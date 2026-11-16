"""Evidence display cannot infer a physical action from absent or mismatched logs."""
from dataclasses import asdict
import json
import pytest
from aiqa.replay.android_plan import TypedAndroidAction
from aiqa.recording.timeline_display import describe_recorded_action

CALL='11111111-1111-4111-8111-111111111111'


def proof(kind='tap',**native):
    return {'schema':'mobile-agent-step-v1','call_id':CALL,'action_id':'ma-'+CALL,'state':'observed','native_calls':1,
        'native':asdict(TypedAndroidAction(kind,**native)),'before_image_hash':'sha256:'+'a'*64,'after_image_hash':'sha256:'+'b'*64}


def display(doc,**changes):
    args={'action_id':'ma-'+CALL,'action_seq':3,'dispatch_state':'observed','log_text':json.dumps(doc),'log_state':'stored',
        'before_state':'stored','after_state':'stored'}
    args.update(changes)
    return describe_recorded_action(**args)


@pytest.mark.parametrize('kind,native,label',[('text',{'text':'synthetic'},'텍스트 입력 기록'),
    ('swipe',{'x':10,'y':10,'x2':20,'y2':30},'스와이프 기록'),('swipe',{'x':10,'y':10,'x2':10,'y2':10},'스와이프 기록'),
    ('key',{'keycode':4},'뒤로가기 기록'),('key',{'keycode':3},'키 입력 기록')])
def test_supported_saved_native_kind_is_readable_without_rewriting_it(kind,native,label):
    doc=proof(kind,**native);before=json.dumps(doc,sort_keys=True)
    assert display(doc).label==label
    assert json.dumps(doc,sort_keys=True)==before


@pytest.mark.parametrize('bad',['foreign_call','different_state','boolean_count','native_kind_type','unrecognized_schema','duplicate','plain','oversize','missing_log'])
def test_untrusted_or_unavailable_log_has_only_ordinal_label(bad):
    doc=proof('tap',x=10,y=20);changes={}
    if bad=='foreign_call':doc['call_id']='22222222-2222-4222-8222-222222222222'
    elif bad=='different_state':doc['state']='unknown'
    elif bad=='boolean_count':doc['native_calls']=True
    elif bad=='native_kind_type':doc['native']['kind']=[]
    elif bad=='unrecognized_schema':doc['schema']='unverified-import'
    elif bad=='duplicate':changes['log_text']=json.dumps(doc)[:-1]+',"state":"observed"}'
    elif bad=='plain':changes['log_text']='adb tap 10 20'
    elif bad=='oversize':changes['log_text']='한'*10000
    elif bad=='missing_log':changes['log_state']='missing'
    assert display(doc,**changes).label=='동작 3'


def test_control_does_not_guess_wait_or_finish_and_corrupt_log_is_honest():
    doc=proof();doc.update(native=None,native_calls=0)
    assert display(doc).label=='제어 단계'
    broken=display(doc,log_text='파일 내용이 보관 hash와 다릅니다.',log_state='missing')
    assert broken.label=='동작 3' and broken.log_label=='손상됨'


def test_observed_without_complete_actual_files_does_not_claim_log_receipt():
    result=display(proof('tap',x=10,y=20),log_text='',log_state='missing',after_state='missing')
    assert result.state_label=='관찰 기록' and result.log_label=='미수신'


def test_unobserved_control_remains_named_without_claiming_native_delivery():
    doc=proof();doc.update(schema='mobile-agent-failure-v1',state='not_sent',native=None,native_calls=0,reason='control_unobserved');doc.pop('after_image_hash')
    result=display(doc,dispatch_state='lookup_failed',after_state='missing')
    assert result.label=='제어 단계' and result.state_label=='화면 확인 중단'


def test_coincident_swipe_coordinates_do_not_invent_original_long_press_intent():
    doc=proof('swipe',x=10,y=10,x2=10,y2=10,duration_ms=800)
    doc.update(schema='mobile-agent-failure-v1',state='unknown',native_calls=0,reason='dispatch_unknown');doc.pop('after_image_hash')
    assert display(doc,dispatch_state='unknown',after_state='missing').label=='스와이프 요청'
