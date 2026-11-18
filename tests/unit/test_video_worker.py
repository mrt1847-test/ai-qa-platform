from io import BytesIO
import struct,subprocess
import pytest
from video_support import INIT,FRAME,box

def test_stream_parser_preserves_real_mp4_init_and_fragment_boundaries():
    from aiqa.worker.video import iter_mp4_segments
    class ShortReads(BytesIO):
        def read(self,n=-1):return super().read(min(n,3))
    assert list(iter_mp4_segments(ShortReads(INIT+FRAME+box(b'mfra'))))==[INIT,FRAME]

@pytest.mark.parametrize('data',[b'\0\0\0',struct.pack('>I4s',3,b'moov'),struct.pack('>I4s',3_000_000,b'mdat'),INIT+FRAME[:-2]])
def test_stream_parser_rejects_truncation_and_unbounded_boxes(data):
    from aiqa.worker.video import iter_mp4_segments,VideoCaptureError
    with pytest.raises(VideoCaptureError):list(iter_mp4_segments(BytesIO(data)))

def test_remote_stop_matches_the_owned_encoder_environment_before_killing():
    from aiqa.worker.video import stop_remote_capture
    calls=[];alive=[True]
    def run(argv,**kwargs):
        calls.append(argv)
        if 'ps' in argv:return subprocess.CompletedProcess(argv,0,b'PID ARGS\n71 aiqa-video-other --size\n'+(b'72 aiqa-video-owned --size\n' if alive[0] else b''),b'')
        if '/proc/72/cmdline' in argv:return subprocess.CompletedProcess(argv,0,b'aiqa-video-owned\0--size\0',b'')
        if 'kill' in argv:alive[0]=False;return subprocess.CompletedProcess(argv,0,b'',b'')
        raise AssertionError(argv)
    assert stop_remote_capture('adb','serial','owned',run=run)
    killed=[a for a in calls if 'kill' in a]
    assert len(killed)==1 and killed[0][-1]=='72'

def test_unverifiable_encoder_stop_does_not_acknowledge_a_safe_shutdown():
    from aiqa.worker.video import stop_remote_capture
    def run(argv,**kwargs):
        if 'ps' in argv:return subprocess.CompletedProcess(argv,0,b'PID ARGS\n71 aiqa-video-owned --size\n',b'')
        return subprocess.CompletedProcess(argv,1,b'',b'permission denied')
    assert not stop_remote_capture('adb','serial','owned',run=run)


def test_reconnect_discards_a_previous_captures_pending_keyframe(monkeypatch):
    import base64,queue,threading
    from types import SimpleNamespace
    from uuid import uuid4
    import aiqa.worker.video as v
    clock=[10.0];polls=[0];sent=[];first=str(uuid4());second=str(uuid4())
    monkeypatch.setattr(v.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(v,'starts_keyframe',lambda b:b==b'KEY')
    class Capture:
        def __init__(self,adb,serial,sid):self.items=[b'INIT',b'DELTA',b'KEY'] if sid==first else [b'NEW_INIT']
        def next(self,timeout=.2):
            if self.items:return self.items.pop(0)
            raise queue.Empty
        def close(self):return True
    class Client:
        def __init__(self,*a):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def video(self,p):
            if p['operation']=='poll':
                polls[0]+=1
                return {'session':None if polls[0]==2 else {'session_id':first if polls[0]==1 else second,'status':'pending'}}
            if p['operation']=='append':
                data=base64.b64decode(p['data']);sent.append((p['session_id'],p['sequence'],data))
                if data==b'DELTA':clock[0]=12.0
                if p['session_id']==second:service.stopping.set()
            return {}
    monkeypatch.setattr(v,'WorkerHttpClient',Client);monkeypatch.setattr(v,'AndroidMp4Capture',Capture)
    service=v.AndroidVideoService.__new__(v.AndroidVideoService)
    service.settings=None;service.binding=SimpleNamespace(serial='device',adb_path='adb');service.producer=str(uuid4())
    service.stopping=threading.Event();service.capture=service.demand=None;service.sequence=0
    service._run()
    assert sent==[(first,0,b'INIT'),(first,1,b'DELTA'),(second,0,b'NEW_INIT')]
