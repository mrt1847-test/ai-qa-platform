from types import SimpleNamespace
import json
from aiqa.contracts.cases import CheckSpec
from aiqa.worker.case_context import WorkerCaseContext,CaseStep,CaseTarget
from aiqa.worker.check_binding_pin import WorkerCheckBindingPin
from aiqa.environments.android_hierarchy import AndroidHierarchy,AndroidHierarchyTarget


def source(method='deterministic'):
    return WorkerCaseContext('version','source','goal',CaseTarget('android','com.example.app'),
        (CaseStep('s1','open',(CheckSpec('step','text','Done'),)),),
        (CheckSpec('final','state','enabled=true'),),'context',
        json.dumps({'verification':[{'method':method,'binding_id':'verification' if method!='deterministic' else '',
            'allow_unknown_supplement':False}]}))


def evaluate(pin=None,binding=None,**kwargs):
    from aiqa.worker.bound_check_evaluation import evaluate_bound_checks
    return evaluate_bound_checks(pin or source(),binding,
        SimpleNamespace(steps=(SimpleNamespace(action_id='a1'),SimpleNamespace(action_id='a2'))),
        action_index=kwargs.pop('action_index',2),total_actions=2,
        observed_at='2026-11-19T00:00:00+09:00',checkpoint=lambda:True,timeout=1,**kwargs)


def test_screen_meaning_without_visual_policy_stays_unknown():
    pin=WorkerCaseContext('version','source','goal',CaseTarget('android','com.example.app'),(),
        (CheckSpec('final','visual','상품 이미지와 가격이 표시된다'),),'context',
        json.dumps({'verification':[{'method':'deterministic','binding_id':'','allow_unknown_supplement':False}]}))
    called=[]
    rows=evaluate(pin=pin,visual=lambda *args:called.append(args) or {'status':'satisfied'})
    assert called==[] and rows[0].result.status=='unknown' and rows[0].result.reason=='visual_policy_missing'


def test_screen_meaning_with_visual_policy_uses_the_verifier_once():
    pin=WorkerCaseContext('version','source','goal',CaseTarget('android','com.example.app'),(),
        (CheckSpec('final','visual','상품 이미지와 가격이 표시된다'),),'context',
        json.dumps({'verification':[{'method':'ai_visual','binding_id':'verification','allow_unknown_supplement':False}]}))
    called=[]
    def visual(check,phase,step):
        called.append((check.id,phase,step))
        return {'status':'satisfied','reason':'screen_match','observed_at':'2026-11-19T00:00:02+09:00'}
    rows=evaluate(pin=pin,visual=visual)
    assert called==[('final','final',None)] and rows[0].result.status=='satisfied' and rows[0].result.reason=='screen_match'


