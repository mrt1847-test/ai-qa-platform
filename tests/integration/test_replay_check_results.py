"""Required replay checks survive worker finish and cannot be forged across pins."""
import copy
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from aiqa.contracts.worker_attempt import WorkerAttemptFinishInput
from aiqa.domain.hashing import canonical_hash
from test_rx87_check_bindings import recorded, save
from ux_support import ux_app

STAMP = '2026-11-19T00:00:00+00:00'


@pytest.fixture
def replay(recorded):
    r = recorded
    with r['store'].transaction() as c:
        saved = save(c, r)
        project = str(r['project'])
        execution, run, job, attempt = (str(uuid4()) for _ in range(4))
        package = c.execute('SELECT body_hash FROM replay_packages WHERE package_id=?', (saved['replay_package_id'],)).fetchone()[0]
        c.execute("INSERT INTO executions(project_id,execution_id,name,purpose,source,scope_requested_at) VALUES(?,?,'checks','trial','single',?)", (project, execution, STAMP))
        c.execute("INSERT INTO case_runs(project_id,execution_id,case_run_id,case_id,case_version_id,purpose,requested_at) VALUES(?,?,?,?,?,'trial',?)", (project, execution, run, r['case'], saved['case_version_id'], STAMP))
        limits = json.dumps(dict(replay_package_id=saved['replay_package_id'], replay_package_hash=package, self_healing_enabled=False))
        c.execute("INSERT INTO jobs(project_id,job_id,purpose,case_run_id,payload_hash,source_refs,limits,status) VALUES(?,?,'trial',?,'hash','[]',?,'running')", (project, job, run, limits))
        c.execute('INSERT INTO attempts(project_id,attempt_id,job_id,generation) VALUES(?,?,?,1)', (project, attempt, job))
        digest = canonical_hash(dict(job_id=job, attempt_id=attempt, purpose='trial', target_ref=None, revision_ref='case_run:'+run, policy_ref=None, replay_package_id=saved['replay_package_id'], replay_package_hash=package, self_healing_enabled=False), 'canon-json-v1')
        c.execute("INSERT INTO claim_receipts(project_id,worker_id,request_key,body_hash,job_id,attempt_id,generation,expires_at,purpose,revision_ref,digest,created_at) VALUES(?,'check-worker','claim','body',?,?,1,?,'trial',?,?,?)", (project, job, attempt, STAMP, 'case_run:'+run, digest, STAMP))
        finish = WorkerAttemptFinishInput(UUID(project), UUID(job), UUID(attempt), 1, 'completed', 10, 10, 'ack', digest, True, False)
        from aiqa.recording.case_context import load_case_context
        context = load_case_context(c, SimpleNamespace(project_id=project, job_id=job, attempt_id=attempt, generation=1, snapshot=SimpleNamespace(purpose='trial', replay_package_id=saved['replay_package_id'], replay_package_hash=package)))
        for line in (2, 5):
            action = 'runtime-'+str(line)
            c.execute("INSERT INTO actions(project_id,attempt_id,action_seq,step_id,action_id,proposal_hash,dispatch_state,case_id,case_version_id,outcome_known) VALUES(?,?,?,?,?,'proposal','observed',?,?,1)", (project, attempt, line, action, action, r['case'], saved['case_version_id']))
            detail = json.dumps(dict(phase='after', action_id=action, action_seq=line, sanitized=True))
            c.execute("INSERT INTO attempt_events(project_id,event_id,attempt_id,local_seq,captured_at,event_type,minimum_facts,payload_hash,body_hash,detail_payload) VALUES(?,?,?,?,?,'action.observed','{}','payload','body',?)", (project, str(uuid4()), attempt, line*2, STAMP, detail))
            for role in ('after', 'log'):
                artifact = str(uuid4())
                c.execute('INSERT INTO artifact_refs(project_id,artifact_id,attempt_id,action_id) VALUES(?,?,?,?)', (project, artifact, attempt, action))
                c.execute("INSERT INTO artifact_objects(project_id,artifact_id,object_key,content_hash,byte_length,media_type,owner_id,status,acked,custody,stored_at,owner_kind,attempt_id,action_id,role,job_id,generation) VALUES(?,?,?, ?,1,'text/plain',?,'ready',1,'stored',?,'ITEM',?,?,?,?,1)", (project, artifact, artifact, 'sha256:'+artifact, run, STAMP, attempt, action, role, job))
        for seq in set(range(1, 11)) - {4, 10}:
            c.execute("INSERT INTO attempt_events(project_id,event_id,attempt_id,local_seq,captured_at,event_type,minimum_facts,payload_hash,body_hash) VALUES(?,?,?,?,?,'fixture.prefix','{}','payload','body')", (project, str(uuid4()), attempt, seq, STAMP))
    return dict(r=r, finish=finish, context=context)


