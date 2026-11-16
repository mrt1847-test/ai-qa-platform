"""Failed original REC finishes save ACK facts without promoting a replay source."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import asyncio, sqlite3, subprocess
import httpx, pytest
from test_ma04_engine_authority import platform, ux_app, worker, choose
from test_rx97_recording_pin import request as start
from test_rx_65 import _observation
from ux_support import session
from aiqa.worker.android_jobs import build_operational_android_recording_handler
from aiqa.worker.runtime import WorkerRuntime, WorkerRuntimeConfig
from aiqa.environments.android_app_launch import AppLaunchReceipt


def handler_for(f, w, tmp_path, monkeypatch):
    def launch(package, *, before_native_send):
        before_native_send()
        return AppLaunchReceipt(package, package+'/.Main')
    monkeypatch.setattr('aiqa.worker.android_jobs._live_android_capture_pair',lambda **kwargs:(_observation,launch))
    handler=build_operational_android_recording_handler(adb_path=Path('adb.exe'),serial=w.serial,expected_avd=None,runtime_root=tmp_path,client=w.client)
    sent=[]
    def unknown(argv,timeout):
        sent.append(tuple(argv))
        raise subprocess.TimeoutExpired(argv,timeout)
    handler.driver._runner=unknown
    return handler,sent


def recording_state(f, recording):
    with sqlite3.connect(f['database']) as db:
        return db.execute('SELECT completion_status,stop_status,storage_status,evidence_status FROM recordings WHERE recording_id=?',(recording,)).fetchone()


@pytest.mark.parametrize('outcome,expected',[('error','error'),('crash','error'),('lost','interrupted'),('interrupted','interrupted'),('cancelled','interrupted')])
def test_failed_worker_finish_stops_and_saves_only_incomplete_recording(platform,tmp_path,monkeypatch,outcome,expected):
    f=platform;w=worker(f);choose(f,w)
    handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    # The original timeout supplies real ACK cursor/evidence; vary the supported finish reason.
    original_handle=handler.handle
    monkeypatch.setattr(handler,'handle',lambda job:replace(original_handle(job),outcome=outcome))
    started=start(f);assert started.status_code==201,started.text
    recording=started.json()['recording_id']
    with sqlite3.connect(f['database']) as db:
        pointers=db.execute('SELECT current_approval_id,latest_draft_version_id FROM automation_cases WHERE case_id=?',(f['body']['case_id'],)).fetchone()
        versions=db.execute('SELECT COUNT(*) FROM case_versions').fetchone()[0]
    runtime=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload)
    report=runtime.run_once()
    assert report.finished and report.actions==1,report
    assert len(sent)==1 and len(f['model_sent'])==1
    assert recording_state(f,recording)==(expected,'stopped','stored','incomplete')
    with sqlite3.connect(f['database']) as db:
        for table in ('recording_manifests','replay_packages','approval_events'):
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM case_versions').fetchone()[0]==versions
        assert db.execute('SELECT current_approval_id,latest_draft_version_id FROM automation_cases WHERE case_id=?',(f['body']['case_id'],)).fetchone()==pointers


def test_failed_recording_and_acked_screenshot_remain_readable_pc_offline(platform,tmp_path,monkeypatch):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    started=start(f);assert started.status_code==201
    recording=started.json()['recording_id']
    report=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload).run_once()
    assert report.finished
    with sqlite3.connect(f['database']) as db:
        artifact=db.execute("SELECT artifact_id FROM artifact_objects WHERE action_id LIKE 'ma-%' AND role='before'").fetchone()[0]
        db.execute('UPDATE worker_presence SET last_seen=? WHERE project_id=? AND worker_id=?',((datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat(),f['project'],w.worker_id))
    async def read():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            page=await c.get(f"/ui/projects/{f['project']}/recordings/{recording}",headers=headers)
            timeline=await c.get(f"/api/v1/projects/{f['project']}/recordings/{recording}/timeline",headers=headers)
            png=await c.get(f'/api/v1/artifacts/{artifact}',headers=headers)
            return page,timeline,png
    page,timeline,png=asyncio.run(read())
    assert page.status_code==200 and timeline.status_code==200 and png.status_code==200
    assert png.content.startswith(b'\x89PNG')
    actions=timeline.json()['actions']
    assert any(item['action_id'].startswith('ma-') and item['before']=='stored' for item in actions),actions
    assert timeline.json()['completion_status']=='error'
    assert recording_state(f,recording)==('error','stopped','stored','incomplete')
    assert len(sent)==1 and len(f['model_sent'])==1


def test_failure_finish_receipt_replay_is_immutable_and_new_key_cannot_promote(platform,tmp_path,monkeypatch):
    from aiqa.worker.http_client import WorkerHttpError
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    started=start(f);assert started.status_code==201
    recorded=[];send=w.client.finish_attempt
    def save(*,payload,idempotency_key):
        recorded.append((dict(payload),idempotency_key))
        result=send(payload=payload,idempotency_key=idempotency_key)
        assert send(payload=payload,idempotency_key=idempotency_key)['replayed'] is True
        promoted={**payload,'outcome':'completed','evidence_complete':True,'ambiguous_dispatch':False,'cleanup_failed':False}
        # Check while the lease still exists, before runtime cleanup can mask the defect.
        with pytest.raises(WorkerHttpError):send(payload=promoted,idempotency_key=idempotency_key+'-promote')
        return result
    monkeypatch.setattr(w.client,'finish_attempt',save)
    report=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload).run_once()
    assert report.finished and len(recorded)==1
    payload,key=recorded[0]
    assert send(payload=payload,idempotency_key=key)['replayed'] is True
    # A new key must not invent a completed source after an authoritative failed finish.
    promoted={**payload,'outcome':'completed','evidence_complete':True,'ambiguous_dispatch':False,'cleanup_failed':False}
    with pytest.raises(WorkerHttpError):send(payload=promoted,idempotency_key=key+'-promote')
    with sqlite3.connect(f['database']) as db:
        assert db.execute('SELECT COUNT(*) FROM recording_manifests').fetchone()[0]==0
    assert recording_state(f,started.json()['recording_id'])==('error','stopped','stored','incomplete')
    assert len(sent)==1 and len(f['model_sent'])==1


def test_browser_cancel_preserves_incomplete_saved_recording_without_native_retry(platform,tmp_path,monkeypatch):
    f=platform;w=worker(f);choose(f,w);handler,sent=handler_for(f,w,tmp_path,monkeypatch)
    started=start(f);assert started.status_code==201
    cancellations=[]
    def cancel():
        with sqlite3.connect(f['database']) as db:
            current=db.execute('SELECT status FROM jobs WHERE job_id=?',(started.json()['job_id'],)).fetchone()[0]
        async def post():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
                headers=await session(c,f['project'])
                return await c.post(f"/api/v1/projects/{f['project']}/jobs/{started.json()['job_id']}/cancellations",json={'expected_state':current},headers={**headers,'Idempotency-Key':'cancel-original'})
        cancelled=asyncio.run(post());cancellations.append(cancelled);assert cancelled.status_code==202,cancelled.text
    publish=handler.context.target_preparer._publish
    def committed_then_cancel():
        result=publish();cancel();return result
    monkeypatch.setattr(handler.context.target_preparer,'_publish',committed_then_cancel)
    report=WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload).run_once()
    assert report.finished and report.actions==1,report
    assert len(cancellations)==1 and cancellations[0].status_code==202
    assert sent==[] and f['model_sent']==[]
    assert recording_state(f,started.json()['recording_id'])==('interrupted','stopped','stored','incomplete')


@pytest.mark.parametrize('operation',['stop','finish'])
def test_browser_cannot_reseal_failed_worker_recording(platform,tmp_path,monkeypatch,operation):
    f=platform;w=worker(f);choose(f,w);handler,_=handler_for(f,w,tmp_path,monkeypatch)
    started=start(f);assert started.status_code==201
    recording=started.json()['recording_id']
    assert WorkerRuntime(w.client,WorkerRuntimeConfig(w.boot,frozenset({'recording'})),handler,inventory_provider=lambda:w.payload).run_once().finished
    with sqlite3.connect(f['database']) as db:
        ids=[row[0] for row in db.execute('SELECT artifact_id FROM artifact_objects')]
    async def reseal():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f['app']),base_url='http://127.0.0.1') as c:
            headers=await session(c,f['project'])
            return await c.post(f'/api/v1/recordings/{recording}/{operation}',json={'project_id':f['project'],'outcome':'completed','final_seq':0,'artifact_ids':ids},headers={**headers,'Idempotency-Key':'late-browser-'+operation})
    response=asyncio.run(reseal())
    assert response.status_code==409,response.text
    with sqlite3.connect(f['database']) as db:assert db.execute('SELECT COUNT(*) FROM recording_manifests').fetchone()[0]==0
    assert recording_state(f,recording)==('error','stopped','stored','incomplete')
