"""Parent-owned bounded I/O for the actual pinned Mobile-Agent child process.

Callbacks are existing bounded worker ports. Deadline stops new sends; in-flight I/O drains.
"""
from __future__ import annotations
import base64,json,math,os,re,subprocess,sys,threading,time
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path,PurePosixPath
from queue import Queue,Empty,Full
from aiqa.adapters.mobile_agent_upstream import COMMIT,load_protocol,render_reply,upstream_action
from aiqa.security.redaction import filter_capture
from aiqa.contracts.actions import CaptureGeometry
from aiqa.worker.mobile_agent_ipc import read_packet,write_packet


@dataclass(frozen=True,slots=True)
class MobileAgentModelFrame:
    """Validated pixels and identifiers only; no raw capture text or reasoning."""
    observation_id:str
    captured_at:str
    geometry:CaptureGeometry
    png:bytes
    platform:str


@dataclass(frozen=True,slots=True)
class MobileAgentProcessResult:
    status:str
    reason:str
    model_requests:int
    native_actions:int
    ambiguous_dispatch:bool
    receipt:dict|None=None
    cleanup_failed:bool=False


class _Stop(Exception):pass


def _path_key(value,max_steps):
    if type(value) is not str or len(value)>256:raise _Stop('capture_path')
    parts=PurePosixPath(value.replace('\\','/')).parts
    if (len(parts)!=2 or len(parts[0])!=80 or re.fullmatch(r'AIQA_[0-9a-f]{32}_+',parts[0]) is None
        or re.fullmatch(r'screenshot_[0-9]{1,2}\.png',parts[1]) is None):raise _Stop('capture_path')
    if int(parts[1][11:-4])>=max_steps:raise _Stop('capture_path')
    return '/'.join(parts)


