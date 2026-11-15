"""Native actions survive recording and replay without a model or a second rescale."""
import copy,json,hashlib
from dataclasses import asdict
from uuid import uuid4
import pytest
from ux_support import ux_app
from aiqa.replay.android_plan import TypedAndroidAction,PlanRejected
from test_rx_34 import _observation,_geometry

ACTIONS=(TypedAndroidAction('tap',x=200,y=400),TypedAndroidAction('text',text='iphone'),
    TypedAndroidAction('swipe',x=200,y=1600,x2=800,y2=400,duration_ms=875),TypedAndroidAction('key',keycode=66),TypedAndroidAction('key',keycode=4))


def mapping():
    from aiqa.replay.android_native_trace import native_event
    observation=_observation(geometry=_geometry(physical=(1000,2000),model=(500,1000)))
    events=[native_event(action,observation,action_id='a'+str(i),line=i) for i,action in enumerate(ACTIONS,1)]
    return json.dumps({'schema':'android-native-trace-v2','native_action_count':len(events),'events':events},sort_keys=True,separators=(',',':'))


def test_native_trace_roundtrips_all_parameters_in_physical_space():
    from aiqa.replay.android_native_trace import parse_native_trace,physical_plan
    steps=parse_native_trace(mapping())
    assert tuple(step.action for step in steps)==ACTIONS
    assert all(step.width==1000 and step.height==2000 and step.rotation==0 for step in steps)
    plan=physical_plan(steps)
    assert plan.splitlines()==['physical:click(200, 400)',"physical:type('iphone')",'physical:swipe(200, 1600, 800, 400, 875)','physical:key(66)','physical:key(4)']


@pytest.mark.parametrize('damage',['count','extra','bool','outside','duplicate','geometry','secret'])
def test_invalid_native_trace_is_rejected_instead_of_partially_replayed(damage):
    from aiqa.replay.android_native_trace import parse_native_trace
    raw=json.loads(mapping())
    if damage=='count':raw['native_action_count']+=1
    elif damage=='extra':raw['events'][0]['native']['shell']='reboot'
    elif damage=='bool':raw['events'][0]['native']['x']=True
    elif damage=='outside':raw['events'][0]['native']['x']=1000
    elif damage=='duplicate':raw['events'][1]['action_id']=raw['events'][0]['action_id']
    elif damage=='geometry':raw['events'][0]['geometry']['physical_width']=True
    else:raw['events'][1]['secret_literal']='private'
    with pytest.raises(PlanRejected):parse_native_trace(json.dumps(raw))


def native_manifest():
    from test_rx_50 import _manifest_model,_supported_events
    from dataclasses import replace
    source,_=_manifest_model(_supported_events(),artifact_id=str(uuid4()))
    raw=mapping();digest=hashlib.sha256(raw.encode()).hexdigest()
    return replace(source,action_mapping=raw,source_artifact_hashes=json.dumps([digest]))


def test_v2_compiler_hashes_exact_physical_plan_and_preserves_every_action():
    from aiqa.replay.android_plan import compile_android_plan,android_trace_ready
    from aiqa.replay.android_native_trace import physical_plan,parse_native_trace
    source=native_manifest();compiled=compile_android_plan(source)
    plan=physical_plan(parse_native_trace(source.action_mapping))
    assert android_trace_ready(source.action_mapping)
    assert compiled.body.compiler_ref=='android-native-plan-v2'
    assert compiled.body.approved_code_or_plan_hash==hashlib.sha256(plan.encode()).hexdigest()
    assert [s.call for s in compiled.steps]==plan.splitlines()
    assert len(compiled.steps)==len(ACTIONS)


def test_new_recording_seal_preserves_literal_key_and_swipe_duration():
    from aiqa.worker.android_jobs import _seal_event_for_action
    obs=_observation(geometry=_geometry(physical=(1000,2000),model=(500,1000)))
    events=[_seal_event_for_action(action,obs,action_id='a'+str(i),line=i) for i,action in enumerate(ACTIONS,1)]
    assert all(event is not None for event in events)
    assert [event['native'] for event in events]==[asdict(action) for action in ACTIONS]


def test_native_marker_does_not_fall_back_to_legacy_plan_if_source_is_missing():
    from aiqa.worker.native_source import resolve_claim_native_source
    job={'project_id':str(uuid4()),'snapshot':{'purpose':'trial','approved_plan':'physical:click(200, 400)'}}
    with pytest.raises(ValueError):resolve_claim_native_source(job)


def native_claim():
    from aiqa.replay.android_native_trace import native_source_document,compile_native_source,physical_plan,parse_native_trace
    source=native_manifest();package=str(uuid4());digest=compile_native_source(source).body_hash
    witness=native_source_document(source.project_id,package,digest,source)
    return {'project_id':str(source.project_id),'job_id':str(uuid4()),'attempt_id':str(uuid4()),'generation':1,
        'snapshot':{'purpose':'trial','replay_package_id':package,'replay_package_hash':digest,
        'approved_digest':digest,'approved_plan':physical_plan(parse_native_trace(source.action_mapping)),'native_source':witness}}


