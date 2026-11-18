"""Demand-driven Android continuous video, without model/device input calls."""
from __future__ import annotations
import base64,os,queue,struct,subprocess,threading,time
from dataclasses import replace
from uuid import UUID,uuid4
from aiqa.worker.http_client import WorkerHttpClient,WorkerHttpError
from aiqa.video.mp4 import starts_keyframe

MAX_BOX=2*1024*1024
HIDDEN=getattr(subprocess,'CREATE_NO_WINDOW',0)
AUD=b'\x00\x00\x00\x01\x09\xf0'

class VideoCaptureError(ValueError):pass

def read_exact(stream,size,*,eof=False):
    result=bytearray()
    while len(result)<size:
        part=stream.read(size-len(result))
        if not part:
            if eof and not result:return b''
            raise VideoCaptureError('truncated MP4 output')
        result.extend(part)
    return bytes(result)

def iter_mp4_segments(stream):
    init=b'';fragment=b'';started=False
    while True:
        header=read_exact(stream,8,eof=True)
        if not header:
            if init or fragment:raise VideoCaptureError('incomplete MP4 segment')
            return
        size,kind=struct.unpack('>I4s',header)
        if not 8<=size<=MAX_BOX:raise VideoCaptureError('MP4 box exceeds limit')
        packet=header+read_exact(stream,size-8)
        if not started:
            if kind==b'ftyp' and not init:init=packet
            elif kind==b'moov' and init:
                yield init+packet;init=b'';started=True
            else:raise VideoCaptureError('MP4 initialization missing')
        elif kind==b'moof' and not fragment:fragment=packet
        elif kind==b'mdat' and fragment:
            if len(fragment)+len(packet)>MAX_BOX:raise VideoCaptureError('MP4 fragment exceeds limit')
            yield fragment+packet;fragment=b''
        elif kind not in {b'mfra',b'free',b'sidx'}:raise VideoCaptureError('unexpected MP4 box')

def stop_remote_capture(adb,serial,session_id,*,run=subprocess.run):
    """SIGINT only encoders carrying this exact argv marker, then verify exit."""
    base=[str(adb),'-s',serial,'shell']
    marker='aiqa-video-'+session_id
    def call(args):return run(base+args,capture_output=True,timeout=4,creationflags=HIDDEN)
    try:
        for attempt in range(10):
            result=call(['ps','-A','-o','PID,ARGS'])
            if result.returncode:return False
            found=[]
            for line in result.stdout.decode('ascii',errors='ignore').splitlines():
                parts=line.split(None,2)
                if len(parts)<2 or parts[1]!=marker:continue
                pid=parts[0]
                if not pid.isdigit():return False
                command=call(['cat','/proc/'+pid+'/cmdline'])
                if command.returncode:return False
                if command.stdout.split(b'\0',1)[0]==marker.encode():found.append(pid)
            if not found:return True
            for pid in found:
                if call(['kill','-2',pid]).returncode:return False
            if attempt<9:time.sleep(.1)
    except (OSError,subprocess.SubprocessError):return False
    return False

