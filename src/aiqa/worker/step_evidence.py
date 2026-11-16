"""Confirm one immutable evidence payload; a retry never reruns a device or model."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from uuid import UUID
from pathlib import Path
from contextlib import contextmanager,ExitStack
from aiqa.worker.files import atomic_write,file_lock

from aiqa.worker.http_client import RetryClass, WorkerHttpError


class StepEvidenceCommitter:
    def __init__(self, client, claim, *, clock=None, namespace="step", pending_path=None):
        if namespace not in {"step","prepare","mobile"}:
            raise ValueError("evidence namespace invalid")
        if pending_path is not None and namespace!="mobile":raise ValueError("durable evidence requires mobile namespace")
        self.pending_path=None if pending_path is None else Path(pending_path)
        self.namespace = namespace
        self.client = client
        self.claim = {name:claim.get(name) for name in ('project_id','job_id','attempt_id','generation','worker_id')}
        self.clock = clock or (lambda:datetime.now(timezone.utc))
        self._entries = {}
        self._pending_seq = None
        self._last_seq = 0
        self._lock = threading.Lock()

    def __call__(self, *, action_seq, action_id, events, artifacts):
        del action_id  # Exact action identity is carried by the events/artifacts.
        with self._lock, self._disk_lock():
            self._load()
            return self._commit(action_seq,events,artifacts)

    def _commit(self, action_seq, events, artifacts):
        if type(action_seq) is not int or not 1 <= action_seq <=(81 if self.namespace=="mobile" else 51):
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
            event_seqs=[event['local_seq'] for event in frozen['events']]
            if self.pending_path is not None and any(type(seq) is not int or seq<1 for seq in event_seqs):raise ValueError('event sequence')
            event_max_seq=max([0,*event_seqs])
            expected_seq = max(self._last_seq,event_max_seq)
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
            if self.namespace=='mobile' and action_seq!=max([0,*self._entries])+1:
                raise WorkerHttpError('evidence turn gap',retry_class=RetryClass.conflict,status_code=409)
            moment=self.clock()
            if self.pending_path is not None and (not isinstance(moment,datetime) or moment.tzinfo is None):
                raise WorkerHttpError('durable evidence timestamp must be aware',retry_class=RetryClass.fatal,status_code=422)
            entry = {'fingerprint':fingerprint,'receipt':None,'expected_seq':expected_seq,'event_max_seq':event_max_seq,'artifact_count':len(frozen['artifacts']),'payload':{
                'sanitized':True,'project_id':owner['project_id'],'job_id':owner['job_id'],'generation':generation,
                'now':moment.isoformat(),'events':frozen['events'],'artifacts':frozen['artifacts'],
                'idempotency_key':f"evidence-{owner['attempt_id']}-{self.namespace}-{action_seq}",
            }}
            self._entries[action_seq] = entry
            self._pending_seq = action_seq
        self._save()
        for send in range(2):
            try:
                receipt = self.client.commit_evidence(**entry['payload'])
                break
            except WorkerHttpError as exc:
                if send==0 and exc.retry_class in {RetryClass.timeout,RetryClass.retryable} and exc.status_code!=429:
                    continue
                raise
        self._validate_receipt(receipt,owner,expected_seq,len(frozen['artifacts']))
        previous=copy.deepcopy(entry);previous_seq=self._last_seq
        self._last_seq = max(self._last_seq,receipt['contiguous_seq'])
        entry['receipt'] = copy.deepcopy(receipt)
        entry['payload'] = None  # Retain only the small receipt after ACK, not every PNG body.
        self._pending_seq = None
        try:self._save()
        except WorkerHttpError:
            # Until the receipt is durable, retain the exact pending payload in memory too.
            # Repeated ACK-save failures must not make the caller freeze an older cursor.
            self._entries[action_seq]=previous;self._last_seq=previous_seq;self._pending_seq=action_seq
            raise
        return copy.deepcopy(receipt)

    def _validate_receipt(self,receipt,owner,expected_seq,artifact_count):
        try:
            if (type(receipt) is not dict or receipt.get('attempt_id')!=owner['attempt_id']
                or receipt.get('late') is not False or type(receipt.get('contiguous_seq')) is not int
                or receipt['contiguous_seq']<expected_seq
                or type(receipt.get('prefix_hash')) is not str
                or re.fullmatch('sha256:[0-9a-f]{64}',receipt['prefix_hash']) is None
                or type(receipt.get('artifact_ids')) is not list
                or len(receipt['artifact_ids'])!=artifact_count):
                raise ValueError('acknowledgement')
            for artifact_id in receipt['artifact_ids']:
                UUID(artifact_id)
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            raise WorkerHttpError('invalid evidence acknowledgement',retry_class=RetryClass.fatal) from exc

    @contextmanager
    def _disk_lock(self):
        with ExitStack() as stack:
            if self.pending_path is not None:
                try:stack.enter_context(file_lock(self.pending_path.with_suffix(self.pending_path.suffix+'.lock')))
                except OSError:raise WorkerHttpError('durable evidence lock unavailable',retry_class=RetryClass.fatal) from None
            yield

    def _owner(self):
        owner={name:str(UUID(str(self.claim[name]))) for name in ('project_id','job_id','attempt_id')}
        generation=self.claim['generation'];worker=self.claim.get('worker_id')
        if type(generation) is not int or generation<1 or type(worker) is not str or not worker:
            raise ValueError('evidence owner')
        return {**owner,'generation':generation,'worker_id':worker}

    @staticmethod
    def _checksum(state):
        body={key:value for key,value in state.items() if key!='checksum'}
        return hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')).hexdigest()

    def _save(self):
        if self.pending_path is None:return
        try:
            state={'version':1,'owner':self._owner(),'namespace':self.namespace,'entries':self._entries,
                'pending_seq':self._pending_seq,'last_seq':self._last_seq}
            state['checksum']=self._checksum(state)
            raw=json.dumps(state,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
            if len(raw)>8000000:raise ValueError('journal size')
            atomic_write(self.pending_path,raw)
        except (ValueError,TypeError,KeyError,OSError,RecursionError):
            raise WorkerHttpError('durable evidence journal unavailable',retry_class=RetryClass.fatal) from None

    def _load(self):
        if self.pending_path is None:return
        try:
            if not self.pending_path.exists():return
            with self.pending_path.open('rb') as stream:raw=stream.read(8000001)
            if len(raw)>8000000:raise ValueError('journal size')
            def unique(pairs):
                values={}
                for key,value in pairs:
                    if key in values:raise ValueError('duplicate journal field')
                    values[key]=value
                return values
            state=json.loads(raw,object_pairs_hook=unique)
            owner=self._owner()
            if (type(state) is not dict or set(state)!={'version','owner','namespace','entries','pending_seq','last_seq','checksum'}
                or type(state['checksum']) is not str or re.fullmatch('[0-9a-f]{64}',state['checksum']) is None
                or state['checksum']!=self._checksum(state)
                or type(state['version']) is not int or state['version']!=1 or type(state['owner']) is not dict
                or set(state['owner'])!=set(owner) or any(type(state['owner'][key]) is not type(value) or state['owner'][key]!=value for key,value in owner.items())
                or state['namespace']!=self.namespace or type(state['entries']) is not dict or len(state['entries'])>81
                or state['pending_seq'] is not None and type(state['pending_seq']) is not int):raise ValueError('journal owner')
            entries={};pending=[]
            for key,entry in state['entries'].items():
                seq=int(key)
                if str(seq)!=key or not 1<=seq<=81 or type(entry) is not dict or set(entry)!={'fingerprint','receipt','payload','expected_seq','event_max_seq','artifact_count'}:
                    raise ValueError('journal entry')
                if (type(entry['fingerprint']) is not str or re.fullmatch('[0-9a-f]{64}',entry['fingerprint']) is None
                    or any(type(entry[name]) is not int or entry[name]<0 for name in ('expected_seq','event_max_seq','artifact_count'))):raise ValueError('journal fingerprint')
                payload=entry['payload'];receipt=entry['receipt']
                if payload is None:
                    self._validate_receipt(receipt,owner,entry['expected_seq'],entry['artifact_count'])
                else:
                    if receipt is not None or type(payload) is not dict or set(payload)!={'sanitized','project_id','job_id','generation','now','events','artifacts','idempotency_key'}:
                        raise ValueError('journal payload')
                    if (payload['sanitized'] is not True or any(type(payload[name]) is not type(owner[name]) or payload[name]!=owner[name] for name in ('project_id','job_id','generation'))
                        or payload['idempotency_key']!=f"evidence-{owner['attempt_id']}-{self.namespace}-{seq}"
                        or type(payload['events']) is not list or type(payload['artifacts']) is not list
                        or len(payload['artifacts'])!=entry['artifact_count'] or datetime.fromisoformat(payload['now']).tzinfo is None):raise ValueError('journal payload owner')
                    if any(type(event) is not dict or type(event.get('local_seq')) is not int or event['local_seq']<1 for event in payload['events']):raise ValueError('journal events')
                    if entry['event_max_seq']!=max([0]+[event['local_seq'] for event in payload['events']]):raise ValueError('journal event cursor')
                    frozen=json.dumps({'events':payload['events'],'artifacts':payload['artifacts']},sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
                    if hashlib.sha256(frozen.encode('utf-8')).hexdigest()!=entry['fingerprint']:raise ValueError('journal payload hash')
                    pending.append(seq)
                entries[seq]=entry
            if (sorted(entries)!=list(range(1,len(entries)+1)) or len(pending)>1
                or state['pending_seq']!=(pending[0] if pending else None) or pending and pending[0]!=len(entries)):
                raise ValueError('journal prefix')
            last=0
            for seq in sorted(entries):
                entry=entries[seq]
                if entry['expected_seq']!=max(last,entry['event_max_seq']):raise ValueError('journal expected cursor')
                if entry['receipt'] is not None:last=max(last,entry['receipt']['contiguous_seq'])
            if type(state['last_seq']) is not int or state['last_seq']!=last:raise ValueError('journal cursor')
            self._entries=entries;self._pending_seq=state['pending_seq'];self._last_seq=last
        except (ValueError,TypeError,KeyError,AttributeError,OSError,RecursionError,WorkerHttpError):
            raise WorkerHttpError('invalid durable evidence journal',retry_class=RetryClass.fatal) from None

    @property
    def pending_sequence(self):
        return self._pending_seq

    def confirm_turn(self, action_seq):
        """Return this frozen turn's ACK, including one recovered by another owner-safe reader."""
        with self._lock, self._disk_lock():
            self._load()
            entry=self._entries.get(action_seq)
            if entry is None:raise WorkerHttpError('evidence turn missing',retry_class=RetryClass.fatal)
            if entry['receipt'] is not None:return copy.deepcopy(entry['receipt'])
            payload=entry['payload']
            return self._commit(action_seq,payload['events'],payload['artifacts'])

    def resume_pending(self):
        """Recover only the exact stored metadata packet, never a capture/model/device."""
        with self._lock, self._disk_lock():
            self._load()
            if self._pending_seq is None:return None
            seq=self._pending_seq;payload=self._entries[seq]['payload']
            return self._commit(seq,payload['events'],payload['artifacts'])