def test_native_claim_recompiles_witness_and_detaches_from_reply_mutation():
    from aiqa.worker.native_source import resolve_claim_native_source
    job=native_claim();pin=resolve_claim_native_source(job)
    assert tuple(s.action for s in pin.steps)==ACTIONS
    job['snapshot']['native_source']['mapping']='{}'
    assert tuple(s.action for s in pin.steps)==ACTIONS


@pytest.mark.parametrize('damage',['project','package','digest','source_hash','mapping','plan','null'])
def test_native_claim_rejects_mismatched_frozen_witness(damage):
    from aiqa.worker.native_source import resolve_claim_native_source
    job=native_claim();raw=job['snapshot']['native_source']
    if damage=='project':raw['project_id']=str(uuid4())
    elif damage=='package':raw['package_id']=str(uuid4())
    elif damage=='digest':raw['package_hash']='sha256:'+'0'*64
    elif damage=='source_hash':raw['source_manifest_hash']='different'
    elif damage=='mapping':raw['mapping']=raw['mapping'].replace('iphone','changed')
    elif damage=='plan':job['snapshot']['approved_plan']='click(200,400)'
    else:job['snapshot']['native_source']=None
    with pytest.raises(ValueError):resolve_claim_native_source(job)


def test_server_package_pin_supplies_native_source_and_physical_plan(ux_app):
    from uuid import UUID
    from test_rx_50 import _seed_case,_seed_artifact
    from aiqa.store.models import Actor
    from aiqa.recording.service import finish_recording
    from aiqa.recording.manifests import RecordingFinishInput
    from aiqa.replay.packages import resolve_claim_package_pin
    app,project,_=ux_app;store=app.state.open_store();actor=Actor(uuid4(),UUID(project),True)
    try:
        case,version,recording,artifact=_seed_case(app,store,UUID(project),actor)
        with store.transaction() as c:
            _seed_artifact(c,UUID(project),recording,artifact,source_mapping=mapping())
            receipt=finish_recording(c,actor,UUID(project),RecordingFinishInput(recording,'completed',10,(str(artifact),),'native-finish',mapping()))
            package,digest=c.execute('SELECT package_id,body_hash FROM replay_packages WHERE source_manifest_id=?',(str(receipt.manifest_id),)).fetchone()
            pin=resolve_claim_package_pin(c,project,package_id=package,package_hash=digest,purpose='trial')
            assert pin.native_source['mapping']==mapping() and pin.approved_plan.startswith('physical:')
    finally:store.close()


def test_native_replay_uses_exact_recorded_argv_without_double_rescale(tmp_path):
    from test_rx_34 import _replay
    from aiqa.worker.native_source import resolve_claim_native_source
    job=native_claim();handler,calls=_replay(tmp_path,digest=job['snapshot']['replay_package_hash'])
    job['snapshot']['serial']=handler.context.expected_serial
    obs=_observation(geometry=_geometry(physical=(1000,2000),model=(500,1000)))
    handler.context.step_observations=tuple((obs,obs) for _ in ACTIONS)
    result=handler.handle(job)
    assert result.outcome=='completed' and result.actions==len(ACTIONS)
    assert calls==[handler.driver.build_argv(action) for action in ACTIONS]
    assert handler.authoring_calls_seen==handler.broker.authoring_calls==handler.verifier_calls==handler.healer_calls==0


@pytest.mark.parametrize('geometry',[_geometry(physical=(100,200),model=(1000,2000)),_geometry(physical=(1000,2000),model=(500,1000),rotation=90)])
def test_native_source_geometry_change_does_not_send_a_recorded_gesture(tmp_path,geometry):
    from test_rx_34 import _replay
    job=native_claim();handler,calls=_replay(tmp_path,digest=job['snapshot']['replay_package_hash'])
    job['snapshot']['serial']=handler.context.expected_serial
    obs=_observation(geometry=geometry);handler.context.step_observations=((obs,obs),)*len(ACTIONS)
    result=handler.handle(job)
    assert result.actions==0 and result.outcome=='error' and calls==[]
    assert result.ambiguous_dispatch is False
    assert handler.original_failure=='native source geometry changed'


