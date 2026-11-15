import json,runpy,subprocess,sys
from types import SimpleNamespace
from pathlib import Path


def run_eval(tmp_path,monkeypatch,*,fail_after=False,expire_on=None):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    mod=runpy.run_path(str(Path('tools/android_luna_recording_eval.py')))
    g=mod['main'].__globals__
    from test_rx_34 import _observation
    obs=_observation();sent=[];clock=[0.0];focus_calls=[0]
    if expire_on:g['time']=SimpleNamespace(monotonic=lambda:clock[0])
    class Provider:
        def __init__(self,*args,**kwargs):self.n=0
        def observe(self):
            self.n+=1
            if expire_on=='capture' and self.n==2:clock[0]=241
            if fail_after and self.n==4:raise RuntimeError('after capture unavailable')
            return SimpleNamespace(state='ready',observation=obs)
    class Port:
        def __init__(self,**kwargs):self.call_count=0
        def complete(self,**kwargs):
            if kwargs.get('before_send'):kwargs['before_send']()
            self.call_count+=1
            actions=['click(100,200)',"type('mouse')",'finish()']
            d={'screen':'search','progress':'next','action':actions[self.call_count-1],
                'goal_status':'achieved' if self.call_count==3 else 'in_progress','evidence':'visible screen'}
            return SimpleNamespace(content=json.dumps(d),provider_request_id='r',actual_model='gpt-6-luna',
                input_tokens=10,output_tokens=5,reasoning_tokens=1,cached_input_tokens=0)
    class Launcher:
        def __init__(self,*a,**k):pass
        def launch(self,package,*,before_native_send):
            before_native_send();return SimpleNamespace(package=package,activity=package+'/.Main')
    def native(argv,**kw):
        if argv[-2:]==['dumpsys','window']:
            focus_calls[0]+=1
            if expire_on=='native_focus' and focus_calls[0]>=3:clock[0]=241
            return subprocess.CompletedProcess(argv,0,b'mCurrentFocus=Window{abc u0 com.ebay.kr.gmarket/.Main}',b'')
        sent.append(tuple(argv));return subprocess.CompletedProcess(argv,0,b'',b'')
    monkeypatch.setattr(subprocess,'run',native)
    g.update(AndroidObservationProvider=Provider,OpenAIProviderHttp=Port,AndroidAppLauncher=Launcher,load_local_api_key=lambda path:'private-test')
    out=tmp_path/'run'
    monkeypatch.setattr(sys,'argv',['eval','--adb','C:/platform-tools/adb.exe','--serial','emulator-5580','--avd','fixture',
        '--package','com.ebay.kr.gmarket','--key-file','unused.env','--output',str(out)])
    result=mod['main']()
    return json.loads((out/'report.json').read_text(encoding='utf-8')),sent,out,result


def test_eval_saves_dependent_actions_without_approving_model_claim(tmp_path,monkeypatch):
    report,sent,out,result=run_eval(tmp_path,monkeypatch)
    assert result==0 and report['recording_model_calls']==3 and len(sent)==2
    assert report['status']=='model_claimed_achieved' and report['human_review']=='pending' and not report['product_approval']
    assert report['replay_model_calls'] is None
    assert json.loads((out/'native-trace.json').read_text(encoding='utf-8'))['native_action_count']==2


def test_eval_preserves_sent_native_when_after_capture_fails(tmp_path,monkeypatch):
    report,sent,out,result=run_eval(tmp_path,monkeypatch,fail_after=True)
    assert result==1 and len(sent)==1 and report['recording_model_calls']==1
    assert report['acknowledged_native_actions']==1 and report['observed_native_actions']==0
    assert report['ambiguous_dispatch'] is True
    dispatch=json.loads((out/'step-001-dispatch.json').read_text(encoding='utf-8'))
    assert dispatch['state']=='dispatch_started' and dispatch['source_event']['action_id']=='step-001'


import pytest

@pytest.mark.parametrize('phase',['capture','native_focus'])
def test_eval_deadline_is_checked_after_blocking_frame_or_focus(tmp_path,monkeypatch,phase):
    report,sent,out,result=run_eval(tmp_path,monkeypatch,expire_on=phase)
    assert result==1 and sent==[]
    assert report['recording_model_calls']==(0 if phase=='capture' else 1)


@pytest.mark.parametrize('name',['different-avd','fixture'])
def test_cleanup_never_kills_a_replacement_named_avd(tmp_path,monkeypatch,name):
    monkeypatch.syspath_prepend(str(Path('tools').resolve()))
    mod=runpy.run_path(str(Path('tools/android_luna_recording_eval.py')))
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv,0,(name+'\nOK\n').encode(),b'')
    monkeypatch.setattr(subprocess,'run',run)
    closed=mod['close_selected_avd']('adb','emulator-5580','fixture')
    assert closed==(name=='fixture')
    assert len(calls)==(2 if name=='fixture' else 1)
