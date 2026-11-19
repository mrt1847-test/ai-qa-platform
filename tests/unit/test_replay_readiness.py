"""Readiness polls observations, never replays an input while waiting."""
from io import BytesIO
import json

from PIL import Image, ImageDraw
import pytest

from aiqa.contracts.actions import CaptureGeometry, Observation
from aiqa.replay.android_plan import PlanRejected, TypedAndroidAction


def png(*, ready=True, size=(160, 240), status=0):
    image = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 12), fill=(status, 0, 0))
    if ready:
        draw.rectangle((50, 90, 110, 150), fill='blue')
        draw.rectangle((65, 105, 95, 135), fill='yellow')
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def observation(data=None, *, rotation=0, size=(160, 240)):
    geo = CaptureGeometry(*size, *size, 'identity', rotation, (0, 0, *size))
    return Observation('capture', '2026-11-19T00:00:00+00:00', geo,
                       data if data is not None else png(size=size), '', '', (), '', True, 'android')


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def pause(self, seconds):
        self.now += seconds


def test_wait_reads_until_recorded_target_appears_and_returns_fresh_capture():
    from aiqa.replay.readiness import readiness_condition, wait_for_ready
    condition = readiness_condition(png(), TypedAndroidAction('tap', x=80, y=120))
    frames = [observation(png(ready=False)), observation(png(ready=False)), observation()]
    expected = frames[-1]
    clock = Clock()
    assert wait_for_ready(lambda: frames.pop(0), condition, lambda: True,
                          clock=clock, pause=clock.pause) is expected
    assert clock.now >= .5


def test_never_ready_times_out_with_last_observation_and_stable_reason():
    from aiqa.replay.readiness import ReadinessTimeout, readiness_condition, wait_for_ready
    condition = readiness_condition(png(), TypedAndroidAction('tap', x=80, y=120))
    current = observation(png(ready=False))
    clock = Clock()
    with pytest.raises(ReadinessTimeout) as error:
        wait_for_ready(lambda: current, condition, lambda: True, timeout=1,
                       clock=clock, pause=clock.pause)
    assert error.value.reason == 'loading_timeout'
    assert error.value.last_observation is current
    assert clock.now == 1


def test_cancel_before_capture_does_not_read_or_dispatch():
    from aiqa.replay.readiness import ReadinessCancelled, readiness_condition, wait_for_ready
    condition = readiness_condition(png(), TypedAndroidAction('tap', x=80, y=120))
    def forbidden():
        pytest.fail('cancelled wait must not capture')
    with pytest.raises(ReadinessCancelled):
        wait_for_ready(forbidden, condition, lambda: False)


def test_cancel_and_timeout_after_capture_cannot_return_ready():
    from aiqa.replay.readiness import ReadinessCancelled, ReadinessTimeout, readiness_condition, wait_for_ready
    condition = readiness_condition(png(), TypedAndroidAction('tap', x=80, y=120))
    checks = iter((True, False))
    with pytest.raises(ReadinessCancelled):
        wait_for_ready(observation, condition, lambda: next(checks))
    clock = Clock()
    def slow_capture():
        clock.now = 2
        return observation()
    with pytest.raises(ReadinessTimeout) as error:
        wait_for_ready(slow_capture, condition, lambda: True, timeout=1, clock=clock)
    assert error.value.last_observation is not None


@pytest.mark.parametrize('rotation,size', [(90, (160, 240)), (0, (240, 160))])
def test_readiness_refuses_geometry_drift(rotation, size):
    from aiqa.environments.android_observation import AndroidGeometryError
    from aiqa.replay.readiness import readiness_condition, wait_for_ready
    condition = readiness_condition(png(), TypedAndroidAction('tap', x=80, y=120))
    with pytest.raises(AndroidGeometryError):
        wait_for_ready(lambda: observation(rotation=rotation, size=size), condition, lambda: True)


