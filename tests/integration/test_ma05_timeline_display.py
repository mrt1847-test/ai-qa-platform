"""Saved original actions have useful labels without changing execution facts."""
import json,sqlite3,subprocess
import pytest
from test_ma04_engine_authority import platform,ux_app,worker,choose
from test_ma05_failure_state import handler_for
from test_ma05_failure_evidence import run
from test_ma05_recording_review_ui import page,export
from test_ma05_authoring_failure import fail_authoring
from test_rx_65 import _observation


@pytest.mark.parametrize('mode,label,state',[('unknown','탭 요청','전달 결과 확인 불가'),('known','탭 전달','기기 전달 확인'),
    ('not_sent','탭 준비','전달 전 중단'),('model','AI 동작 준비','동작 생성 중단'),('normal','탭 기록','화면·로그 수신')])
def test_original_timeline_uses_saved_action_and_delivery_labels(platform,tmp_path,monkeypatch,mode,label,state):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    if mode=='model':fail_authoring(f,w,handler,monkeypatch,'fence')
    elif mode in {'known','normal'}:
        def ack(argv,timeout):sent.append(tuple(argv));return subprocess.CompletedProcess(argv,0,'','')
        handler.driver._runner=ack
    if mode in {'known','not_sent'}:
        captures=[]
        def capture():
            captures.append(1)
            if mode=='known' and len(captures)==3:raise OSError('synthetic after capture failure')
            return _observation(fill=b'\x00\xff\x00' if mode=='not_sent' and len(captures)>1 else b'\xff\x00\x00')
        handler.context.live_capture=capture
    started,_=run(f,w,handler)
    html,body=page(f,started['recording_id'])
    action=next(a for a in body['actions'] if a['action_id'].startswith('ma-'))
    assert action['label']==label and action['state_label']==state
    assert action['before_label']=='저장됨'
    assert action['action_id'] not in action['label']
    assert body['actions'][0]['label']=='앱 준비'
    assert label in html and state in html
    assert '수신 기록 ' in html and '서버 ACK ' not in html
    assert action['dispatch_state']=={'unknown':'unknown','known':'acknowledged','not_sent':'lookup_failed','model':'planned','normal':'observed'}[mode]
    with sqlite3.connect(f['database']) as db:assert db.execute('SELECT COUNT(*) FROM approval_events').fetchone()[0]==0
    if mode=='model':assert sent==[] and f['model_sent']==[]
    if mode=='normal':assert body['actions'][-1]['label']=='제어 단계'
    export(f,'timeline-'+mode,html,body)


def test_legacy_query_link_roundtrips_and_stale_selection_uses_server_choice(platform):
    from datetime import datetime,timezone
    from uuid import uuid4
    from urllib.parse import urlsplit,parse_qs
    from html import unescape
    import base64,hashlib,re
    from test_ma04_engine_authority import claim
    from test_rx97_recording_pin import request as start
    f=platform;w=worker(f);choose(f,w);started=start(f);assert started.status_code==201
    job=claim(f,w);assert job is not None
    w.client.acknowledge(project_id=f['project'],job_id=job['job_id'],generation=job['generation'],runner_nonce=str(uuid4()),
        now=datetime.now(timezone.utc).isoformat(),idempotency_key='legacy-timeline-ack')
    action_id='legacy&part#+next';raw=_observation().png
    w.client.commit_evidence(sanitized=True,project_id=f['project'],job_id=job['job_id'],generation=job['generation'],
        now=datetime.now(timezone.utc).isoformat(),events=[],idempotency_key='legacy-before-only',artifacts=[{
            'filename':'legacy-before.png','media_type':'image/png','body_b64':base64.b64encode(raw).decode(),
            'declared_hash':'sha256:'+hashlib.sha256(raw).hexdigest(),'declared_length':len(raw),'owner_kind':'REC',
            'attempt_id':job['attempt_id'],'action_id':action_id,'role':'before'}])
    html,body=page(f,started.json()['recording_id'],'missing-selection');export(f,'timeline-legacy',html,body)
    assert body['selected_action_id']==action_id and body['actions'][0]['dispatch_state']=='observed'
    anchors=[{k:unescape(v) for k,v in re.findall(r'([\w-]+)="([^"]*)"',attrs)} for attrs in re.findall(r'<a\b([^>]*)>',html)]
    target=next(a for a in anchors if a.get('data-timeline-action')==action_id)
    assert parse_qs(urlsplit(target['href']).query)['action_id']==[action_id]
    assert body['actions'][0]['state_label']=='관찰 기록'
    assert f['model_sent']==[]
