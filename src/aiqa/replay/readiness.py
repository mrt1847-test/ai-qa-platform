"""Bounded read-only visual preconditions and post-input settling.

Matching the recorded patch is evidence that the same visual target is present,
not evidence of semantic success. Settling only detects quiet app pixels: a
static loading page can settle, so callers still need a final assertion. These
helpers never issue an input, retry an input, invoke a model, or move coordinates.
Capture callbacks must enforce their own bounded I/O deadline; checkpoints also
run immediately before and after each read so a late result cannot authorize input.
"""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
import math
import time

from aiqa.environments.android_observation import AndroidGeometryError, require_usable_geometry
from aiqa.replay.android_plan import PlanRejected

_SCHEMA = 'android-visual-readiness-v1'
_SAMPLE_SIZE = (16, 16)
_MEAN_ERROR = 8
_POLL_SECONDS = .25
_SETTLE_SECONDS = .5
_FIELDS = frozenset(('schema', 'width', 'height', 'rotation', 'bounds', 'sample_size', 'rgb', 'max_mean_error'))


class ReadinessTimeout(TimeoutError):
    reason = 'loading_timeout'

    def __init__(self, last_observation=None):
        super().__init__(self.reason)
        self.last_observation = last_observation


class ReadinessCancelled(RuntimeError):
    reason = 'readiness_cancelled'

    def __init__(self):
        super().__init__(self.reason)


def _image(png):
    from PIL import Image
    if type(png) is not bytes or not 0 < len(png) <= 8_000_000:
        raise ValueError('readiness capture size invalid')
    with Image.open(BytesIO(png)) as image:
        if image.format != 'PNG' or min(image.size) < 1 or image.width * image.height > 16_000_000:
            raise ValueError('readiness capture image invalid')
        return image.convert('RGB')


def _sample(image, bounds):
    from PIL import Image
    return image.crop(tuple(bounds)).resize(_SAMPLE_SIZE, Image.Resampling.BILINEAR).tobytes()


def _content_bounds(width, height):
    # Exclude the status clock and bottom navigation; never ignore app content
    # merely because it might be a progress indicator.
    top = min(height - 1, math.ceil(height * .06))
    bottom = max(top + 1, math.floor(height * .97))
    return [0, top, width, bottom]


def readiness_condition(png, action, *, rotation=0):
    """Create a <=2KB signature at recorded physical coordinates.

    Taps use a local target patch; swipes, keys and text compare app content.
    This intentionally has no OCR/semantic interpretation or automatic healing.
    """
    image = _image(png)
    width, height = image.size
    bounds = _content_bounds(width, height)
    if action.kind == 'tap':
        if (type(action.x) is not int or type(action.y) is not int
            or not 0 <= action.x < width or not 0 <= action.y < height):
            raise PlanRejected('readiness target invalid')
        radius = max(12, min(96, round(min(width, height) * .06)))
        bounds = [max(0, action.x - radius), max(0, action.y - radius),
                  min(width, action.x + radius + 1), min(height, action.y + radius + 1)]
    elif action.kind not in {'swipe', 'text', 'key'}:
        raise PlanRejected('readiness action unsupported')
    condition = {'schema': _SCHEMA, 'width': width, 'height': height, 'rotation': rotation,
                 'bounds': bounds, 'sample_size': list(_SAMPLE_SIZE),
                 'rgb': base64.b64encode(_sample(image, bounds)).decode('ascii'),
                 'max_mean_error': _MEAN_ERROR}
    return validate_readiness_condition(condition)


