import json,hashlib,subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_rx_34 import _observation
from aiqa.replay.android_runner import AndroidDeterministicDriver


def setup(tmp_path,*,fail_after=False,foreground='com.ebay.kr.gmarket'):
    from aiqa.recording.mobile_agent_session import ObservedMobileSession
    from aiqa.adapters.mobile_agent_upstream import load_upstream
    calls=[];count=[0]
    def capture():
        count[0]+=1
        if fail_after and count[0]==3:raise RuntimeError('after unavailable')
        return _observation(),foreground
    def run(argv,timeout):calls.append(tuple(argv));return subprocess.CompletedProcess(argv,0,b'',b'')
    driver=AndroidDeterministicDriver(Path('C:/platform-tools/adb.exe'),'emulator-5580',runner=run)
    u=load_upstream()
    response='Action: Search.\n<tool_call>\n{"name":"mobile_use","arguments":{"action":"click","coordinate":[500,500]}}\n</tool_call>'
    session=ObservedMobileSession(upstream=u,capture=capture,driver=driver,output=tmp_path/'evidence',package='com.ebay.kr.gmarket',complete=lambda conversation:SimpleNamespace(content=response,actual_model='gpt-6-luna',input_tokens=10,output_tokens=5,reasoning_tokens=0,cached_input_tokens=0,provider_request_id='fixture'))
    return session,calls


def test_ack_source_is_saved_even_if_after_capture_fails(tmp_path):
    s,calls=setup(tmp_path,fail_after=True);s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}])
    with pytest.raises(RuntimeError):s.click(*s.scaled['coordinate'])
    trace=json.loads((s.output/'native-trace.json').read_text())
    assert len(calls)==trace['native_action_count']==1
    assert s.report['steps'][0]['state']=='acknowledged_after_missing'


def test_external_permission_screen_cannot_receive_tap(tmp_path):
    s,calls=setup(tmp_path,foreground='com.google.android.permissioncontroller');s.get_screenshot(str(tmp_path/'frame.png'))
    with pytest.raises(ValueError):s.predict([{'role':'user','content':[{'text':'goal'}]}])
    assert calls==[]


def test_completed_trace_replay_has_same_argv_and_no_model_port(tmp_path):
    from aiqa.replay.mobile_agent_replay import replay_saved_trace
    s,calls=setup(tmp_path);s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}]);s.click(*s.scaled['coordinate'])
    source=s.output/'native-trace.json';expected=hashlib.sha256(source.read_bytes()).hexdigest()
    target={'serial':'emulator-5580','avd':'fixture','package':s.package};s.report['status']='model_claimed_success';s.save_pin(target)
    pin=s.output/'recording-pin.json'
    report=replay_saved_trace(source=source,expected_hash=expected,pin_path=pin,pin_hash=hashlib.sha256(pin.read_bytes()).hexdigest(),target=target,capture=s.capture,driver=s.driver,output=tmp_path/'replay',package=s.package,sleep=lambda _:None)
    assert report['model_calls']==0 and report['status']=='replayed_pending_observation'
    assert calls[0]==calls[1] and report['steps'][0]['argv']==list(calls[0])


def test_changed_source_replay_never_captures_or_dispatches(tmp_path):
    from aiqa.replay.mobile_agent_replay import replay_saved_trace
    s,calls=setup(tmp_path);source=tmp_path/'changed.json';source.write_text('{}')
    def deny():raise AssertionError('should not touch device')
    with pytest.raises(ValueError):replay_saved_trace(source=source,expected_hash='0'*64,pin_path=tmp_path/'missing-pin',pin_hash='0'*64,target={},capture=deny,driver=s.driver,output=tmp_path/'replay',package=s.package)
    assert calls==[]


def test_same_package_overlay_before_native_is_refused(tmp_path):
    from dataclasses import replace
    from test_rx_34 import _png
    s,calls=setup(tmp_path);s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}])
    obs=_observation();changed=bytearray(obs.png)
    # Build a valid white frame of the same geometry instead of black.
    from PIL import Image
    from io import BytesIO
    b=BytesIO();Image.new('RGB',(100,200),'white').save(b,format='PNG')
    s.capture=lambda:(replace(obs,png=b.getvalue()),s.package)
    with pytest.raises(ValueError):s.click(*s.scaled['coordinate'])
    assert calls==[]


def test_native_timeout_does_not_retry_or_invent_ack(tmp_path):
    s,calls=setup(tmp_path);s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}])
    def timeout(argv,limit):calls.append(tuple(argv));raise subprocess.TimeoutExpired(argv,limit)
    s.driver._runner=timeout
    with pytest.raises(Exception):s.click(*s.scaled['coordinate'])
    assert len(calls)==1 and s.report['steps'][0]['state']=='dispatch_started'
    assert s.source==[] and not (s.output/'native-trace.json').exists()


