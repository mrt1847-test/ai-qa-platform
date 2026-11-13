"""Normal leased recording authoring through the existing server gateway and durable quota."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime,timezone
from urllib.parse import urlsplit
from uuid import uuid4
from aiqa.models.broker import ModelRequestDenied,ModelRequestConflict
from aiqa.models.recording_authorization import authorize_recording
from aiqa.recording.intent import IntentRejected,bind_authoring_sanitized_inputs
from aiqa.store.model_requests import (model_error,prior_request,request_fingerprint,reserve_request,settle_request,used_calls)


def _now():return datetime.now(timezone.utc)


def _provider_endpoint(provider, grant):
    fixed = urlsplit(grant.endpoint)
    if getattr(provider, 'kind', None) == 'fixture':
        if (grant.provider != 'fixture' or grant.endpoint_kind != 'loopback'
            or fixed.scheme != 'http' or fixed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or fixed.username or fixed.password or fixed.query or fixed.fragment):
            raise ModelRequestDenied('provider_endpoint', status=503)
        return
    if getattr(provider, 'kind', None) != 'operational' or not getattr(provider, 'allow_live', False):
        raise ModelRequestDenied('provider_unavailable', status=503)
    if (grant.provider == 'fixture' or grant.endpoint_kind != 'https'
        or fixed.scheme != 'https' or not fixed.netloc or fixed.username or fixed.password
        or fixed.query or fixed.fragment
        or grant.endpoint.rstrip('/') != str(getattr(provider, 'base_url', '')).rstrip('/')):
        raise ModelRequestDenied('provider_endpoint', status=503)


def handle_recording_request(store,gateway,settings,worker,request,project_id,item_id,key,presented_intent):
    # The raw request participates too, so spoofed/dropped objective text cannot
    # change under the same receipt key even though only server-bound intent is sent.
    from aiqa.domain.hashing import canonical_hash
    fingerprint=canonical_hash({'request':request_fingerprint(request,project_id,item_id),'intent_hash':presented_intent},'canon-json-v1')
    reserved=False
    try:
        with store.transaction() as c:
            if project_id not in worker.permitted_projects or 'recording' not in worker.permitted_purposes:
                raise ModelRequestDenied('recording_authorization')
            prior=prior_request(c,project_id,item_id,key,fingerprint,worker.worker_id)
            if prior is not None:
                status,body=prior
                if 'error' not in body:
                    try:authorize_recording(c,worker,request,project_id,item_id,_now())
                    except ModelRequestDenied:body['action_allowed']=False
                    else:body['action_allowed']=True
                return status,body
            grant=authorize_recording(c,worker,request,project_id,item_id,_now())
            if presented_intent is None:raise ModelRequestDenied('intent_hash_required')
            try:inputs=bind_authoring_sanitized_inputs(c,project_id=project_id,attempt_id=item_id,presented_hash=presented_intent,worker_inputs=request.sanitized_inputs)
            except IntentRejected:raise ModelRequestDenied('intent_invalid')
            # Unknown tariff has no monetary guarantee; only explicitly enabled
            # estimate mode may proceed, with unreported usage in every receipt.
            if settings.model_price_mode!='estimate':raise ModelRequestDenied('unknown_price',status=503)
            _provider_endpoint(gateway.provider,grant)
            reserve_request(c,project_id,item_id,key,request,worker.worker_id,fingerprint,grant,_now())
        reserved=True
        policy=grant.policy
        existing=gateway._policies.get((project_id,item_id))
        if existing is not None and existing!=policy:raise ModelRequestDenied('policy_conflict')
        gateway.ensure_policy(policy)
        bound=replace(request,sanitized_inputs=inputs)
        def before_provider():
            with store.transaction() as c:
                authorize_recording(c,worker,request,project_id,item_id,_now())
        receipt=gateway.handle(worker,bound,project_id=project_id,item_id=item_id,
            idempotency_key='recording:'+str(project_id)+':'+item_id+':'+key,actor_id=grant.actor_id,store=store,before_provider=before_provider)
        with store.transaction() as c:
            try:authorize_recording(c,worker,request,project_id,item_id,_now())
            except ModelRequestDenied:
                body=model_error('response_late',True);status=403
            else:
                calls=used_calls(c,project_id,item_id)
                body={'call_id':str(receipt.call_id),'allowed':True,'action_allowed':True,'reason':'admitted','actual_model':receipt.actual_model,
                    'measurement_status':'unreported','provider_request_id':receipt.provider_request_id,'role':'authoring',
                    'purpose':'recording','replayed':False,'content':receipt.content,'item_id':item_id,'generation':policy.generation,
                    'provider_dispatched':True,'usage':{'authoring_calls':calls,'verification_calls':0,'healing_calls':0,'maintenance_calls':0,
                        'input_tokens':None,'output_tokens':None,'reserved_cost':None,'cost_status':'unknown','price_mode':'estimate',
                        'budget':policy.budget,'currency':'USD','incomplete':True}}
                status=200
            settle_request(c,project_id,item_id,key,status,body,True,_now())
        return status,body
    except ModelRequestConflict:return 409,model_error('idempotency_conflict')
    except ModelRequestDenied as exc:
        body=model_error(exc.reason,exc.provider_dispatched);status=exc.status
        if reserved:
            with store.transaction() as c:settle_request(c,project_id,item_id,key,status,body,exc.provider_dispatched,_now())
        return status,body
    except Exception:
        # Reservation may cover an uncertain send. Persist a conservative unknown
        # result, without exception text, and never automatically send it again.
        if not reserved:raise
        body=model_error('dispatch_unknown',None)
        with store.transaction() as c:settle_request(c,project_id,item_id,key,503,body,True,_now())
        return 503,body


def handle_recording_http(open_store,gateway,settings,worker,request,project_id,item_id,key,presented_intent):
    # SQLite connection is created in the same worker thread that uses it.
    store=open_store()
    try:return handle_recording_request(store,gateway,settings,worker,request,project_id,item_id,key,presented_intent)
    finally:store.close()
