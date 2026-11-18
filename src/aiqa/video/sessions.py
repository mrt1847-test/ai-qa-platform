"""Bounded, actor-scoped fragmented MP4 buffers. No device or file I/O."""
from __future__ import annotations

from dataclasses import dataclass,field
import struct
import threading
import time
from uuid import uuid4
from aiqa.video.mp4 import starts_keyframe

class VideoMissing(ValueError):pass
class VideoConflict(ValueError):pass
class VideoInvalid(ValueError):pass

ACTIVE={'pending','live'}
MAX_SEGMENT=2*1024*1024

def boxes(data:bytes):
    """Validate complete bounded ISO BMFF boxes, without decoding their payloads."""
    offset=0;result=[]
    while offset<len(data):
        if len(data)-offset<8:raise VideoInvalid('incomplete MP4 box')
        size,kind=struct.unpack_from('>I4s',data,offset)
        if size<8 or size>MAX_SEGMENT or offset+size>len(data):raise VideoInvalid('invalid MP4 box size')
        result.append(kind);offset+=size
    return result

@dataclass
class Session:
    session_id:str
    project:str
    resource:str
    actor:str
    worker:str
    native:str
    created:float
    lease_until:float
    status:str='pending'
    reason:str='waiting_for_worker'
    producer:str=''
    producer_closed:bool=False
    published:float=0
    ended:float|None=None
    codec:str=''
    size:int=0
    segments:list[bytes]=field(default_factory=list)
    first_sequence:int=1
    next_sequence:int=0