def test_checks_run_at_explicit_boundary_and_read_selected_resources_once():
    calls=[]
    binding=WorkerCheckBindingPin('manifest','hash',(('s1','a2'),),
        (('step','com.example.app:id/title'),('final','com.example.app:id/button')))
    def read(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(snapshot=AndroidHierarchy(0,(
            AndroidHierarchyTarget('com.example.app:id/title','available','Done'),
            AndroidHierarchyTarget('com.example.app:id/button','available',enabled=True))),
            captured_at='2026-11-19T00:00:01+09:00')
    assert evaluate(binding=binding,action_index=1,hierarchy_observer=read)==()
    rows=evaluate(binding=binding,hierarchy_observer=read)
    assert [r.result.status for r in rows]==['satisfied','satisfied']
    assert [r.result.reason for r in rows]==['exact_text_match','state_match']
    assert len(calls)==1 and calls[0]['package']=='com.example.app'
    assert set(calls[0]['resource_ids'])=={'com.example.app:id/title','com.example.app:id/button'}
    assert all(r.case_version_id=='version' and r.source_hash=='source' for r in rows)


def test_missing_mapping_and_ambiguous_target_never_pass():
    binding=WorkerCheckBindingPin('m','h',(),(('final','com.example.app:id/button'),))
    rows=evaluate(binding=binding,hierarchy_observer=lambda **kw:SimpleNamespace(
        snapshot=AndroidHierarchy(0,(AndroidHierarchyTarget('com.example.app:id/button','ambiguous'),)),
        captured_at='2026-11-19T00:00:00+09:00'))
    assert [r.result.status for r in rows]==['unknown','unknown']
    assert [r.result.reason for r in rows]==['logical_step_mapping_missing','target_ambiguous']


def test_real_mismatch_is_violated_and_does_not_call_visual_supplement():
    binding=WorkerCheckBindingPin('m','h',(('s1','a1'),),(('step','com.example.app:id/title'),))
    calls=[]
    rows=evaluate(pin=source('deterministic_then_ai_unknown'),binding=binding,action_index=1,
        hierarchy_observer=lambda **kw:SimpleNamespace(snapshot=AndroidHierarchy(0,(
            AndroidHierarchyTarget('com.example.app:id/title','available','Wrong'),)),captured_at='2026-11-19T00:00:00+09:00'),
        visual=lambda *args:calls.append(args))
    assert rows[0].result.status=='violated' and rows[0].result.reason=='text_mismatch'
    assert calls==[]


def test_visual_only_at_due_assertion_and_keeps_source_expected():
    calls=[]
    def visual(check,phase,step):
        calls.append(check.id)
        return {'status':'satisfied','reason':'visible','observed_at':'2026-11-19T00:00:00+09:00'}
    rows=evaluate(pin=source('ai_visual'),binding=None,visual=visual)
    assert calls==['final']
    assert [r.result.status for r in rows]==['unknown','satisfied']
    assert rows[-1].result.expected_snapshot=='enabled=true'


def test_unapproved_policy_does_not_read_a_mapped_target():
    calls=[]
    base=source()
    pin=WorkerCaseContext(base.case_version_id,base.content_hash,base.objective,base.target,base.steps,
        base.final_expected,base.context_hash,json.dumps({'verification':[]}))
    binding=WorkerCheckBindingPin('m','h',(('s1','a2'),),(('step','com.example.app:id/title'),('final','com.example.app:id/button')))
    rows=evaluate(pin=pin,binding=binding,hierarchy_observer=lambda **kw:calls.append(kw))
    assert calls==[] and [r.result.status for r in rows]==['unknown','unknown']
    assert {r.result.reason for r in rows}=={'verifier_policy_missing'}


def test_shared_boundary_reads_every_due_resource_once_and_ignores_ordinal():
    calls=[]
    pin=WorkerCaseContext('version','source','goal',CaseTarget('android','com.example.app'),
        (CaseStep('s1','open',(CheckSpec('one','text','Done'),)),CaseStep('s2','next',(CheckSpec('two','state','visible=true'),))),
        (),'context',source()._serialized)
    binding=WorkerCheckBindingPin('m','h',(('s1','a2'),('s2','a2')),
        (('one','com.example.app:id/title'),('two','com.example.app:id/button')))
    def read(**kwargs):
        calls.append(kwargs['resource_ids'])
        return SimpleNamespace(snapshot=AndroidHierarchy(0,(
            AndroidHierarchyTarget('com.example.app:id/title','available','Done'),
            AndroidHierarchyTarget('com.example.app:id/button','available',text='present'))),
            captured_at='2026-11-19T00:00:00+09:00')
    assert evaluate(pin=pin,binding=binding,action_index=1,hierarchy_observer=read)==()
    rows=evaluate(pin=pin,binding=binding,hierarchy_observer=read)
    assert calls==[('com.example.app:id/button','com.example.app:id/title')]
    assert [(r.result.check_id,r.result.status,r.result.reason) for r in rows]==[
        ('one','satisfied','exact_text_match'),('two','unknown','state_field_unavailable')]
    assert 'present' not in rows[1].result.reason and rows[1].result.sanitized_observed==''


def test_redacted_unavailable_and_unsupported_kind_stay_unknown():
    binding=WorkerCheckBindingPin('m','h',(('s1','a2'),),(('step','com.example.app:id/title'),))
    redacted=evaluate(binding=binding,hierarchy_observer=lambda **kw:SimpleNamespace(
        snapshot=AndroidHierarchy(0,(AndroidHierarchyTarget('com.example.app:id/title','redacted',text='secret'),)),
        captured_at='2026-11-19T00:00:00+09:00'))
    assert redacted[0].result.status=='unknown' and redacted[0].result.reason=='target_redacted'
    assert 'secret' not in redacted[0].result.reason
    pin=source()
    pin=WorkerCaseContext(pin.case_version_id,pin.content_hash,pin.objective,pin.target,
        (CaseStep('s1','open',(CheckSpec('step','value','Done'),)),),pin.final_expected,pin.context_hash,pin._serialized)
    unsupported=evaluate(pin=pin,binding=binding,hierarchy_observer=lambda **kw:SimpleNamespace(
        snapshot=AndroidHierarchy(0,(AndroidHierarchyTarget('com.example.app:id/title','available','Done',visible=True),)),
        captured_at='2026-11-19T00:00:00+09:00'))
    assert unsupported[0].result.status=='unknown' and unsupported[0].result.reason=='unsupported_check_kind'


def test_unavailable_target_can_load_without_repeating_an_input():
    ticks=[0.0];calls=[]
    binding=WorkerCheckBindingPin('m','h',(('s1','a1'),),(('step','com.example.app:id/title'),))
    def read(**kw):
        calls.append(kw)
        target=AndroidHierarchyTarget('com.example.app:id/title','missing') if len(calls)==1 else AndroidHierarchyTarget('com.example.app:id/title','available','Done')
        return SimpleNamespace(snapshot=AndroidHierarchy(0,(target,)),captured_at='2026-11-19T00:00:00+09:00')
    rows=evaluate(binding=binding,action_index=1,hierarchy_observer=read,clock=lambda:ticks[0],pause=lambda n:ticks.__setitem__(0,ticks[0]+n))
    assert rows[0].result.status=='satisfied' and len(calls)==2