def coverage(f, check='c1', *, status='satisfied', action='runtime-2', method='deterministic'):
    context = f['context']
    source = context['steps'][0]['expected'][0] if check=='c1' else context['final_expected'][0]
    return dict(result=dict(check_id=check, status=status, method=method, expected_snapshot='WORKER MUST NOT WRITE THIS', sanitized_observed='password=private', reason='exact_text_match' if status=='satisfied' else 'text_mismatch', observed_at=STAMP, latch=''), phase='step' if check=='c1' else 'final', step_id='s1' if check=='c1' else None, context_hash=context['context_hash'], case_version_id=context['case_version_id'], source_hash=context['content_hash'], kind=source['kind'], action_id=action)


def test_finish_contract_transports_normalized_rows():
    from aiqa.api.worker import _attempt_finish
    from aiqa.worker.runtime import HandlerResult
    result = HandlerResult(0, 'error', True, False, check_results=({'action_id':'a'},))
    assert result.check_results == ({'action_id':'a'},)
    payload = dict(project_id=str(uuid4()), job_id=str(uuid4()), attempt_id=str(uuid4()), generation=1, outcome='error', final_seq=0, last_ack_seq=0, last_ack_hash='ack', manifest_digest='pin', evidence_complete=True, ambiguous_dispatch=False, check_results=[{'action_id':'a'}])
    assert _attempt_finish(payload).check_results == result.check_results
    with pytest.raises(ValueError): _attempt_finish({**payload, 'check_results':'injected'})


def test_normalized_result_uses_source_expected_and_ready_action_artifacts(replay):
    from aiqa.store.replay_check_results import persist_replay_check_results
    f = replay
    with f['r']['store'].transaction() as c:
        result = persist_replay_check_results(c, replace(f['finish'], check_results=(coverage(f),)))
        assert result == 'INCONCLUSIVE'  # final required check remains missing
        row = c.execute("SELECT status,expected_snapshot,sanitized_observed,artifact_refs FROM check_results WHERE check_id='c1'").fetchone()
        assert row[:3] == ('satisfied', 'mouse', '')
        assert len(json.loads(row[3])) == 2


@pytest.mark.parametrize('damage', ['foreign_check', 'version', 'source', 'context', 'boundary', 'foreign_action', 'final_early', 'kind', 'unsupported_state', 'unbound_target', 'unacked'])
def test_worker_cannot_inject_or_satisfy_an_unbound_required_check(replay, damage):
    from aiqa.store.replay_check_results import persist_replay_check_results
    f = replay
    row = coverage(f)
    if damage=='foreign_check': row['result']['check_id']='foreign'
    elif damage=='version': row['case_version_id']=str(uuid4())
    elif damage=='source': row['source_hash']='foreign'
    elif damage=='context': row['context_hash']='foreign'
    elif damage=='boundary': row['action_id']='runtime-5'
    elif damage=='foreign_action': row['action_id']='foreign'
    elif damage=='kind': row['kind']='state'
    elif damage in {'final_early', 'unsupported_state', 'unbound_target'}: row=coverage(f, 'final', action='runtime-2' if damage=='final_early' else 'runtime-5')
    finish = replace(f['finish'], check_results=(row,), last_ack_seq=2 if damage=='unacked' else 10)
    with f['r']['store'].transaction() as c:
        with pytest.raises(ValueError): persist_replay_check_results(c, finish)
        assert c.execute('SELECT count(*) FROM check_results').fetchone()[0] == 0