def test_scripted_recording_saved_trace_replays_same_text_swipe_and_key_argv(tmp_path):
    from test_rx_48 import _handler,_claim
    from test_rx_34 import _replay
    from dataclasses import replace
    from uuid import UUID
    from aiqa.replay.android_native_trace import compile_native_source,native_source_document,physical_plan,parse_native_trace
    original=[];record=_handler(tmp_path/'record',original,responses=("type('iphone')",'swipe(100,1600,800,400,875)','key(66)','finish()'),steps=4)
    recording=_claim();saved=record.handle(recording)
    assert saved.outcome=='completed' and saved.actions==3
    raw=saved.action_mapping
    source=replace(native_manifest(),project_id=UUID(recording['project_id']),action_mapping=raw,source_artifact_hashes=json.dumps([hashlib.sha256(raw.encode()).hexdigest()]))
    compiled=compile_native_source(source);package=str(uuid4());witness=native_source_document(source.project_id,package,compiled.body_hash,source)
    replay,calls=_replay(tmp_path/'replay',digest=compiled.body_hash)
    replay.context.step_observations=record.context.step_observations[:3]
    job={'project_id':recording['project_id'],'job_id':str(uuid4()),'attempt_id':str(uuid4()),'generation':1,
        'snapshot':{'purpose':'trial','serial':replay.context.expected_serial,'replay_package_id':package,'replay_package_hash':compiled.body_hash,
        'approved_plan':physical_plan(parse_native_trace(raw)),'native_source':witness}}
    result=replay.handle(job)
    assert result.outcome=='completed' and result.actions==3
    assert calls==original and replay.broker.authoring_calls==0


@pytest.mark.parametrize('damage',['duplicate_key','boolean_bounds'])
def test_native_trace_rejects_ambiguous_json_and_geometry_types(damage):
    from aiqa.replay.android_native_trace import parse_native_trace
    raw=mapping()
    if damage=='duplicate_key':
        raw=raw.replace('"native_action_count": 5','"native_action_count": 0,"native_action_count": 5') if '"native_action_count": 5' in raw else raw.replace('"native_action_count":5','"native_action_count":0,"native_action_count":5')
    else:
        obj=json.loads(raw)
        obj['events'][1]['geometry']['content_bounds']=[False,False,True,True]
        raw=json.dumps(obj)
    with pytest.raises(PlanRejected):parse_native_trace(raw)


def test_native_source_count_must_match_durable_gesture_prefix():
    from aiqa.recording.service import _android_seal_payload
    from aiqa.recording.manifests import RecordingFinishInput
    # A complete-looking five-action mapping cannot seal a one-action prefix.
    spec=RecordingFinishInput(uuid4(),'completed',2,(),'count-mismatch',mapping())
    assert _android_seal_payload(spec,'completed')[2] is False


@pytest.mark.parametrize('remaining',['count','physical_geometry'])
def test_damaged_v2_markers_never_downgrade_to_legacy(remaining):
    from dataclasses import replace
    from aiqa.replay.android_plan import android_trace_ready,compile_android_plan
    from aiqa.replay.packages import mobile_agent_plan_from_android_mapping
    raw=json.loads(mapping());raw.pop('schema');raw['events']=raw['events'][:1]
    for event in raw['events']:event.pop('native')
    if remaining=='physical_geometry':raw.pop('native_action_count')
    text=json.dumps(raw)
    assert android_trace_ready(text) is False
    assert mobile_agent_plan_from_android_mapping(text)==''
    with pytest.raises(PlanRejected):compile_android_plan(replace(native_manifest(),action_mapping=text))


@pytest.mark.parametrize('plan',['click(1,2)',''])
def test_native_compiler_pin_requires_witness_even_when_display_plan_is_legacy(plan):
    from types import SimpleNamespace
    from aiqa.worker.native_source import resolve_claim_native_source
    job=native_claim();job['snapshot'].pop('native_source');job['snapshot']['approved_plan']=plan
    with pytest.raises(ValueError):resolve_claim_native_source(job,case_context=SimpleNamespace(replay_compiler_ref='android-native-plan-v2'))


def test_native_uuid_type_failure_is_a_structured_rejection():
    from aiqa.worker.native_source import resolve_claim_native_source
    job=native_claim();job['snapshot']['native_source']['source_manifest_id']=5
    with pytest.raises(ValueError):resolve_claim_native_source(job)


def test_native_physical_normalization_cannot_hide_invalid_original_frame(tmp_path):
    from dataclasses import replace
    from test_rx_34 import _replay
    job=native_claim();handler,calls=_replay(tmp_path,digest=job['snapshot']['replay_package_hash'])
    job['snapshot']['serial']=handler.context.expected_serial
    geo=replace(_geometry(physical=(1000,2000),model=(500,1000)),model_width=0)
    obs=_observation(geometry=geo);handler.context.step_observations=tuple((obs,obs) for _ in ACTIONS)
    result=handler.handle(job)
    assert result.actions==0 and calls==[]


def test_v2_seal_requires_the_exact_acknowledged_owned_source(ux_app):
    from uuid import UUID
    from test_rx_50 import _seed_case,_seed_artifact
    from aiqa.store.models import Actor
    from aiqa.recording.service import finish_recording,PreflightRejected
    from aiqa.recording.manifests import RecordingFinishInput
    app,project,_=ux_app;store=app.state.open_store();actor=Actor(uuid4(),UUID(project),True)
    try:
        case,version,recording,artifact=_seed_case(app,store,UUID(project),actor)
        with store.transaction() as c:
            _seed_artifact(c,UUID(project),recording,artifact)
            with pytest.raises(PreflightRejected):finish_recording(c,actor,UUID(project),RecordingFinishInput(recording,'completed',10,(str(artifact),),'bad-native-source',mapping()))
    finally:store.close()