class VideoSessions:
    def __init__(self,*,clock=time.monotonic,max_bytes=16*1024*1024,max_sessions=3):
        self.clock=clock;self.max_bytes=max_bytes;self.max_sessions=max_sessions
        self.lock=threading.RLock();self.sessions:dict[str,Session]={}

    def _end(self,s,status='stopped',reason='viewer_disconnected',*,purge=True):
        s.status=status;s.reason=reason
        if s.ended is None:s.ended=self.clock()
        if purge:s.segments.clear();s.size=0

    def _gc(self):
        now=self.clock()
        for sid,s in list(self.sessions.items()):
            if s.status in ACTIVE:
                if now-s.created>=600:self._end(s,reason='duration_limit')
                elif now>=s.lease_until:self._end(s)
                elif s.producer and now-s.published>15:self._end(s,'error','publisher_disconnected')
            if s.ended is not None and now-s.ended>300:
                s.segments.clear();s.size=0
                # An unacknowledged producer remains a stop fence, even after pixels expire.
                if not s.producer or s.producer_closed:del self.sessions[sid]

    def _get(self,sid,project=None,actor=None):
        self._gc();s=self.sessions.get(sid)
        if s is None or project is not None and s.project!=project or actor is not None and s.actor!=actor:
            raise VideoMissing('video session was not found')
        if s.ended is not None and self.clock()-s.ended>300:raise VideoMissing('video session expired')
        return s

    def create(self,project,resource,actor,worker,native):
        with self.lock:
            self._gc()
            for s in self.sessions.values():
                if s.worker==worker and s.native==native and s.producer and not s.producer_closed and s.status not in ACTIVE:
                    raise VideoConflict('previous video publisher is still stopping')
                if s.worker==worker and s.native==native and s.status in ACTIVE:
                    if (s.project,s.actor,s.resource)==(project,actor,resource):return self.describe(s)
                    raise VideoConflict('device video is already in use')
            if sum(s.status in ACTIVE or bool(s.producer and not s.producer_closed) for s in self.sessions.values())>=self.max_sessions:
                raise VideoConflict('video capacity reached')
            now=self.clock();sid=str(uuid4());s=Session(sid,project,resource,actor,worker,native,now,now+20)
            self.sessions[sid]=s;return self.describe(s)

    def describe(self,s):
        return {'session_id':s.session_id,'resource_id':s.resource,'status':s.status,'reason':s.reason,
                'codec':s.codec,'bytes':s.size,'next_sequence':s.next_sequence,'max_seconds':600}

    def claim(self,worker,native,producer,*,projects=None):
        with self.lock:
            self._gc()
            # First tell a previous publisher to close; never create a second capture pipeline.
            for s in self.sessions.values():
                if projects is not None and s.project not in projects:continue
                if s.worker==worker and s.native==native and s.producer==producer and not s.producer_closed:
                    if s.status in ACTIVE:s.published=self.clock()
                    return self.describe(s)
            for s in self.sessions.values():
                if projects is not None and s.project not in projects:continue
                if s.worker==worker and s.native==native and s.status in ACTIVE and not s.producer:
                    s.producer=producer;s.published=self.clock();return self.describe(s)
            return None

    def append(self,sid,producer,sequence,data):
        with self.lock:
            s=self._get(sid)
            if s.producer!=producer or s.producer_closed or s.status not in ACTIVE:raise VideoConflict('video publisher stopped')
            if type(sequence) is not int or sequence<0 or sequence>s.next_sequence:raise VideoConflict('video sequence changed')
            if type(data) is not bytes or not data or len(data)>MAX_SEGMENT:raise VideoInvalid('video segment exceeds limit')
            if sequence<s.next_sequence:
                index=0 if sequence==0 else sequence-s.first_sequence+1
                if sequence and sequence<s.first_sequence or index>=len(s.segments) or s.segments[index]!=data:
                    raise VideoConflict('video sequence body changed')
                return self.describe(s)
            kinds=boxes(data)
            if sequence==0:
                marker=data.find(b'avcC')
                if kinds!=[b'ftyp',b'moov'] or marker<0 or len(data)<marker+8 or data[marker+4]!=1:
                    raise VideoInvalid('AVC MP4 initialization required')
                s.codec='avc1.'+data[marker+5:marker+8].hex()
            elif not kinds or len(kinds)%2 or any(kinds[n:n+2]!=[b'moof',b'mdat'] for n in range(0,len(kinds),2)):
                raise VideoInvalid('complete MP4 fragments required')
            # Only the latest decodable GOP is a transport buffer, never a session recording.
            if sequence and starts_keyframe(data):
                s.segments=s.segments[:1];s.size=sum(map(len,s.segments));s.first_sequence=sequence
            if s.size+len(data)>self.max_bytes:
                self._end(s,'error','capacity_limit');raise VideoConflict('video capacity reached')
            s.segments.append(data);s.size+=len(data);s.next_sequence+=1
            s.status='live' if sequence else 'pending';s.reason='';s.published=self.clock()
            return self.describe(s)

    def read(self,sid,project,actor,after):
        with self.lock:
            s=self._get(sid,project,actor)
            if type(after) is not int or after<0:raise VideoInvalid('invalid video cursor')
            if not s.segments or s.status not in ACTIVE:return {**self.describe(s),'segments':[],'next_sequence':after,'reset':False}
            reset=after==0 or after<s.first_sequence
            selected=[s.segments[0]] if reset else [];size=sum(map(len,selected))
            cursor=s.first_sequence if reset else after
            for segment in s.segments[max(1,cursor-s.first_sequence+1):]:
                if selected and size+len(segment)>512*1024:break
                selected.append(segment);size+=len(segment);cursor+=1
            return {**self.describe(s),'segments':selected,'next_sequence':cursor,'reset':reset}

    def keepalive(self,sid,project,actor):
        with self.lock:
            s=self._get(sid,project,actor)
            if s.status in ACTIVE:s.lease_until=self.clock()+20
            return self.describe(s)

    def stop(self,sid,project,actor):
        with self.lock:
            s=self._get(sid,project,actor);self._end(s,reason='viewer_stopped');return self.describe(s)

    def fail(self,sid,producer,reason):
        with self.lock:
            s=self._get(sid)
            if s.producer!=producer:raise VideoConflict('different video publisher')
            if s.status not in ACTIVE:return self.describe(s)
            self._end(s,'error',reason);return self.describe(s)

    def ack_stop(self,sid,producer):
        with self.lock:
            s=self.sessions.get(sid)
            if s is None or s.producer!=producer:raise VideoConflict('different video publisher')
            if s.status in ACTIVE:self._end(s,reason='publisher_stopped')
            s.producer_closed=True

    def fence(self,native,project,*,sensitive,worker=None):
        """Close incompatible captures and wait for their owned processes to stop."""
        with self.lock:
            self._gc();ready=True
            for s in self.sessions.values():
                if worker is not None and s.worker!=worker:continue
                if s.native!=native or not (sensitive or s.project!=project):continue
                self._end(s,'blocked','sensitive_or_foreign_job',purge=True)
                if s.producer and not s.producer_closed:ready=False
            return ready