def test_unrelated_foreground_is_not_sent_to_model(tmp_path):
    s,calls=setup(tmp_path,foreground='other.private.app');s.get_screenshot(str(tmp_path/'frame.png'))
    paid=[];s.complete=lambda c:paid.append(c)
    with pytest.raises(ValueError):s.predict([{'role':'user','content':[{'text':'goal'}]}])
    assert paid==[]


def test_replay_rejects_a_different_target_and_incomplete_recording(tmp_path):
    from aiqa.replay.mobile_agent_replay import load_replay_reference
    s,calls=setup(tmp_path);s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}]);s.click(*s.scaled['coordinate'])
    target={'serial':'emulator-5580','avd':'fixture','package':s.package};s.report['status']='model_claimed_success';s.save_pin(target)
    source=s.output/'native-trace.json';pin=s.output/'recording-pin.json'
    with pytest.raises(ValueError):load_replay_reference(source,hashlib.sha256(source.read_bytes()).hexdigest(),pin,hashlib.sha256(pin.read_bytes()).hexdigest(),dict(target,avd='other-avd'))
    s.report['status']='stopped';s.save_pin(target)
    with pytest.raises(ValueError):load_replay_reference(source,hashlib.sha256(source.read_bytes()).hexdigest(),pin,hashlib.sha256(pin.read_bytes()).hexdigest(),target)


def test_replay_rejects_path_action_ids_before_device_access(tmp_path):
    from aiqa.replay.mobile_agent_replay import load_replay_reference
    s,calls=setup(tmp_path);s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}]);s.click(*s.scaled['coordinate'])
    target={'serial':'emulator-5580','avd':'fixture','package':s.package};s.report['status']='model_claimed_success';s.save_pin(target)
    source=s.output/'native-trace.json';raw=json.loads(source.read_text());raw['events'][0]['action_id']='../../escape';source.write_text(json.dumps(raw))
    pin=s.output/'recording-pin.json';data=json.loads(pin.read_text());data['source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest();pin.write_text(json.dumps(data))
    with pytest.raises(ValueError):load_replay_reference(source,data['source_sha256'],pin,hashlib.sha256(pin.read_bytes()).hexdigest(),target)


def test_replay_deadline_expiring_during_journal_prevents_send(tmp_path,monkeypatch):
    import aiqa.replay.mobile_agent_replay as replay
    s,calls=setup(tmp_path);s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}]);s.click(*s.scaled['coordinate'])
    target={'serial':'emulator-5580','avd':'fixture','package':s.package};s.report['status']='model_claimed_success';s.save_pin(target)
    source=s.output/'native-trace.json';pin=s.output/'recording-pin.json';clock=[0.0];actual=replay.persist
    monkeypatch.setattr(replay.time,'monotonic',lambda:clock[0])
    def persist(path,data):
        actual(path,data)
        if isinstance(data,dict) and data.get('steps') and data['steps'][-1]['state']=='dispatch_started':clock[0]=241.0
    monkeypatch.setattr(replay,'persist',persist)
    with pytest.raises(RuntimeError):replay.replay_saved_trace(source=source,expected_hash=hashlib.sha256(source.read_bytes()).hexdigest(),pin_path=pin,pin_hash=hashlib.sha256(pin.read_bytes()).hexdigest(),target=target,capture=s.capture,driver=s.driver,output=tmp_path/'replay',package=s.package,sleep=lambda _:None)
    assert len(calls)==1


def test_replay_screen_drift_saves_both_frames_and_stops(tmp_path):
    from dataclasses import replace
    from io import BytesIO
    from PIL import Image
    import aiqa.replay.mobile_agent_replay as replay
    s,calls=setup(tmp_path);s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}]);s.click(*s.scaled['coordinate'])
    target={'serial':'emulator-5580','avd':'fixture','package':s.package};s.report['status']='model_claimed_success';s.save_pin(target)
    source=s.output/'native-trace.json';pin=s.output/'recording-pin.json';b=BytesIO();Image.new('RGB',(100,200),'white').save(b,format='PNG')
    capture=lambda:(replace(_observation(),png=b.getvalue()),s.package)
    with pytest.raises(ValueError):replay.replay_saved_trace(source=source,expected_hash=hashlib.sha256(source.read_bytes()).hexdigest(),pin_path=pin,pin_hash=hashlib.sha256(pin.read_bytes()).hexdigest(),target=target,capture=capture,driver=s.driver,output=tmp_path/'replay',package=s.package)
    assert len(calls)==1 and (tmp_path/'replay/step-001-before.png').is_file() and (tmp_path/'replay/step-001-reference.png').is_file()


