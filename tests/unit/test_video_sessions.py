import struct
import pytest
from video_support import INIT,FRAME,DELTA

def box(kind, body=b''):
    return struct.pack('>I4s',len(body)+8,kind)+body


@pytest.fixture
def video():
    from aiqa.video.sessions import VideoSessions
    clock=[0.0]
    return VideoSessions(clock=lambda:clock[0]),clock

def start(store,actor='a',project='p',resource='r',worker='w',native='device'):
    return store.create(project,resource,actor,worker,native)['session_id']

def test_real_stream_bytes_are_ordered_for_live_playback(video):
    s,_=video;i=start(s)
    assert s.claim('w','device','producer')['session_id']==i
    s.append(i,'producer',0,INIT);s.append(i,'producer',1,FRAME)
    read=s.read(i,'p','a',0)
    assert read['segments']==[INIT,FRAME] and read['next_sequence']==2
    assert read['codec']=='avc1.42c01e' and read['status']=='live'

def test_duplicate_is_idempotent_but_reordered_or_changed_bytes_fail(video):
    from aiqa.video.sessions import VideoConflict
    s,_=video;i=start(s);s.claim('w','device','producer')
    s.append(i,'producer',0,INIT);s.append(i,'producer',0,INIT)
    with pytest.raises(VideoConflict):s.append(i,'producer',0,FRAME)
    with pytest.raises(VideoConflict):s.append(i,'producer',2,FRAME)
    assert len(s.read(i,'p','a',0)['segments'])==1

def test_project_actor_and_publisher_cannot_take_over(video):
    from aiqa.video.sessions import VideoMissing,VideoConflict
    s,_=video;i=start(s);s.claim('w','device','one')
    assert s.claim('other-worker','device','two') is None
    assert s.claim('w','device','two') is None
    with pytest.raises(VideoMissing):s.read(i,'foreign','a',0)
    with pytest.raises(VideoMissing):s.read(i,'p','foreign',0)
    with pytest.raises(VideoConflict):s.append(i,'two',0,INIT)

def test_viewer_expiry_stops_capture_and_discards_pixels(video):
    from aiqa.video.sessions import VideoConflict,VideoMissing
    s,c=video;i=start(s);s.claim('w','device','one');s.append(i,'one',0,INIT)
    c[0]=21
    assert s.read(i,'p','a',0)['status']=='stopped'
    with pytest.raises(VideoConflict):s.append(i,'one',1,FRAME)
    assert s.read(i,'p','a',0)['segments']==[]
    c[0]=322
    with pytest.raises(VideoMissing):s.read(i,'p','a',0)

def test_keepalive_does_not_extend_hard_duration(video):
    s,c=video;i=start(s)
    for t in range(1,601,10):c[0]=t;s.keepalive(i,'p','a')
    c[0]=601
    assert s.read(i,'p','a',0)['status']=='stopped'

def test_capacity_and_invalid_mp4_are_bounded(video):
    from aiqa.video.sessions import VideoConflict,VideoInvalid,VideoSessions
    s=VideoSessions(max_bytes=len(INIT)+len(FRAME)-1);i=start(s);s.claim('w','device','one')
    with pytest.raises(VideoInvalid):s.append(i,'one',0,b'not a video')
    s.append(i,'one',0,INIT)
    with pytest.raises(VideoConflict):s.append(i,'one',1,FRAME)
    assert s.read(i,'p','a',0)['status']=='error'
    for n in range(3):
        try:start(s,resource=str(n),native=str(n))
        except VideoConflict:break
    with pytest.raises(VideoConflict):start(s,resource='last',native='last')

def test_sensitive_or_foreign_job_fence_purges_pixels_and_requires_stop_ack(video):
    s,_=video;i=start(s);s.claim('w','device','one');s.append(i,'one',0,INIT)
    assert not s.fence('device','p',sensitive=True)
    assert s.read(i,'p','a',0)['segments']==[]
    assert s.read(i,'p','a',0)['status']=='blocked'
    s.ack_stop(i,'one')
    assert s.fence('device','p',sensitive=True)
    j=start(s,resource='r2',native='second');s.claim('w','second','two')
    assert not s.fence('second','other-project',sensitive=False)
    s.ack_stop(j,'two');assert s.fence('second','other-project',sensitive=False)

def test_same_project_non_sensitive_execution_can_be_watched(video):
    s,_=video;i=start(s);s.claim('w','device','one')
    assert s.fence('device','p',sensitive=False)
    s.append(i,'one',0,INIT)
    assert start(s)==i

def test_publisher_loss_is_not_labelled_live(video):
    s,c=video;i=start(s);s.claim('w','device','one');s.append(i,'one',0,INIT)
    c[0]=14;s.keepalive(i,'p','a')
    c[0]=16
    assert s.read(i,'p','a',0)['status']=='error'
    assert s.read(i,'p','a',0)['reason']=='publisher_disconnected'

def test_live_buffer_discards_previous_gop_instead_of_recording_a_session(video):
    s,_=video;i=start(s);s.claim('w','device','one')
    for n,data in enumerate([INIT,FRAME,DELTA,FRAME]):s.append(i,'one',n,data)
    result=s.read(i,'p','a',0)
    assert result['segments']==[INIT,FRAME]
    assert result['reset'] is True and result['next_sequence']==4
    assert result['bytes']==len(INIT)+len(FRAME)
    assert s.read(i,'p','a',4)['segments']==[]
    s.stop(i,'p','a')
    assert s.read(i,'p','a',0)['segments']==[]


def test_foreign_project_poll_cannot_claim_an_authorized_workers_other_project(video):
    s,_=video;i=start(s,project='other')
    assert s.claim('w','device','foreign',projects={'p'}) is None
    assert s.sessions[i].producer==''
    assert s.claim('w','device','owner',projects={'other'})['session_id']==i


def test_identical_android_serials_on_other_pcs_are_independent(video):
    s,_=video;i=start(s,worker='pc-a');s.claim('pc-a','device','one')
    assert s.fence('device','foreign',sensitive=True,worker='pc-b')
    assert s.sessions[i].status=='pending'


def test_a_late_publish_failure_cannot_replace_the_viewers_stop_reason(video):
    s,_=video;i=start(s);s.claim('w','device','one');s.stop(i,'p','a')
    result=s.fail(i,'one','capture_unavailable')
    assert result['status']=='stopped' and result['reason']=='viewer_stopped'
