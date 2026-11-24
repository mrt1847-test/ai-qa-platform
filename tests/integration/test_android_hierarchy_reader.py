"""One shared explicit XML collector for the evaluation CLI and check-time reader."""
from pathlib import Path
import subprocess
import pytest
from test_android_observation import AdbBoundary

PACKAGE='com.example.app'
RESOURCE=PACKAGE+':id/query'
XML=b'<hierarchy rotation="0"><node package="com.example.app" resource-id="com.example.app:id/query" text="Ready" password="false" enabled="true"/></hierarchy>'
SUFFIX=b'UI hierchary dumped to: /proc/self/fd/1'


class Boundary(AdbBoundary):
    def __init__(self):
        super().__init__();self.focus='com.example.app';self.focus_count=0;self.xml=XML+SUFFIX+b'\n';self.dump_code=0;self.after_dump=None
    def __call__(self,argv,**kwargs):
        command=tuple(argv[3:])
        if command in {('shell','dumpsys','window'),('exec-out','uiautomator','dump','/proc/self/fd/1')}:
            assert argv[1:3]==['-s','emulator-5580'] and kwargs.get('shell',False) is False
            assert 0<kwargs['timeout']<=15;self.calls.append(command)
            if command[0]=='shell':
                self.focus_count+=1;output=f'mCurrentFocus=Window{{abc u0 {self.focus}/.Activity}}'.encode();code=0
            else:
                output=self.xml;code=self.dump_code
                if self.after_dump:self.after_dump()
            return subprocess.CompletedProcess(argv,code,output,b'PRIVATE_NATIVE_DIAGNOSTIC')
        return super().__call__(argv,**kwargs)


@pytest.fixture
def source(monkeypatch):
    import aiqa.environments.android_observation as module
    fake=Boundary();monkeypatch.setattr(module,'_run_bounded',fake)
    observer=module.AndroidObservationProvider(Path('C:/sdk/adb.exe'),'emulator-5580',expected_avd='AIQA_API36')
    return fake,observer


def reader(source,**changes):
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReader
    return AndroidHierarchyReader(source[1],**{'package':PACKAGE,'checkpoint':lambda:True,**changes})


def test_selected_facts_need_no_screenshot_and_capture_reuses_the_same_collector(source):
    fake,_=source;shared=reader(source)
    fact=shared.observe_targets((RESOURCE,))
    assert fact.snapshot.targets[0].text=='Ready' and fact.foreground==PACKAGE
    assert fact.geometry.rotation==0 and fact.captured_at.endswith('+00:00')
    assert ('exec-out','screencap','-p') not in fake.calls
    fake.calls.clear();observation,foreground=shared.capture_once()
    assert foreground==PACKAGE and observation.dom==XML.decode() and observation.capture_ok
    assert fake.calls.count(('exec-out','screencap','-p'))==1
    assert fake.calls.count(('exec-out','uiautomator','dump','/proc/self/fd/1'))==1
    assert all('cat' not in c and 'rm' not in c for c in fake.calls)


def test_false_control_stops_before_any_native_lookup(source):
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReadError
    with pytest.raises(AndroidHierarchyReadError):reader(source,checkpoint=lambda:False).observe_targets((RESOURCE,))
    assert source[0].calls==[]


def test_control_loss_after_xml_never_returns_an_observation_or_takes_a_screenshot(source):
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReadError
    active=[True];source[0].after_dump=lambda:active.__setitem__(0,False)
    with pytest.raises(AndroidHierarchyReadError):reader(source,checkpoint=lambda:active[0]).capture_once()
    assert ('exec-out','screencap','-p') not in source[0].calls


@pytest.mark.parametrize('damage',['prefix','suffix','two_documents','invalid_utf8','too_large','error','wrong_rotation','wrong_avd','foreign_focus','focus_changed','geometry_changed'])
def test_bad_or_changed_native_evidence_is_not_exposed(source,damage):
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReadError
    fake,_=source
    if damage=='prefix':fake.xml=b'UNTRUSTED_PREFIX'+fake.xml
    elif damage=='suffix':fake.xml+=b'UNTRUSTED_TRAILER'
    elif damage=='two_documents':fake.xml=XML+XML+SUFFIX
    elif damage=='invalid_utf8':fake.xml=b'PRIVATE_XML_CANARY\xff'+SUFFIX
    elif damage=='too_large':fake.xml=b'x'*1048577+SUFFIX
    elif damage=='error':fake.dump_code=1
    elif damage=='wrong_rotation':fake.xml=fake.xml.replace(b'rotation="0"',b'rotation="1"')
    elif damage=='wrong_avd':fake.avd='Other_AVD'
    elif damage=='foreign_focus':fake.focus='other.app'
    elif damage=='focus_changed':fake.after_dump=lambda:setattr(fake,'focus','other.app')
    else:fake.after_dump=lambda:setattr(fake,'rotation',1)
    with pytest.raises(AndroidHierarchyReadError) as raised:reader(source).observe_targets((RESOURCE,))
    assert 'PRIVATE' not in str(raised.value) and 'UNTRUSTED' not in str(raised.value)
    assert raised.value.__context__ is None
    if damage in {'wrong_avd','foreign_focus'}:assert not any('uiautomator' in c for c in fake.calls)