class AndroidMp4Capture:
    def __init__(self,adb,serial,session_id):
        self.adb=str(adb);self.serial=serial;self.sid=str(UUID(session_id))
        self.stopping=threading.Event();self.output=queue.Queue(maxsize=32)
        self.raw=queue.Queue(maxsize=16);self.processes=[];self.threads=[];self.closed=False
        try:
            import imageio_ffmpeg
            ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
            # argv[0] is readable under Android's /proc policy and survives worker restart.
            script=f'exec -a aiqa-video-{self.sid} /system/bin/screenrecord --output-format=h264 --size 540x1200 --bit-rate 1200000 --time-limit 0 -'
            capture=subprocess.Popen([self.adb,'-s',serial,'exec-out','sh','-c',script],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
            self.processes.append(capture)
            mux=subprocess.Popen([ffmpeg,'-hide_banner','-loglevel','error','-probesize','32','-analyzeduration','0',
                '-fflags','+genpts','-use_wallclock_as_timestamps','1','-f','h264','-i','pipe:0','-c:v','copy','-an',
                '-movflags','frag_every_frame+empty_moov+default_base_moof','-flush_packets','1','-f','mp4','pipe:1'],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
            self.processes.append(mux)
            self._thread(lambda:self._read_raw(capture.stdout))
            self._thread(lambda:self._feed(mux.stdin))
            self._thread(lambda:self._read_mp4(mux.stdout))
        except Exception:
            self.close();raise VideoCaptureError('Android video capture is unavailable') from None

    def _thread(self,fn):
        t=threading.Thread(target=fn,daemon=True);self.threads.append(t);t.start()

    def _put(self,target,item):
        while not self.stopping.is_set():
            try:target.put(item,timeout=.2);return
            except queue.Full:continue

    def _read_raw(self,stream):
        try:
            while not self.stopping.is_set():
                chunk=os.read(stream.fileno(),65536)
                if not chunk:break
                self._put(self.raw,chunk)
        finally:self._put(self.raw,None)

    def _feed(self,stream):
        wrote=False
        try:
            while not self.stopping.is_set():
                try:chunk=self.raw.get(timeout=.04)
                except queue.Empty:
                    # Delimit a sparse native picture without inventing image content.
                    if wrote:stream.write(AUD);stream.flush();wrote=False
                    continue
                if chunk is None:break
                stream.write(chunk);stream.flush();wrote=True
            if wrote:stream.write(AUD)
        except (OSError,ValueError):pass
        finally:
            try:stream.close()
            except OSError:pass

    def _read_mp4(self,stream):
        try:
            for segment in iter_mp4_segments(stream):self._put(self.output,segment)
        except (VideoCaptureError,OSError) as exc:self._put(self.output,exc)
        finally:self._put(self.output,None)

    def next(self,timeout=.2):return self.output.get(timeout=timeout)

    def close(self):
        if self.closed:return True
        self.stopping.set()
        remote=stop_remote_capture(self.adb,self.serial,self.sid)
        for process in self.processes:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        for t in self.threads:t.join(timeout=1)
        self.closed=remote
        return remote

class AndroidVideoService:
    """Own one independent HTTP client/capture while the execution loop is busy."""
    def __init__(self,settings,binding):
        self.settings=replace(settings,timeout_seconds=min(settings.timeout_seconds,3))
        self.binding=binding;self.producer=str(uuid4());self.stopping=threading.Event()
        self.thread=None;self.capture=None;self.demand=None;self.sequence=0

    def start(self):
        self.thread=threading.Thread(target=self._run,name='android-live-video',daemon=True);self.thread.start()

    def close(self):
        self.stopping.set()
        if self.thread:self.thread.join(timeout=15)
        return self.thread is None or not self.thread.is_alive()

    def _request(self,client,operation,**payload):
        return client.video({'operation':operation,'producer_id':self.producer,**payload})

    def _close_capture(self,client):
        if not self.demand:return
        closed=self.capture.close() if self.capture else stop_remote_capture(self.binding.adb_path,self.binding.serial,self.demand['session_id'])
        if closed:
            self._request(client,'closed',session_id=self.demand['session_id'])
            self.capture=None;self.demand=None;self.sequence=0

    def _run(self):
        with WorkerHttpClient(self.settings) as client:
            last_poll=0;pending=None
            try:
                while not self.stopping.is_set():
                    try:
                        if time.monotonic()-last_poll>=1 or self.demand is None:
                            response=self._request(client,'poll',native_id=self.binding.serial);last_poll=time.monotonic()
                            for old in response.get('closing',[]):
                                if self.demand and old['session_id']==self.demand['session_id']:continue
                                if stop_remote_capture(self.binding.adb_path,self.binding.serial,old['session_id']):
                                    client.video({'operation':'closed',**old})
                            requested=response.get('session')
                            if not requested or requested['status'] not in {'pending','live'}:
                                pending=None;self._close_capture(client);self.stopping.wait(.2);continue
                            if self.demand is None:
                                pending=None;self.demand=requested;self.sequence=0
                                self.capture=AndroidMp4Capture(self.binding.adb_path,self.binding.serial,requested['session_id'])
                        if self.capture is None:continue
                        try:segment=pending if pending is not None else self.capture.next()
                        except queue.Empty:continue
                        pending=None
                        if segment is None or isinstance(segment,Exception):raise VideoCaptureError('capture ended')
                        # Init is separate; coalesce complete frame fragments for bounded HTTP traffic.
                        if self.sequence:
                            deadline=time.monotonic()+.15
                            while time.monotonic()<deadline:
                                try:extra=self.capture.next(timeout=.02)
                                except queue.Empty:continue
                                if extra is None or isinstance(extra,Exception):raise VideoCaptureError('capture ended')
                                if starts_keyframe(extra) or len(segment)+len(extra)>MAX_BOX:pending=extra;break
                                segment+=extra
                        encoded=base64.b64encode(segment).decode('ascii')
                        # Same sequence/body retries cannot duplicate video bytes.
                        for retry in range(2):
                            try:
                                self._request(client,'append',session_id=self.demand['session_id'],sequence=self.sequence,data=encoded);break
                            except WorkerHttpError:
                                if retry:raise
                        self.sequence+=1
                    except (WorkerHttpError,VideoCaptureError,OSError,ValueError,KeyError):
                        pending=None
                        if self.demand:
                            try:self._request(client,'failed',session_id=self.demand['session_id'])
                            except WorkerHttpError:pass
                            try:self._close_capture(client)
                            except WorkerHttpError:pass
                        self.stopping.wait(1)
            finally:
                try:self._close_capture(client)
                except (WorkerHttpError,OSError):
                    if self.capture:self.capture.close()
