"""Confirm one immutable evidence payload; a retry never reruns a device or model."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from uuid import UUID

from aiqa.worker.http_client import RetryClass, WorkerHttpError


class StepEvidenceCommitter:
    def __init__(self, client, claim, *, clock=None):
        self.client = client
        self.claim = {name:claim.get(name) for name in ('project_id','job_id','attempt_id','generation')}
        self.clock = clock or (lambda:datetime.now(timezone.utc))
        self._entries = {}
        self._pending_seq = None
        self._last_seq = 0
        self._lock = threading.Lock()

    def __call__(self, *, action_seq, action_id, events, artifacts):
        del action_id  # Exact action identity is carried by the events/artifacts.
        with self._lock:
            return self._commit(action_seq,events,artifacts)

    def _commit(self, action_seq, events, artifacts):
        if type(action_seq) is not int or not 1 <= action_seq <=51:
            raise WorkerHttpError('invalid evidence step',retry_class=RetryClass.fatal,status_code=422)
        try:
            owner = {name:str(UUID(str(self.claim[name]))) for name in ('project_id','job_id','attempt_id')}
            generation = self.claim['generation']
            if type(generation) is not int or generation<1:
                raise ValueError('generation')
            serialized = json.dumps({'events':events,'artifacts':artifacts},sort_keys=True,
                ensure_ascii=False,separators=(',',':'),allow_nan=False)
            frozen = json.loads(serialized)
            if type(frozen['events']) is not list or type(frozen['artifacts']) is not list:
                raise ValueError('evidence')
            expected_seq = max([self._last_seq]+[event['local_seq'] for event in frozen['events']])
            if type(expected_seq) is not int or expected_seq<0:
                raise ValueError('prefix')
        except (ValueError,TypeError,KeyError) as exc:
            raise WorkerHttpError('invalid step evidence',retry_class=RetryClass.fatal,status_code=422) from exc
        fingerprint = hashlib.sha256(serialized.encode('utf-8')).hexdigest()
        entry = self._entries.get(action_seq)
        if entry is not None:
            if entry['fingerprint']!=fingerprint:
                raise WorkerHttpError('evidence step body changed',retry_class=RetryClass.conflict,status_code=409)
            if entry['receipt'] is not None:
                return copy.deepcopy(entry['receipt'])
        else:
            if self._pending_seq is not None:
                raise WorkerHttpError('evidence prefix unconfirmed',retry_class=RetryClass.conflict,status_code=409)
            entry = {'fingerprint':fingerprint,'receipt':None,'payload':{
                'sanitized':True,'project_id':owner['project_id'],'job_id':owner['job_id'],'generation':generation,
                'now':self.clock().isoformat(),'events':frozen['events'],'artifacts':frozen['artifacts'],
                'idempotency_key':f"evidence-{owner['attempt_id']}-step-{action_seq}",
            }}
            self._entries[action_seq] = entry
            self._pending_seq = action_seq
        for send in range(2):
            try:
                receipt = self.client.commit_evidence(**entry['payload'])
                break
            except WorkerHttpError as exc:
                if send==0 and exc.retry_class in {RetryClass.timeout,RetryClass.retryable} and exc.status_code!=429:
                    continue
                raise
        try:
            if (type(receipt) is not dict or receipt.get('attempt_id')!=owner['attempt_id']
                or receipt.get('late') is not False or type(receipt.get('contiguous_seq')) is not int
                or receipt['contiguous_seq']<expected_seq
                or type(receipt.get('prefix_hash')) is not str
                or re.fullmatch('sha256:[0-9a-f]{64}',receipt['prefix_hash']) is None
                or type(receipt.get('artifact_ids')) is not list
                or len(receipt['artifact_ids'])!=len(frozen['artifacts'])):
                raise ValueError('acknowledgement')
            for artifact_id in receipt['artifact_ids']:
                UUID(artifact_id)
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            raise WorkerHttpError('invalid evidence acknowledgement',retry_class=RetryClass.fatal) from exc
        self._last_seq = max(self._last_seq,receipt['contiguous_seq'])
        entry['receipt'] = copy.deepcopy(receipt)
        entry['payload'] = None  # Retain only the small receipt after ACK, not every PNG body.
        self._pending_seq = None
        return copy.deepcopy(receipt)