def test_invalid_target_request_does_not_call_adb(source):
    with pytest.raises(ValueError):reader(source).observe_targets(('other.app:id/query',))
    assert source[0].calls==[]


def test_observer_gate_applies_between_metadata_commands(source):
    fake,observer=source;checks=[]
    def gate():checks.append(1);return len(checks)<3
    result=observer.observe(capture=False,checkpoint=gate)
    assert result.state=='unavailable' and result.observation is None and len(fake.calls)<=2


def test_cli_capture_closure_uses_the_shared_reader_and_existing_sanitize(source):
    import ast
    from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReadError
    from aiqa.recording.mobile_agent_session import TransientCapture
    path=Path('tools/android_mobile_agent_record_replay.py')
    main=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='main')
    capture=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='capture_once')
    namespace={'hierarchy':reader(source),'adapter':MobileAgentAndroidAdapter(),
        'AndroidHierarchyReadError':AndroidHierarchyReadError,'TransientCapture':TransientCapture}
    exec(compile(ast.Module(body=[capture],type_ignores=[]),str(path),'exec'),namespace)
    observation,foreground=namespace['capture_once']()
    assert foreground==PACKAGE and observation.dom==XML.decode()
    assert source[0].calls.count(('exec-out','uiautomator','dump','/proc/self/fd/1'))==1


def test_prepared_worker_bounds_check_reads_by_the_claim_timeout(source,tmp_path,monkeypatch):
    import aiqa.environments.android_observation as module
    from aiqa.worker.android_jobs import build_approved_android_replay_handler
    fake,_=source;seen=[]
    def run(argv,**kwargs):
        seen.append(kwargs['timeout']);return fake(argv,**kwargs)
    monkeypatch.setattr(module,'_run_bounded',run)
    handler=build_approved_android_replay_handler(adb_path=Path('C:/sdk/adb.exe'),serial='emulator-5580',expected_avd='AIQA_API36',
        runtime_root=tmp_path,approved_digest='',approved_plan='')
    fact=handler.context.hierarchy_observer(package=PACKAGE,resource_ids=(RESOURCE,),checkpoint=lambda:True,timeout=4)
    assert fact.snapshot.targets[0].text=='Ready' and seen and max(seen)<=4
    assert ('exec-out','screencap','-p') not in fake.calls


def test_prepared_worker_exposes_same_shared_reader_without_running_it_at_build(source,tmp_path):
    from aiqa.worker.android_jobs import build_approved_android_replay_handler
    fake,_=source
    handler=build_approved_android_replay_handler(adb_path=Path('C:/sdk/adb.exe'),serial='emulator-5580',expected_avd='AIQA_API36',
        runtime_root=tmp_path,approved_digest='',approved_plan='')
    assert fake.calls==[] and handler.context.hierarchy_observer is not None
    fact=handler.context.hierarchy_observer(package=PACKAGE,resource_ids=(RESOURCE,),checkpoint=lambda:True,timeout=20)
    assert fact.snapshot.targets[0].text=='Ready'
    assert ('exec-out','screencap','-p') not in fake.calls
    assert handler.authoring_calls_seen==handler.verifier_calls==handler.healer_calls==0


def test_existing_recording_capture_stays_png_only(source):
    from aiqa.worker.android_jobs import _live_android_capture_pair
    fake,_=source
    capture,_=_live_android_capture_pair(adb_path=Path('C:/sdk/adb.exe'),serial='emulator-5580',expected_avd='AIQA_API36')
    assert capture().capture_ok
    assert fake.calls.count(('exec-out','screencap','-p'))==1
    assert not any('uiautomator' in c for c in fake.calls)


def test_late_successful_native_read_is_discarded(source,monkeypatch):
    import aiqa.environments.android_hierarchy_reader as module
    clock=[0.0];monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    source[0].after_dump=lambda:clock.__setitem__(0,31.0)
    with pytest.raises(module.AndroidHierarchyReadError):reader(source,total_timeout=30).capture_once()
    assert ('exec-out','screencap','-p') not in source[0].calls


def test_shared_deadline_bounds_the_existing_observer_without_mutating_configuration(source,monkeypatch):
    import aiqa.environments.android_observation as module
    clock=[10.0];monkeypatch.setattr(module.time,'monotonic',lambda:clock[0]);seen=[]
    original=source[0]
    def run(argv,**kwargs):seen.append(kwargs['timeout']);return original(argv,**kwargs)
    monkeypatch.setattr(module,'_run_bounded',run)
    source[1].observe(capture=False,deadline=10.25,checkpoint=lambda:True)
    assert seen and max(seen)<=0.25 and source[1].observation_timeout==30
    seen.clear();assert source[1].observe(capture=False,deadline=9).state=='unavailable' and seen==[]