def test_worker_visual_pass_requires_server_written_verification(replay):
    from aiqa.store.replay_check_results import persist_replay_check_results
    f = replay
    with f['r']['store'].transaction() as c:
        with pytest.raises(ValueError): persist_replay_check_results(c, replace(f['finish'], check_results=(coverage(f, method='ai_visual'),)))


def test_required_violation_is_derived_without_worker_flag_and_never_replaced(replay):
    from aiqa.store.replay_check_results import persist_replay_check_results
    f = replay
    with f['r']['store'].transaction() as c:
        assert persist_replay_check_results(c, replace(f['finish'], check_results=(coverage(f, status='violated'),)))=='FAIL'
        with pytest.raises(ValueError): persist_replay_check_results(c, replace(f['finish'], check_results=(coverage(f),)))
        assert c.execute("SELECT status FROM check_results WHERE check_id='c1'").fetchone()[0]=='violated'


def test_missing_rows_on_pinned_native_replay_are_inconclusive(replay):
    from aiqa.store.replay_check_results import persist_replay_check_results
    with replay['r']['store'].transaction() as c:
        assert persist_replay_check_results(c, replay['finish'])=='INCONCLUSIVE'


@pytest.mark.parametrize('status, expected', [('satisfied', 'INCONCLUSIVE'), ('violated', 'FAIL'), (None, 'INCONCLUSIVE')])
def test_attempt_finish_derives_required_result_and_replays_receipt(replay, status, expected):
    from aiqa.store.evidence import _cursor
    from aiqa.store.models import WorkerScope
    from aiqa.store.queue import finish_worker_attempt, FinishConflict
    f = replay
    finish = f['finish']
    moment = datetime.fromisoformat(STAMP)
    worker = WorkerScope('check-worker', (finish.project_id,), ('trial',))
    with f['r']['store'].transaction() as c:
        c.execute("INSERT INTO leases(project_id,job_id,generation,worker_id,expires_at) VALUES(?,?,1,'check-worker',?)", (str(finish.project_id), str(finish.job_id), (moment+timedelta(minutes=5)).isoformat()))
        c.execute("INSERT INTO attempt_runners(project_id,attempt_id,runner_nonce,acked_at) VALUES(?,?,'runner',?)", (str(finish.project_id), str(finish.attempt_id), STAMP))
        seq, ack = _cursor(c, finish.project_id, str(finish.attempt_id))
        finish = replace(finish, last_ack_seq=seq, last_ack_hash=ack, check_results=() if status is None else (coverage(f, status=status),))
        receipt = finish_worker_attempt(c, worker, finish, request_key='seal', body_hash='body', now=moment)
        assert receipt.verdict == expected and receipt.approved is False
        repeated = finish_worker_attempt(c, worker, finish, request_key='seal', body_hash='body', now=moment)
        assert repeated.replayed is True and repeated.verdict == expected
        with pytest.raises(FinishConflict): finish_worker_attempt(c, worker, finish, request_key='second', body_hash='body', now=moment)


def test_unconnected_visual_placeholder_is_durable_unknown(replay, monkeypatch):
    import aiqa.store.replay_check_results as results
    f = replay
    with f['r']['store'].transaction() as c:
        source = results.load_replay_check_source(c, f['finish'])
        context = copy.deepcopy(source.context)
        context['verification'] = [dict(method='ai_visual', binding_id='saved', allow_unknown_supplement=False)]
        source = replace(source, context=context)
        monkeypatch.setattr(results, 'load_replay_check_source', lambda *args:source)
        row = coverage(f, status='unknown', method='ai_visual')
        row['result']['reason']='verifier_not_connected'
        assert results.persist_replay_check_results(c, replace(f['finish'], check_results=(row,)))=='INCONCLUSIVE'
        assert c.execute("SELECT status,method FROM check_results WHERE check_id='c1'").fetchone()==('unknown', 'ai_visual')


