import json
import pytest
from aiqa.worker.recording_reasoning import parse_decision,require_evaluation_action
from aiqa.replay.android_plan import TypedAndroidAction


def decision(**changes):
    return json.dumps(dict(screen='상품 검색창',progress='검색어 입력이 필요함',action="type('mouse')",goal_status='in_progress',evidence='빈 검색창이 보임',**changes),ensure_ascii=False)


def test_eval_accepts_only_observable_summary_and_one_typed_action():
    result=parse_decision(decision())
    assert result.action=="type('mouse')" and result.goal_status=='in_progress'


@pytest.mark.parametrize('value',['{}','{"analysis":"hidden reasoning"}','not json',json.dumps({'screen':'s','progress':'p','action':'finish()','goal_status':'achieved','evidence':''})])
def test_eval_malformed_or_unsupported_decisions_fail_closed(value):
    with pytest.raises(ValueError):parse_decision(value)


@pytest.mark.parametrize('foreground',['com.google.android.permissioncontroller','com.android.settings','com.android.chrome'])
def test_eval_never_taps_or_types_in_permission_or_external_surface(foreground):
    for action in [TypedAndroidAction('tap',x=50,y=50),TypedAndroidAction('text',text='mouse')]:
        with pytest.raises(ValueError):require_evaluation_action(action,foreground=foreground,package='com.ebay.kr.gmarket')
    require_evaluation_action(TypedAndroidAction('key',keycode=4),foreground=foreground,package='com.ebay.kr.gmarket')


def test_eval_restricts_literals_and_keys_even_in_target_app():
    require_evaluation_action(TypedAndroidAction('text',text='mouse'),foreground='com.ebay.kr.gmarket',package='com.ebay.kr.gmarket')
    for action in [TypedAndroidAction('text',text='private email'),TypedAndroidAction('key',keycode=26)]:
        with pytest.raises(ValueError):require_evaluation_action(action,foreground='com.ebay.kr.gmarket',package='com.ebay.kr.gmarket')


@pytest.mark.parametrize('serial,avd,package',[('physical-device','fixture','com.ebay.kr.gmarket'),('emulator-5580','fixture','com.android.settings')])
def test_eval_target_is_only_the_named_gmarket_emulator(serial,avd,package):
    from aiqa.worker.recording_reasoning import require_evaluation_target
    with pytest.raises(ValueError):require_evaluation_target(serial,avd,package)


def test_eval_rejects_current_geometry_or_foreground_drift():
    from dataclasses import replace
    from test_rx_34 import _observation
    from aiqa.worker.recording_reasoning import require_current_frame
    before=_observation()
    require_current_frame(before,before,expected_foreground='app',current_foreground='app')
    for current,foreground in [(replace(before,geometry=replace(before.geometry,rotation=90)),'app'),(before,'permission')]:
        with pytest.raises(ValueError):require_current_frame(before,current,expected_foreground='app',current_foreground=foreground)