def test_configured_device_identity_cannot_change_during_authority_callback(source):
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReadError
    fake,observer=source;checks=[]
    def gate():
        checks.append(1)
        if len(checks)==2:observer.serial='emulator-5582'
        return True
    with pytest.raises(AndroidHierarchyReadError):reader(source,checkpoint=gate).observe_targets((RESOURCE,))
    assert fake.calls==[]


def test_cli_does_not_retry_a_wrong_named_device_as_a_screen_transition(source):
    import ast
    from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReadError
    from aiqa.recording.mobile_agent_session import TransientCapture,capture_stable
    path=Path('tools/android_mobile_agent_record_replay.py')
    main=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='main')
    capture=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='capture_once')
    namespace={'hierarchy':reader(source),'adapter':MobileAgentAndroidAdapter(),
        'AndroidHierarchyReadError':AndroidHierarchyReadError,'TransientCapture':TransientCapture}
    exec(compile(ast.Module(body=[capture],type_ignores=[]),str(path),'exec'),namespace)
    source[0].avd='Other_AVD'
    with pytest.raises(AndroidHierarchyReadError):capture_stable(namespace['capture_once'],pause=lambda _:None,max_reads=3)
    assert source[0].calls.count(('get-state',))==1 and not any('uiautomator' in c for c in source[0].calls)


def test_trailing_line_padding_cannot_bypass_the_wire_budget(source):
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReadError
    source[0].xml=XML+SUFFIX+b'\n'*1100000
    with pytest.raises(AndroidHierarchyReadError):reader(source).observe_targets((RESOURCE,))


@pytest.mark.parametrize('method',['targets','capture'])
@pytest.mark.parametrize('failure',['control','deadline'])
def test_projection_is_inside_the_final_authority_and_deadline_fence(source,monkeypatch,method,failure):
    import aiqa.environments.android_hierarchy_reader as module
    clock=[0.0];active=[True];monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    name='parse_android_hierarchy' if method=='targets' else 'replace';actual=getattr(module,name)
    def project(*args,**kwargs):
        value=actual(*args,**kwargs)
        if failure=='control':active[0]=False
        else:clock[0]=31.0
        return value
    monkeypatch.setattr(module,name,project)
    shared=reader(source,checkpoint=lambda:active[0])
    with pytest.raises(module.AndroidHierarchyReadError) as raised:
        if method=='targets':shared.observe_targets((RESOURCE,))
        else:shared.capture_once()
    assert raised.value.__context__ is None


def test_command_cap_reaches_metadata_and_dump_without_mutating_shared_observer(source,monkeypatch):
    import aiqa.environments.android_observation as module
    seen=[];actual=source[0]
    def run(argv,**kwargs):seen.append(kwargs['timeout']);return actual(argv,**kwargs)
    monkeypatch.setattr(module,'_run_bounded',run)
    reader(source,command_timeout=0.25).observe_targets((RESOURCE,))
    assert seen and max(seen)<=0.25 and source[1].command_timeout==10


@pytest.mark.parametrize('failure',['nonzero','empty','null_root'])
def test_cli_retries_only_transient_dump_reads_and_keeps_bounded_transition_metadata(source,tmp_path,failure):
    import ast,time,json
    from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter
    from aiqa.environments.android_hierarchy_reader import AndroidHierarchyReadError
    from aiqa.recording.mobile_agent_session import TransientCapture,capture_stable,persist
    fake=source[0];valid=fake.xml
    if failure=='nonzero':fake.dump_code=1
    elif failure=='null_root':fake.xml=b'ERROR: null root node returned by UiTestAutomationBridge.\n'
    else:fake.xml=b''
    def recover():fake.dump_code=0;fake.xml=valid
    fake.after_dump=recover
    path=Path('tools/android_mobile_agent_record_replay.py')
    main=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='main')
    capture=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='capture_once')
    namespace={'hierarchy':reader(source),'adapter':MobileAgentAndroidAdapter(),'AndroidHierarchyReadError':AndroidHierarchyReadError,
        'TransientCapture':TransientCapture,'persist':persist,'out':tmp_path,'time':time,'transitions':[],'transition_count':[0]}
    exec(compile(ast.Module(body=[capture],type_ignores=[]),str(path),'exec'),namespace)
    assert capture_stable(namespace['capture_once'],pause=lambda _:None,max_reads=3)[0].capture_ok
    assert fake.calls.count(('exec-out','uiautomator','dump','/proc/self/fd/1'))==2
    assert fake.calls.count(('exec-out','screencap','-p'))==1
    rows=json.loads((tmp_path/'capture-transitions.json').read_text())
    assert len(rows)==1 and rows[0]['count']==1 and 'elapsed' in rows[0]
    assert 'PRIVATE' not in json.dumps(rows)