def test_missing_source_policy_allows_only_unknown_placeholder(replay, monkeypatch):
    import aiqa.store.replay_check_results as results
    f = replay
    with f['r']['store'].transaction() as c:
        source = results.load_replay_check_source(c, f['finish'])
        context = copy.deepcopy(source.context); context['verification']=[]
        source = replace(source, context=context)
        monkeypatch.setattr(results, 'load_replay_check_source', lambda *args:source)
        row = coverage(f, status='unknown'); row['result']['reason']='verifier_policy_missing'
        assert results.persist_replay_check_results(c, replace(f['finish'], check_results=(row,)))=='INCONCLUSIVE'
        with pytest.raises(ValueError): results.persist_replay_check_results(c, replace(f['finish'], check_results=(coverage(f),)))


def test_all_required_checks_must_be_satisfied_for_pass(replay, monkeypatch):
    import aiqa.store.replay_check_results as results
    f = replay
    with f['r']['store'].transaction() as c:
        source = results.load_replay_check_source(c, f['finish'])
        context = copy.deepcopy(source.context); context['final_expected']=[]
        source = replace(source, context=context)
        monkeypatch.setattr(results, 'load_replay_check_source', lambda *args:source)
        assert results.persist_replay_check_results(c, replace(f['finish'], check_results=(coverage(f),)))=='PASS'


def _worker_row(f, *, status, reason, action='runtime-2'):
    from aiqa.contracts.checks import CheckResult
    from aiqa.worker.replay_check_coverage import RequiredCheckCoverage
    context = f['context']
    check = context['steps'][0]['expected'][0]
    coverage = RequiredCheckCoverage(
        CheckResult(check['id'], status, 'deterministic', 'WORKER MUST NOT WRITE THIS', 'password=private', reason, STAMP, 'FAIL' if status=='violated' else ''),
        'step', 's1', context['context_hash'], context['case_version_id'], context['content_hash'], check['kind'])
    return {**asdict(coverage), 'action_id': action}


def _seal(f, row, *, outcome):
    from aiqa.store.evidence import _cursor
    from aiqa.store.models import WorkerScope
    from aiqa.store.queue import finish_worker_attempt
    finish = f['finish']
    moment = datetime.fromisoformat(STAMP)
    worker = WorkerScope('check-worker', (finish.project_id,), ('trial',))
    with f['r']['store'].transaction() as c:
        raw = json.loads(c.execute('SELECT limits FROM jobs WHERE job_id=?', (str(finish.job_id),)).fetchone()[0])
        raw['failure_policy'] = 'continue'
        c.execute('UPDATE jobs SET limits=? WHERE job_id=?', (json.dumps(raw), str(finish.job_id)))
        c.execute("INSERT INTO leases(project_id,job_id,generation,worker_id,expires_at) VALUES(?,?,1,'check-worker',?)", (str(finish.project_id), str(finish.job_id), (moment+timedelta(minutes=5)).isoformat()))
        c.execute("INSERT INTO attempt_runners(project_id,attempt_id,runner_nonce,acked_at) VALUES(?,?,'runner',?)", (str(finish.project_id), str(finish.attempt_id), STAMP))
        seq, ack = _cursor(c, finish.project_id, str(finish.attempt_id))
        approval = c.execute('SELECT current_approval_id FROM automation_cases WHERE case_id=?', (f['r']['case'],)).fetchone()[0]
        sealed = replace(finish, outcome=outcome, last_ack_seq=seq, last_ack_hash=ack, check_results=(row,), required_violation=False)
        receipt = finish_worker_attempt(c, worker, sealed, request_key='seal', body_hash='body', now=moment)
        item = c.execute('SELECT core_result, content_hash FROM item_finalizations WHERE case_run_id=?', (c.execute('SELECT case_run_id FROM jobs WHERE job_id=?', (str(finish.job_id),)).fetchone()[0],)).fetchone()
        stored = c.execute("""SELECT cr.status, cr.expected_snapshot, cr.sanitized_observed, cr.artifact_refs, v.content_hash
            FROM check_results cr
            JOIN actions a ON a.project_id=cr.project_id AND a.attempt_id=cr.attempt_id AND a.action_id=cr.action_id
            JOIN case_versions v ON v.project_id=a.project_id AND v.version_id=a.case_version_id
            WHERE cr.check_id='c1'""").fetchone()
        later = c.execute('SELECT current_approval_id FROM automation_cases WHERE case_id=?', (f['r']['case'],)).fetchone()[0]
    return receipt, item, stored, approval, later


