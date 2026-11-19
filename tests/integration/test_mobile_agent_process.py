from pathlib import Path
from types import SimpleNamespace
import json,subprocess
import pytest
from test_rx_34 import _observation


def call(tmp_path,*,allowed=lambda:True,timeout=20,fail_native=False,max_actions=50,model_after=None,secrets=(),repeat_click=False,max_steps=3,model_boundary=1,native_boundary=1,capture_override=None):
    from aiqa.worker.mobile_agent_process import run_mobile_agent_process
    seen=[];native=[]
    def model(request,*,before_send):

        for _ in range(model_boundary):before_send()
        seen.append(request)
        if model_after:model_after()
        args={'action':'click','coordinate':[500,500]} if repeat_click or len(seen)==1 else {'action':'terminate','status':'success'}
        return json.dumps({'summary':'next','name':'mobile_use','arguments':args})
    def dispatch(action,before,*,before_send):

        for _ in range(native_boundary):before_send()
        native.append(action)
        if fail_native:raise TimeoutError('fixture ambiguous native')
        return SimpleNamespace(native_calls=1,outcome='acknowledged')
    result=run_mobile_agent_process(output=tmp_path/'process',instruction='Open search',capture=capture_override or _observation,model=model,
        dispatch=dispatch,secrets=secrets,allowed=allowed,max_steps=max_steps,max_actions=max_actions,timeout_seconds=timeout)
    return result,seen,native