def validate_readiness_condition(raw, *, width=None, height=None, rotation=None):
    """Reject extra fields, permissive tolerances and unbounded signature data."""
    try:
        if type(raw) is not dict or set(raw) != _FIELDS or raw['schema'] != _SCHEMA:
            raise ValueError()
        w, h, r = (raw[key] for key in ('width', 'height', 'rotation'))
        if (type(w) is not int or type(h) is not int or min(w, h) < 1 or w * h > 16_000_000
            or type(r) is not int or r not in {0, 90, 180, 270}
            or width is not None and w != width or height is not None and h != height
            or rotation is not None and r != rotation):
            raise ValueError()
        bounds = raw['bounds']
        if (type(bounds) is not list or len(bounds) != 4 or any(type(n) is not int for n in bounds)
            or not 0 <= bounds[0] < bounds[2] <= w or not 0 <= bounds[1] < bounds[3] <= h):
            raise ValueError()
        if (type(raw['sample_size']) is not list or raw['sample_size'] != list(_SAMPLE_SIZE)
            or any(type(n) is not int for n in raw['sample_size'])
            or type(raw['max_mean_error']) is not int or raw['max_mean_error'] != _MEAN_ERROR
            or type(raw['rgb']) is not str or len(raw['rgb']) != 1024):
            raise ValueError()
        pixels = base64.b64decode(raw['rgb'], validate=True)
        if len(pixels) != 768 or base64.b64encode(pixels).decode('ascii') != raw['rgb']:
            raise ValueError()
        return {**raw, 'bounds': list(bounds), 'sample_size': list(raw['sample_size'])}
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise PlanRejected('readiness condition invalid') from exc


def _matches(expected, actual):
    errors = [abs(a - b) for a, b in zip(expected, actual, strict=True)]
    return sum(errors) <= _MEAN_ERROR * len(errors) and sum(error > 32 for error in errors) <= len(errors) * .05


def _geometry(observation, expected=None):
    geo = require_usable_geometry(observation)
    identity = (geo.physical_width, geo.physical_height, geo.rotation)
    if expected is not None and identity != expected:
        raise AndroidGeometryError('readiness geometry changed')
    image = _image(observation.png)
    if image.size != identity[:2]:
        raise AndroidGeometryError('readiness image geometry changed')
    return identity, image


def _wait(capture, checkpoint, evaluate, *, timeout, clock, pause):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError('readiness timeout must be finite and in (0, 30]')
    deadline = clock() + timeout
    last = None

    def allowed():
        if checkpoint() is False:
            raise ReadinessCancelled()

    # The read cap remains bounded even for a broken/no-op clock or pause.
    max_reads = math.ceil(timeout / _POLL_SECONDS) + 1
    for index in range(max_reads):
        allowed()
        if clock() >= deadline:
            raise ReadinessTimeout(last)
        last = capture()
        allowed()
        if clock() >= deadline:
            raise ReadinessTimeout(last)
        if evaluate(last, clock()):
            return last
        if index + 1 == max_reads:
            break
        allowed()
        pause(min(_POLL_SECONDS, max(0, deadline - clock())))
        allowed()
    raise ReadinessTimeout(last)


def wait_for_ready(capture, condition, checkpoint, *, timeout=30.0, clock=time.monotonic, pause=time.sleep):
    """Poll fresh observations until the recorded visual precondition matches."""
    checked = validate_readiness_condition(condition)
    expected = base64.b64decode(checked['rgb'])
    identity = tuple(checked[key] for key in ('width', 'height', 'rotation'))

    def evaluate(observation, now):
        _, image = _geometry(observation, identity)
        return _matches(expected, _sample(image, checked['bounds']))

    return _wait(capture, checkpoint, evaluate, timeout=timeout, clock=clock, pause=pause)


def wait_for_settled(capture, checkpoint, *, timeout=30.0, clock=time.monotonic, pause=time.sleep):
    """Require consistent app pixels for >=0.5s; this is not a success assertion."""
    identity = anchor = stable_since = None

    def evaluate(observation, now):
        nonlocal identity, anchor, stable_since
        identity, image = _geometry(observation, identity)
        current = _sample(image, _content_bounds(*identity[:2]))
        if anchor is None or not _matches(anchor, current):
            anchor, stable_since = current, now
            return False
        return now - stable_since >= _SETTLE_SECONDS

    return _wait(capture, checkpoint, evaluate, timeout=timeout, clock=clock, pause=pause)
