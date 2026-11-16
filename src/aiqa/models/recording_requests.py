"""Normal leased recording authoring through the existing server gateway and durable quota."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime,timezone
from urllib.parse import urlsplit
from uuid import uuid4
from aiqa.contracts.mobile_agent_engine import is_openai_endpoint
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
    if getattr(provider,'kind',None)=='openai':
        from aiqa.models.openai_server import OpenAIServerProvider
        if (type(provider) is not OpenAIServerProvider or grant.provider!='openai' or grant.endpoint_kind!='https'
            or not is_openai_endpoint(grant.endpoint)
            or fixed.username or fixed.password or fixed.query or fixed.fragment):
            raise ModelRequestDenied('provider_endpoint',status=503)
        return
    if getattr(provider, 'kind', None) != 'operational' or not getattr(provider, 'allow_live', False):
        raise ModelRequestDenied('provider_unavailable', status=503)
    if (grant.provider in {'fixture','openai'} or grant.endpoint_kind != 'https'
        or fixed.scheme != 'https' or not fixed.netloc or fixed.username or fixed.password
        or fixed.query or fixed.fragment
        or grant.endpoint.rstrip('/') != str(getattr(provider, 'base_url', '')).rstrip('/')):
        raise ModelRequestDenied('provider_endpoint', status=503)


def handle_recording_request(store,gateway,settings,worker,request,project_id,item_id,key,presented_intent):
    from aiqa.domain.hashing import canonical_hash
    from aiqa.models.model_observations import load_authoring_observation
    fingerprint = canonical_hash({'request':request_fingerprint(request,project_id,item_id),
        'intent_hash':presented_intent}, 'canon-json-v1')
    reserved = False
    mobile_state = None
    def reuse(prior):
        status,body=prior
        if 'error' not in body:
            try:
                load_authoring_observation(store,worker,request,project_id,item_id)
                with store.transaction() as connection:
                    current=authorize_recording(connection,worker,request,project_id,item_id,_now())
                    consumed=current.engine_kind is not None and connection.execute(
                        "SELECT 1 FROM artifact_objects WHERE project_id=? AND attempt_id=? AND action_id=? AND owner_kind='REC' AND role IN ('after','log') AND status='ready' AND acked=1 AND generation=? LIMIT 1",
                        (str(project_id),item_id,'ma-'+str(request.call_id),request.generation)).fetchone() is not None
            except ModelRequestDenied:body['action_allowed']=False
            else:body['action_allowed']=not consumed
        return status,body
    try:
        with store.transaction() as connection:
            if project_id not in worker.permitted_projects or 'recording' not in worker.permitted_purposes:
                raise ModelRequestDenied('recording_authorization')
            prior = prior_request(connection,project_id,item_id,key,fingerprint,worker.worker_id)
        if prior is not None:return reuse(prior)
        with store.transaction() as connection:
            grant = authorize_recording(connection,worker,request,project_id,item_id,_now())
            if presented_intent is None:
                raise ModelRequestDenied('intent_hash_required')
            try:
                inputs = bind_authoring_sanitized_inputs(connection,project_id=project_id,attempt_id=item_id,
                    presented_hash=presented_intent,worker_inputs=request.sanitized_inputs)
            except IntentRejected:
                raise ModelRequestDenied('intent_invalid')
            if settings.model_price_mode!='estimate':
                raise ModelRequestDenied('unknown_price',status=503)
            admitted_provider=gateway.provider
            _provider_endpoint(admitted_provider,grant)
            if not getattr(admitted_provider,'supports_observation',False):
                raise ModelRequestDenied('provider_observation_unsupported',status=503)
        frame = load_authoring_observation(store,worker,request,project_id,item_id)
        if grant.engine_kind is not None:
            from aiqa.models.mobile_agent_history import load_mobile_agent_history
            mobile_state=load_mobile_agent_history(store,worker,request,project_id,item_id)
        with store.transaction() as connection:
            prior=prior_request(connection,project_id,item_id,key,fingerprint,worker.worker_id)
            if prior is None:
                current = authorize_recording(connection,worker,request,project_id,item_id,_now())
                if current.policy_ref!=grant.policy_ref:
                    raise ModelRequestDenied('recording_policy_invalid')
                reserve_request(connection,project_id,item_id,key,request,worker.worker_id,fingerprint,grant,_now())
        if prior is not None:return reuse(prior)
        reserved = True
        policy = grant.policy
        existing = gateway._policies.get((project_id,item_id))
        if existing is not None and existing!=policy:
            raise ModelRequestDenied('policy_conflict')
        gateway.ensure_policy(policy)
        bound = replace(request,sanitized_inputs=inputs)
        def before_provider():
            load_authoring_observation(store,worker,request,project_id,item_id)
            with store.transaction() as connection:
                current=authorize_recording(connection,worker,request,project_id,item_id,_now())
                if current.policy_ref!=grant.policy_ref or current.policy!=grant.policy:
                    raise ModelRequestDenied('recording_policy_invalid')
                if gateway.provider is not admitted_provider:
                    raise ModelRequestDenied('provider_unavailable',status=503)
                _provider_endpoint(admitted_provider,current)
            if mobile_state is not None:
                fresh=load_mobile_agent_history(store,worker,request,project_id,item_id)
                if fresh.fingerprint!=mobile_state.fingerprint:
                    raise ModelRequestDenied('mobile_history_changed')
        receipt = gateway.handle(worker,bound,project_id=project_id,item_id=item_id,
            idempotency_key='recording:'+str(project_id)+':'+item_id+':'+key,actor_id=grant.actor_id,
            store=store,before_provider=before_provider,observation=frame if mobile_state is None else None,
            provider_pin=admitted_provider,mobile_context=None if mobile_state is None else mobile_state.context)
        with store.transaction() as connection:
            calls=used_calls(connection,project_id,item_id)
        usage={'authoring_calls':calls,'verification_calls':0,'healing_calls':0,'maintenance_calls':0,
            'input_tokens':receipt.usage.get('input_tokens'),'output_tokens':receipt.usage.get('output_tokens'),
            'cached_input_tokens':receipt.usage.get('cached_input_tokens'),'reasoning_tokens':receipt.usage.get('reasoning_tokens'),
            'total_tokens':receipt.usage.get('total_tokens'),'token_scope':'call','tokens_complete':receipt.usage.get('tokens_complete',False),
            'reserved_cost':None,'cost_status':'unknown','price_mode':'estimate','budget':policy.budget,'currency':'USD','incomplete':True}
        measurements={'actual_model':receipt.actual_model,'measurement_status':receipt.usage.get('measurement_status','unreported'),
            'provider_request_id':receipt.provider_request_id,'usage':usage}
        response_error='mobile_action_invalid'
        try:
            load_authoring_observation(store,worker,request,project_id,item_id)
            if mobile_state is not None:
                if receipt.actual_model!='gpt-6-luna':
                    response_error='mobile_model_mismatch'
                    raise ValueError('unexpected recording model')
                from aiqa.models.mobile_agent_context import validate_mobile_agent_reply
                validate_mobile_agent_reply(content=receipt.content,context=mobile_state.context,geometry=frame.geometry)
                load_authoring_observation(store,worker,request,project_id,item_id)
        except ModelRequestDenied:
            body=model_error('response_late',True)
            body.update(measurements)
            status=403
        except ValueError:
            body=model_error(response_error,True)
            body.update(measurements)
            status=502
        else:
            body={'call_id':str(receipt.call_id),'allowed':True,'action_allowed':True,'reason':'admitted',
                **measurements,'role':'authoring','purpose':'recording','replayed':False,'content':receipt.content,
                'item_id':item_id,'generation':policy.generation,'provider_dispatched':True,
                'model_observation_id':request.model_observation_id,'image_hash':frame.image_hash}
            status=200
        with store.transaction() as connection:
            settle_request(connection,project_id,item_id,key,status,body,True,_now())
        return status,body
    except ModelRequestConflict:
        return 409,model_error('idempotency_conflict')
    except ModelRequestDenied as exc:
        body = model_error(exc.reason,exc.provider_dispatched)
        if reserved:
            with store.transaction() as connection:
                settle_request(connection,project_id,item_id,key,exc.status,body,exc.provider_dispatched,_now())
        return exc.status,body
    except Exception:
        if not reserved:
            raise
        body = model_error('dispatch_unknown',None)
        with store.transaction() as connection:
            settle_request(connection,project_id,item_id,key,503,body,True,_now())
        return 503,body


def handle_recording_http(open_store,gateway,settings,worker,request,project_id,item_id,key,presented_intent):
    # SQLite connection is created in the same worker thread that uses it.
    store=open_store()
    try:return handle_recording_request(store,gateway,settings,worker,request,project_id,item_id,key,presented_intent)
    finally:store.close()