def test_luna_images_match_original_thousand_square_tool_frame(tmp_path):
    from aiqa.recording.mobile_agent_session import conversation
    import base64
    from io import BytesIO
    from PIL import Image
    p=tmp_path/'frame.png';raw=_observation().png;p.write_bytes(raw)
    messages=conversation([{'role':'user','content':[{'image':'file://'+str(p)}]}],tmp_path)
    image=base64.b64decode(messages[0]['content'][0]['image_url'].split(',',1)[1])
    assert Image.open(BytesIO(image)).size==(1000,1000)
    assert p.read_bytes()==raw


def test_transitional_capture_retries_reads_only_and_is_bounded():
    from aiqa.recording.mobile_agent_session import capture_stable,TransientCapture
    calls=[]
    def read():
        calls.append('read')
        if len(calls)<3:raise TransientCapture('foreground transition')
        return 'observed'
    assert capture_stable(read,pause=lambda _:None,max_reads=3)=='observed' and len(calls)==3
    calls.clear()
    def unavailable():calls.append('read');raise TransientCapture('foreground transition')
    with pytest.raises(TransientCapture):capture_stable(unavailable,pause=lambda _:None,max_reads=3)
    assert len(calls)==3


def test_wrong_device_capture_is_never_retried():
    from aiqa.recording.mobile_agent_session import capture_stable
    calls=[]
    def wrong():calls.append('read');raise ValueError('wrong device')
    with pytest.raises(ValueError):capture_stable(wrong,pause=lambda _:None)
    assert len(calls)==1


def test_text_replay_does_not_compare_the_screen():
    from aiqa.recording.mobile_agent_frames import require_frame_pixels,require_guarded_frame
    from aiqa.replay.android_plan import TypedAndroidAction
    from PIL import Image
    from io import BytesIO
    def png(color):
        out=BytesIO();Image.new('RGB',(720,1600),color).save(out,format='PNG');return out.getvalue()
    action=TypedAndroidAction('text',text='mouse')
    assert require_frame_pixels(png('white'),png('black'),action) is None
    assert require_guarded_frame(png('white'),png('black'),action)['kind']=='unchecked'
    with pytest.raises(ValueError):require_frame_pixels(png('white'),png('black'),TypedAndroidAction('key',keycode=66))


def test_stable_resource_target_survives_only_pixel_animation():
    from aiqa.recording.mobile_agent_frames import require_guarded_frame
    from aiqa.replay.android_plan import TypedAndroidAction
    from PIL import Image
    from io import BytesIO
    xml='<hierarchy rotation="0"><node resource-id="com.ebay.kr.gmarket:id/search" package="com.ebay.kr.gmarket" class="android.view.View" bounds="[0,0][100,100]" clickable="true" enabled="true" text="" content-desc="Search"/></hierarchy>'
    original=_observation().png;b=BytesIO();Image.new('RGB',(100,200),'white').save(b,format='PNG')
    assert require_guarded_frame(original,b.getvalue(),TypedAndroidAction('tap',x=50,y=50),xml,xml)['kind']=='resource_id'
    with pytest.raises(ValueError):require_guarded_frame(original,b.getvalue(),TypedAndroidAction('tap',x=50,y=50),xml,xml.replace(':id/search',':id/buy'))
    with pytest.raises(ValueError):require_guarded_frame(original,b.getvalue(),TypedAndroidAction('tap',x=50,y=50),xml,xml.replace('</hierarchy>','<node resource-id="" package="com.ebay.kr.gmarket" bounds="[0,0][100,100]" clickable="true" enabled="true"/></hierarchy>'))


def test_recorded_hierarchy_between_decimal_and_binary_megabyte_limits_is_replayable(tmp_path):
    from dataclasses import replace
    from aiqa.replay.mobile_agent_replay import load_replay_reference
    s,_=setup(tmp_path)
    raw='<hierarchy rotation="0">'+' '*1000000+'</hierarchy>'
    s.capture=lambda:(replace(_observation(),dom=raw),s.package)
    s.get_screenshot(str(tmp_path/'frame.png'));s.predict([{'role':'user','content':[{'text':'goal'}]}]);s.click(*s.scaled['coordinate'])
    target={'serial':'emulator-5580','avd':'fixture','package':s.package};s.report['status']='model_claimed_success';s.save_pin(target)
    source=s.output/'native-trace.json';pin=s.output/'recording-pin.json'
    steps,refs=load_replay_reference(source,hashlib.sha256(source.read_bytes()).hexdigest(),pin,hashlib.sha256(pin.read_bytes()).hexdigest(),target)
    assert len(steps)==1 and refs[0][2]==raw
