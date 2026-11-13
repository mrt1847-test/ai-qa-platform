"""One durable call reservation per real send, independent of gateway process memory."""
from __future__ import annotations
import json
from uuid import uuid4
from dataclasses import asdict
from aiqa.domain.hashing import canonical_hash
from aiqa.models.broker import ModelRequestConflict,ModelRequestDenied


def request_fingerprint(request,project_id,item_id):
    return canonical_hash({'project_id':str(project_id),'item_id':item_id,**{
        **asdict(request),'call_id':str(request.call_id),'sanitized_inputs':list(request.sanitized_inputs)}},'canon-json-v1')


def prior_request(connection,project_id,item_id,key,fingerprint,worker_id):
    row=connection.execute("""SELECT fingerprint,worker_id,state,status_code,response_json FROM model_request_receipts
        WHERE project_id=? AND attempt_id=? AND request_key=?""",(str(project_id),item_id,key)).fetchone()
    if row is None:return None
    if row[1]!=worker_id:raise ModelRequestDenied('recording_authorization')
    if row[0]!=fingerprint:raise ModelRequestConflict('idempotency conflict')
    if row[2]=='pending':return 503,model_error('dispatch_unknown',None,replayed=True)
    body=json.loads(row[4])
    if 'error' in body:body['error']['replayed']=True
    else:body['replayed']=True
    return row[3],body


def used_calls(connection,project_id,item_id):
    return connection.execute('SELECT COALESCE(SUM(charged),0) FROM model_request_receipts WHERE project_id=? AND attempt_id=?',
        (str(project_id),item_id)).fetchone()[0]


def reserve_request(connection,project_id,item_id,key,request,worker_id,fingerprint,grant,now):
    if connection.execute('SELECT 1 FROM model_request_receipts WHERE project_id=? AND call_id=?',(str(project_id),str(request.call_id))).fetchone():
        raise ModelRequestConflict('call id already reserved')
    if used_calls(connection,project_id,item_id)>=grant.policy.max_calls:raise ModelRequestDenied('quota')
    if connection.execute("SELECT 1 FROM model_request_receipts WHERE project_id=? AND attempt_id=? AND state='pending'",(str(project_id),item_id)).fetchone():
        raise ModelRequestConflict('model request in flight')
    connection.execute("""INSERT INTO model_request_receipts
        (project_id,attempt_id,request_key,call_id,worker_id,fingerprint,policy_ref,price_mode,state,charged,created_at)
        VALUES (?,?,?,?,?,?,?,'estimate','pending',1,?)""",
        (str(project_id),item_id,key,str(request.call_id),worker_id,fingerprint,grant.policy_ref,now.isoformat()))


def settle_request(connection,project_id,item_id,key,status,body,charged,now):
    result=connection.execute("""UPDATE model_request_receipts SET state='completed',charged=?,status_code=?,response_json=?,completed_at=?
        WHERE project_id=? AND attempt_id=? AND request_key=? AND state='pending'""",
        (int(charged),status,json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')),now.isoformat(),str(project_id),item_id,key))
    if result.rowcount!=1:raise ModelRequestConflict('model settlement conflict')


def model_error(reason,dispatched=False,*,replayed=False):
    return {'error':{'code':'model_request','message':reason,'fields':{},'retryable':False,
        'provider_dispatched':dispatched,'replayed':replayed,'request_id':str(uuid4())}}