def test_worker_violation_commits_item_fail_without_changing_approval(replay):
    from aiqa.store.replay_check_results import persist_replay_check_results
    receipt, item, stored, before, after = _seal(replay, _worker_row(replay, status='violated', reason='text_mismatch'), outcome='error')
    assert receipt.approved is False and receipt.verdict == 'FAIL'
    assert item[0] == 'FAIL'
    assert stored[:3] == ('violated', 'mouse', '')
    assert len(json.loads(stored[3])) == 2 and stored[4] == replay['context']['content_hash']
    assert 'password=private' not in ''.join(stored[:3]) and before == after
    with replay['r']['store'].transaction() as c:
        with pytest.raises(ValueError): persist_replay_check_results(c, replace(replay['finish'], check_results=(_worker_row(replay, status='satisfied', reason='exact_text_match'),)))
        assert c.execute("SELECT status FROM check_results WHERE check_id='c1'").fetchone()[0] == 'violated'


def test_worker_unknown_commits_inconclusive_item_and_not_a_pass(replay):
    receipt, item, stored, before, after = _seal(replay, _worker_row(replay, status='unknown', reason='target_ambiguous'), outcome='error')
    assert receipt.approved is False and receipt.verdict == 'INCONCLUSIVE'
    assert item[0] == 'INCONCLUSIVE'
    assert stored[0] == 'unknown' and stored[1] == 'mouse' and stored[4] == replay['context']['content_hash']
    assert before == after


def test_completed_item_passes_only_when_every_required_check_is_satisfied(replay, monkeypatch):
    import aiqa.store.replay_check_results as results
    source = None
    with replay['r']['store'].transaction() as c:
        source = results.load_replay_check_source(c, replay['finish'])
    context = copy.deepcopy(source.context)
    context['final_expected'] = []
    monkeypatch.setattr(results, 'load_replay_check_source', lambda *args: replace(source, context=context))
    receipt, item, stored, before, after = _seal(replay, _worker_row(replay, status='satisfied', reason='exact_text_match'), outcome='completed')
    assert receipt.approved is False and receipt.verdict == 'PASS'
    assert item[0] == 'PASS' and stored[0] == 'satisfied' and stored[1] == 'mouse'
    assert before == after


def test_runtime_serializes_normalized_results_in_finish_payload():
    from aiqa.worker.runtime import HandlerResult, WorkerRuntime
    runtime = WorkerRuntime.__new__(WorkerRuntime)
    sent=[]
    runtime._now=lambda:datetime.fromisoformat(STAMP)
    runtime._client=SimpleNamespace(finish_attempt=lambda **kwargs:sent.append(kwargs) or {'saved':True})
    claim=dict(project_id=str(uuid4()), job_id=str(uuid4()), attempt_id=str(uuid4()), generation=1, snapshot=dict(digest='pin'))
    rows=({'action_id':'observed'},)
    assert runtime._submit_finish(claim, HandlerResult(0,'error',True,False,check_results=rows))=={'saved':True}
    assert sent[0]['payload']['check_results']==list(rows)