def test_settle_requires_continuous_consistency_but_ignores_status_bar_clock():
    from aiqa.replay.readiness import wait_for_settled
    frames = [observation(png(ready=False)), observation(png(status=1)),
              observation(png(status=2)), observation(png(status=3))]
    expected = frames[-1]
    clock = Clock()
    assert wait_for_settled(lambda: frames.pop(0), lambda: True,
                            clock=clock, pause=clock.pause) is expected
    assert clock.now >= .75


def test_settle_does_not_accept_changing_content_and_is_bounded_with_stuck_clock():
    from aiqa.replay.readiness import ReadinessTimeout, wait_for_settled
    count = 0
    def capture():
        nonlocal count
        count += 1
        return observation(png(ready=bool(count % 2)))
    with pytest.raises(ReadinessTimeout):
        wait_for_settled(capture, lambda: True, timeout=.5,
                         clock=lambda: 0, pause=lambda _: None)
    assert count <= 4


@pytest.mark.parametrize('action', [TypedAndroidAction('swipe', x=80, y=180, x2=80, y2=60),
                                  TypedAndroidAction('text', text='query'),
                                  TypedAndroidAction('key', keycode=66)])
def test_non_tap_conditions_compare_recorded_app_content(action):
    from aiqa.replay.readiness import readiness_condition, wait_for_ready
    clock = Clock()
    condition = readiness_condition(png(), action)
    frames = [observation(png(ready=False)), observation()]
    assert wait_for_ready(lambda: frames.pop(0), condition, lambda: True,
                          clock=clock, pause=clock.pause).capture_ok
    assert clock.now > 0


def native_mapping(condition=None, post_wait=None):
    from aiqa.replay.android_native_trace import native_event
    event = native_event(TypedAndroidAction('tap', x=80, y=120), observation(), action_id='one', line=1)
    if condition is not None:
        event['readiness'] = condition
    if post_wait is not None:
        event['post_wait_seconds'] = post_wait
    return json.dumps({'schema': 'android-native-trace-v2', 'native_action_count': 1, 'events': [event]})


def test_old_v2_remains_supported_and_new_conditions_and_waits_roundtrip():
    from aiqa.replay.android_native_trace import parse_native_trace
    from aiqa.replay.readiness import readiness_condition
    old = parse_native_trace(native_mapping())[0]
    assert old.readiness is None and old.post_wait_seconds == 0
    condition = readiness_condition(png(), TypedAndroidAction('tap', x=80, y=120))
    new = parse_native_trace(native_mapping(condition, 1.25))[0]
    assert new.readiness == condition and new.post_wait_seconds == 1.25
    assert new.action == old.action


@pytest.mark.parametrize('damage', ['extra', 'bounds', 'pixels', 'size', 'tolerance', 'rotation', 'dimensions'])
def test_tampered_or_unbounded_conditions_are_rejected_before_capture(damage):
    from aiqa.replay.android_native_trace import parse_native_trace
    from aiqa.replay.readiness import readiness_condition
    condition = readiness_condition(png(), TypedAndroidAction('tap', x=80, y=120))
    if damage == 'extra': condition['shell'] = 'input tap 1 1'
    elif damage == 'bounds': condition['bounds'] = [-1, 0, 1, 2]
    elif damage == 'pixels': condition['rgb'] = 'A' * 100_000
    elif damage == 'size': condition['sample_size'] = [10000, 10000]
    elif damage == 'tolerance': condition['max_mean_error'] = 255
    elif damage == 'rotation': condition['rotation'] = 90
    else: condition['width'] = 161
    with pytest.raises(PlanRejected):
        parse_native_trace(native_mapping(condition))


@pytest.mark.parametrize('duration', [-1, 30.1, True, float('nan'), float('inf'), '1'])
def test_native_wait_must_be_finite_and_bounded(duration):
    from aiqa.replay.android_native_trace import parse_native_trace
    with pytest.raises(PlanRejected):
        parse_native_trace(native_mapping(post_wait=duration))


def test_native_event_cannot_hide_invalid_zero_like_wait_by_omitting_it():
    from aiqa.replay.android_native_trace import native_event
    with pytest.raises(PlanRejected):
        native_event(TypedAndroidAction('tap', x=80, y=120), observation(),
                     action_id='one', line=1, post_wait_seconds=False)