def test_original_main_executes_in_child_with_parent_owned_io(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','must-never-enter-child')
    monkeypatch.setenv('AIQA_WORKER_TOKEN','must-never-enter-child')
    cwd=Path.cwd();r,seen,native=call(tmp_path)
    assert r.status=='claimed_success' and r.model_requests==2 and r.native_actions==1 and not r.ambiguous_dispatch
    assert r.receipt['main_invocations']==1 and r.receipt['upstream_commit']=='81fa28b564ef7a695521500bc15a0e1324b2b394'
    assert r.receipt['network_disabled'] and r.receipt['credential_environment_names']==[]
    assert (native[0].x,native[0].y)==(50,100) and Path.cwd()==cwd
    assert any(m['role']=='assistant' for m in seen[1]['messages'])
    assert all('must-never-enter-child' not in p.read_text(encoding='utf-8',errors='ignore') for p in (tmp_path/'process').rglob('*') if p.is_file() and p.suffix!='.png')


def test_cancelled_parent_never_delegates_or_dispatches(tmp_path):
    r,seen,native=call(tmp_path,allowed=lambda:False)
    assert r.status=='stopped' and seen==native==[] and r.native_actions==0


def test_native_timeout_keeps_uncertainty_and_never_retries(tmp_path):
    r,seen,native=call(tmp_path,fail_native=True)
    assert r.status=='stopped' and r.ambiguous_dispatch and len(native)==1 and len(seen)==1
    assert r.native_actions==0


def test_cutoff_during_model_callback_blocks_next_native(tmp_path,monkeypatch):
    import aiqa.worker.mobile_agent_process as process
    clock=[0.0]
    monkeypatch.setattr(process,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    r,seen,native=call(tmp_path,timeout=20,model_after=lambda:clock.__setitem__(0,21.0))
    assert r.status=='stopped' and r.reason=='deadline' and native==[]
    assert len(seen)==1 and r.model_requests==1


def test_existing_output_is_never_overwritten(tmp_path):
    out=tmp_path/'process';out.mkdir();(out/'user-data').write_text('preserve')
    with pytest.raises(FileExistsError):call(tmp_path)
    assert (out/'user-data').read_text()=='preserve'


def test_sensitive_capture_is_not_written_or_sent_to_child_model(tmp_path):
    r,seen,native=call(tmp_path,secrets=('fixture-pixel-secret',))
    assert r.status=='stopped' and seen==native==[]
    assert not list((tmp_path/'process').rglob('*.png'))


def test_action_cap_stops_before_a_second_native_send(tmp_path):
    r,seen,native=call(tmp_path,repeat_click=True,max_actions=1)
    assert r.reason=='action_limit' and r.native_actions==1 and len(native)==1
    assert r.model_requests==2 and not r.ambiguous_dispatch


def test_original_step_limit_does_not_claim_success(tmp_path):
    r,seen,native=call(tmp_path,repeat_click=True,max_steps=1)
    assert r.reason=='step_limit' and r.model_requests==1 and r.native_actions==1
    assert r.receipt['main_invocations']==1


@pytest.mark.parametrize('boundary',[0,2])
def test_missing_or_duplicate_model_boundary_stops_before_native(tmp_path,boundary):
    r,seen,native=call(tmp_path,model_boundary=boundary)
    assert r.status=='stopped' and native==[] and r.model_requests<=1


@pytest.mark.parametrize('boundary',[0,2])
def test_missing_or_duplicate_native_boundary_never_counts_ack(tmp_path,boundary):
    r,seen,native=call(tmp_path,native_boundary=boundary)
    assert r.status=='stopped' and r.native_actions==0 and len(seen)==1
    assert r.ambiguous_dispatch is (boundary==2)


def test_cancel_after_model_response_stops_before_native(tmp_path):
    active=[True]
    r,seen,native=call(tmp_path,allowed=lambda:active[0],model_after=lambda:active.__setitem__(0,False))
    assert r.reason=='cancelled' and len(seen)==1 and native==[]


def test_own_child_is_reaped_on_ambiguous_native_send(tmp_path,monkeypatch):
    import aiqa.worker.mobile_agent_process as process
    start=subprocess.Popen
    children=[]
    def track(*args,**kwargs):
        child=start(*args,**kwargs);children.append(child);return child
    monkeypatch.setattr(process.subprocess,'Popen',track)
    r,seen,native=call(tmp_path,fail_native=True)
    assert r.ambiguous_dispatch and len(children)==1 and children[0].poll() is not None
    assert all(stream.closed for stream in (children[0].stdin,children[0].stdout,children[0].stderr))


def test_model_frame_excludes_raw_capture_reasoning(tmp_path):
    from dataclasses import replace
    raw=replace(_observation(),reasoning='private-capture-reasoning-sentinel')
    r,seen,native=call(tmp_path,capture_override=lambda:raw)
    assert r.status=='claimed_success'
    for request in seen:
        for frame in [request['current'],*request['images'].values()]:
            assert not hasattr(frame,'reasoning')
            assert frame.png==raw.png and frame.geometry==raw.geometry


def test_diagnostic_disk_failure_preserves_ambiguous_result(tmp_path,monkeypatch):
    write=Path.write_bytes
    def fail_log(path,data):
        if path.name=='child-stderr.log':raise OSError('fixture full disk')
        return write(path,data)
    monkeypatch.setattr(Path,'write_bytes',fail_log)
    r,seen,native=call(tmp_path,fail_native=True)
    assert r.ambiguous_dispatch and len(native)==1 and r.native_actions==0


def _scripted_child(monkeypatch,body):
    import sys
    import aiqa.worker.mobile_agent_process as process
    start=subprocess.Popen;children=[]
    prelude="import sys,time,json\nfrom aiqa.worker.mobile_agent_ipc import read_packet,write_packet\nfrom aiqa.adapters.mobile_agent_upstream import load_protocol\nconfig=read_packet(sys.stdin.buffer)\nsequence=0\ntag='AIQA_'+'a'*32+'_'*43\npath=tag+'/screenshot_0.png'\ndef rpc(op,payload):\n    global sequence\n    sequence+=1\n    write_packet(sys.stdout.buffer,{'v':1,'id':sequence,'op':op,'payload':payload})\n    return read_packet(sys.stdin.buffer)['result']\n"
    def track(*args,**kwargs):
        child=start([sys.executable,'-B','-c',prelude+body],**kwargs)
        children.append(child);return child
    monkeypatch.setattr(process.subprocess,'Popen',track)
    return children


def test_child_that_stops_reading_cannot_block_parent_cutoff(tmp_path,monkeypatch):
    import io,random,time
    from PIL import Image
    from dataclasses import replace
    from aiqa.contracts.actions import CaptureGeometry
    buffer=io.BytesIO();Image.frombytes('RGB',(500,500),random.Random(0).randbytes(750000)).save(buffer,format='PNG')
    frame=replace(_observation(),png=buffer.getvalue(),geometry=CaptureGeometry(500,500,500,500,'identity',0,(0,0,500,500)))
    children=_scripted_child(monkeypatch,"write_packet(sys.stdout.buffer,{'v':1,'id':1,'op':'capture','payload':{'path':path}})\ntime.sleep(3)\n")
    started=time.monotonic()
    r,seen,native=call(tmp_path,timeout=.7,capture_override=lambda:frame)
    assert r.reason=='deadline' and time.monotonic()-started<2
    assert children[0].poll() is not None and seen==native==[]


@pytest.mark.parametrize('violation',['double_capture','reuse_frame','skip_index','change_tag'])
def test_malformed_child_sequence_stops_before_extra_callbacks(tmp_path,monkeypatch,violation):
    from aiqa.worker.mobile_agent_process import run_mobile_agent_process
    body="rpc('capture',{'path':path})\n"
    if violation=='double_capture':body+="rpc('capture',{'path':tag+'/screenshot_1.png'})\n"
    else:
        body+="p=load_protocol()\nmessages=p.build_messages(path,tag+' ('+config['instruction']+')',[],'gpt-6-luna')\ncontent=rpc('model',{'messages':messages})['content']\n"
        if violation=='reuse_frame':body+="messages=p.build_messages(path,tag+' ('+config['instruction']+')',[{'output':content,'image':path}],'gpt-6-luna')\nrpc('model',{'messages':messages})\n"
        elif violation=='skip_index':body+="rpc('capture',{'path':tag+'/screenshot_2.png'})\n"
        else:body+="rpc('capture',{'path':tag.replace('a','b')+'/screenshot_1.png'})\n"
    _scripted_child(monkeypatch,body)
    captures=[];models=[]
    def capture():captures.append(1);return _observation()
    def model(request,*,before_send):
        before_send();models.append(1)
        return json.dumps({'summary':'wait','name':'mobile_use','arguments':{'action':'wait','time':0}})
    def dispatch(*args,**kwargs):raise AssertionError('malformed child must never dispatch')
    r=run_mobile_agent_process(output=tmp_path/'process',instruction='Wait',capture=capture,model=model,dispatch=dispatch,secrets=(),max_steps=3)
    assert len(captures)==1 and len(models)==(0 if violation=='double_capture' else 1)
    assert r.reason in {'capture_order','model_order'} and not r.ambiguous_dispatch


def test_child_crash_after_model_never_dispatches(tmp_path,monkeypatch):
    children=_scripted_child(monkeypatch,"rpc('capture',{'path':path})\np=load_protocol()\nmessages=p.build_messages(path,tag+' ('+config['instruction']+')',[],'gpt-6-luna')\nrpc('model',{'messages':messages})\nimport os\nos._exit(1)\n")
    r,seen,native=call(tmp_path)
    assert r.status=='stopped' and r.reason=='child_closed'
    assert native==[] and len(seen)==1 and r.native_actions==0 and not r.ambiguous_dispatch
    assert children[0].poll() not in (None,0)