def run_mobile_agent_process(*,output,instruction,capture,model,dispatch,secrets,allowed=lambda:True,
                             max_steps=10,max_actions=50,timeout_seconds=240):
    if (type(secrets) is not tuple or any(type(value) is not str or not value for value in secrets)
        or type(instruction) is not str or not instruction.strip() or len(instruction.encode('utf-8'))>16000
        or type(max_steps) is not int or not 1<=max_steps<=80 or type(max_actions) is not int or not 1<=max_actions<=50
        or type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not 0<timeout_seconds<=3600):
        raise ValueError('Mobile-Agent process limits invalid')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    (output/'.aiqa-mobile-agent').write_text('mobile-agent-ipc-v1',encoding='ascii')
    protocol=load_protocol();deadline=time.monotonic()+timeout_seconds
    model_count=native_count=0;native_started=False;receipt=None
    frames=OrderedDict();history=[];last_path=None;before=None;pending=None;terminal=None
    phase='capture';capture_tag=None;capture_index=0
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP'}}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]),PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
    process=subprocess.Popen([sys.executable,'-B','-m','aiqa.worker.mobile_agent_child'],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,cwd=output,shell=False,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    queue=Queue(maxsize=1);writes=Queue(maxsize=1);stop=threading.Event();stderr=bytearray()
    def emit(value):
        while not stop.is_set():
            try:queue.put(value,timeout=.1);return
            except Full:pass
    def reader():
        try:
            while not stop.is_set():emit(read_packet(process.stdout))
        except Exception:emit(None)
    def errors():
        try:
            while chunk:=process.stderr.read1(8192):
                if len(stderr)<16384:stderr.extend(chunk[:16384-len(stderr)])
        except OSError:pass
    def writer():
        while not stop.is_set():
            try:packet,done,failed=writes.get(timeout=.1)
            except Empty:continue
            try:write_packet(process.stdin,packet)
            except Exception:failed.append(True)
            finally:done.set()
    readers=[threading.Thread(target=reader,daemon=True),threading.Thread(target=errors,daemon=True),
             threading.Thread(target=writer,daemon=True)]
    for thread in readers:thread.start()
    def fence():
        if time.monotonic()>=deadline:raise _Stop('deadline')
        if allowed() is not True:raise _Stop('cancelled')
    def send(packet):
        fence()
        done=threading.Event();failed=[]
        writes.put_nowait((packet,done,failed))
        while not done.wait(.05):fence()
        if failed:raise _Stop('ipc_write_failed')
        fence()
    def result(status,reason):return MobileAgentProcessResult(status,reason,model_count,native_count,native_started,receipt)
    try:
        send({'v':1,'op':'init','root':str(output),'instruction':instruction,'max_steps':max_steps})
        sequence=0
        while True:
            fence()
            try:packet=queue.get(timeout=min(.1,max(.001,deadline-time.monotonic())))
            except Empty:continue
            if packet is None:raise _Stop('child_closed')
            sequence+=1
            if (set(packet)!={'v','id','op','payload'} or packet['v']!=1 or type(packet['id']) is not int
                or packet['id']!=sequence or type(packet['payload']) is not dict):raise _Stop('ipc_invalid')
            op,data=packet['op'],packet['payload'];reply={}
            if op=='capture':
                if set(data)!={'path'} or phase!='capture' or pending is not None:raise _Stop('capture_order')
                key=_path_key(data['path'],max_steps)
                tag,filename=key.split('/')
                if (key in frames or len(history)>=max_steps or (capture_tag is not None and tag!=capture_tag)
                    or filename!=f'screenshot_{capture_index}.png'):raise _Stop('capture_order')
                current=capture();safe=filter_capture(current, secrets)
                if len(current.png)>2_000_000:raise _Stop('image_size')
                fence();before=current;last_path=data['path'];capture_tag=tag;capture_index+=1;phase='model'
                frames[key]=MobileAgentModelFrame(current.observation_id,current.captured_at,current.geometry,safe.png,current.platform)
                while len(frames)>5:frames.popitem(last=False)
                reply={'png':base64.b64encode(current.png).decode('ascii')}
            elif op=='model':
                if set(data)!={'messages'} or phase!='model' or before is None or pending is not None or terminal is not None:raise _Stop('model_order')
                if model_count>=max_steps:raise _Stop('model_limit')
                tag=last_path.replace('\\','/').split('/')[0]
                expected=protocol.build_messages(last_path,tag+' ('+instruction+')',history,'gpt-6-luna')
                if data['messages']!=expected:raise _Stop('model_context')
                images={}
                for message in expected:
                    for part in message['content']:
                        if 'image' in part:
                            ref=part['image'];key=_path_key(ref[7:],max_steps)
                            if key not in frames:raise _Stop('model_image')
                            images[ref]=frames[key]
                marked=[False]
                def model_boundary():
                    nonlocal model_count
                    fence()
                    if marked[0]:raise _Stop('duplicate_model_boundary')
                    marked[0]=True;model_count+=1
                content=model({'messages':deepcopy(expected),'images':images,'current':frames[_path_key(last_path,max_steps)]},before_send=model_boundary)
                if not marked[0]:raise _Stop('model_boundary_missing')
                fence()
                if type(content) is not str or len(content.encode('utf-8'))>16384:raise _Stop('model_response')
                rendered=render_reply(content)
                if rendered.count('<tool_call>')!=1 or rendered.count('</tool_call>')!=1:raise _Stop('model_response')
                raw=protocol.parse_action(rendered);action=upstream_action(protocol,raw,before.geometry)
                if action is not None and action.kind=='finish':terminal=raw['arguments']['status'];phase='done'
                else:
                    history.append({'output':rendered,'image':last_path});phase='capture'
                    if action is not None:
                        scaled=deepcopy(raw['arguments']);rh,rw=protocol.smart_resize(before.geometry.physical_height,before.geometry.physical_width,factor=16,min_pixels=3136,max_pixels=1003520*200)
                        protocol.rescale_coordinates(scaled,rw,rh)
                        name=scaled['action'];method={'click':'click','long_press':'long_press','swipe':'slide','scroll':'slide','type':'type','system_button':'back'}[name]
                        args=[]
                        if 'coordinate' in scaled:args.extend(scaled['coordinate'])
                        if 'coordinate2' in scaled:args.extend(scaled['coordinate2'])
                        if name=='type':args.append(scaled['text'])
                        pending=(action,method,args);phase='native'
                reply={'content':rendered}
            elif op=='native':
                if set(data)!={'method','args'} or phase!='native' or pending is None:raise _Stop('native_order')
                action,method,args=pending
                if (data['method']!=method or data['args']!=args or type(data['args']) is not list
                    or [type(v) for v in data['args']]!=[type(v) for v in args]):raise _Stop('native_differs')
                if native_count>=max_actions:raise _Stop('action_limit')
                def native_boundary():
                    nonlocal native_started
                    fence()
                    if native_started:raise _Stop('duplicate_native_boundary')
                    native_started=True
                ack=dispatch(action,before,before_send=native_boundary)
                if not native_started:raise _Stop('native_boundary_missing')
                if getattr(ack,'native_calls',None)!=1 or getattr(ack,'outcome',None)!='acknowledged':raise _Stop('native_unacknowledged')
                native_count+=1;native_started=False;pending=None;phase='capture';reply={'acknowledged':True}
            elif op=='done':
                if (phase!='done' and not (phase=='capture' and model_count==max_steps)) or pending is not None or data.get('main_invocations')!=1 or data.get('upstream_commit')!=COMMIT:raise _Stop('child_receipt')
                receipt=data
                send({'v':1,'id':sequence,'ok':True,'result':{}})
                process.wait(timeout=2)
                if process.returncode!=0:raise _Stop('child_exit')
                if terminal=='success':return result('claimed_success','completed')
                return result('stopped','claimed_failure' if terminal=='failure' else 'step_limit')
            elif op=='error':raise _Stop('child_error')
            else:raise _Stop('ipc_operation')
            fence();send({'v':1,'id':sequence,'ok':True,'result':reply})
    except _Stop as exc:return result('stopped',str(exc))
    except Exception:return result('stopped','callback_or_ipc_failed')
    finally:
        stop.set()
        cleanup_failed=False
        try:
            if process.poll() is None:process.kill()
            process.wait(timeout=2)
        except Exception:cleanup_failed=True
        for thread in readers:
            try:
                thread.join(timeout=.5)
                if thread.is_alive():cleanup_failed=True
            except Exception:cleanup_failed=True
        try:alive=process.poll() is None
        except Exception:alive=True
        # A surviving child can hold pipe locks: do not block forever closing its streams.
        if alive:cleanup_failed=True
        else:
            for stream in (process.stdin,process.stdout,process.stderr):
                try:stream.close()
                except Exception:cleanup_failed=True
        try:(output/'child-stderr.log').write_bytes(stderr)
        except OSError:pass  # Diagnostics must never erase an ACK/ambiguous dispatch result.
        if cleanup_failed:
            return MobileAgentProcessResult('stopped','child_cleanup_failed',model_count,native_count,native_started,receipt,True)
