"""Durable evidence around actual upstream Mobile-Agent I/O; model claims never approve."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
import base64,hashlib,json,os,re,time
from pathlib import Path
from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter
from aiqa.adapters.mobile_agent_upstream import upstream_action,render_reply
from aiqa.replay.android_native_trace import native_event
from aiqa.recording.mobile_agent_frames import require_guarded_frame
from aiqa.worker.recording_reasoning import require_evaluation_action,require_current_frame


def persist(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    temporary=path.with_name(path.name+'.tmp')
    with temporary.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)


def conversation(messages,root,image_output=None):
    result=[];root=Path(root).resolve()
    for message in messages:
        content=[]
        for item in message['content']:
            if set(item)=={'text'}:content.append({'type':'output_text' if message['role']=='assistant' else 'input_text','text':item['text']})
            elif set(item)=={'image'}:
                name=item['image']
                if type(name) is not str or not name.startswith('file://'):raise ValueError('upstream image invalid')
                path=Path(name[7:]).resolve()
                if not path.is_relative_to(root) or path.stat().st_size>2_000_000:raise ValueError('upstream image outside evidence')
                raw=path.read_bytes()
                from PIL import Image
                from io import BytesIO
                encoded=BytesIO()
                with Image.open(BytesIO(raw)) as image:
                    image.convert('RGB').resize((1000,1000),Image.Resampling.LANCZOS).save(encoded,format='PNG')
                raw=encoded.getvalue()
                if image_output is not None:persist(Path(image_output)/(hashlib.sha256(raw).hexdigest()+'.png'),raw)
                content.append({'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(raw).decode('ascii'),'detail':'high'})
            else:raise ValueError('upstream content unsupported')
        result.append({'role':message['role'],'content':content,**({'phase':'final_answer'} if message['role']=='assistant' else {})})
    return tuple(result)


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate action field')
        result[key]=value
    return result


class ObservedMobileSession:
    def __init__(self,*,upstream,capture,driver,output,package,complete,deadline=None):
        self.upstream,self.capture,self.driver=upstream,capture,driver
        self.output=Path(output).resolve();self.output.mkdir(parents=True,exist_ok=False)
        self.package,self.complete=package,complete
        self.started=time.monotonic()
        self.deadline=deadline if deadline is not None else self.started+240
        self.adapter=MobileAgentAndroidAdapter();self.source=[];self.before=None;self.pending=None;self.previous=None
        self.report={'engine':'actual_mobile_agent_v3.5','model_requested':'gpt-6-luna','reasoning_effort':'low',
                     'status':'recording','human_review':'pending','product_approval':False,'model_calls':[],
                     'steps':[],'replay_model_calls':None}
        self.flush()

    def fence(self):
        if time.monotonic()>=self.deadline:raise RuntimeError('recording send deadline exceeded')

    def flush(self):
        self.report['elapsed_seconds']=round(time.monotonic()-self.started,3)
        persist(self.output/'report.json',self.report)

    def get_screenshot(self,path):
        self.fence();self.before,self.foreground=self.capture();self.before=self.adapter.sanitize(self.before)
        self.fence();self.before_path=Path(path).resolve()
        persist(self.before_path,self.before.png)
        return True

    def predict(self,messages):
        if self.before is None:raise RuntimeError('upstream screenshot missing')
        self.fence()
        if self.foreground not in {self.package,'com.google.android.permissioncontroller'}:raise ValueError('model foreground outside evaluation')
        index=len(self.report['model_calls'])+1
        if index>10:raise RuntimeError('recording call cap')
        persist(self.output/f'model-{index:03d}-messages.json',messages)
        started=time.monotonic()
        result=self.complete(conversation(messages,Path.cwd(),self.output/'model-images'))
        self.report['model_calls'].append({k:getattr(result,k) for k in ('content','actual_model','input_tokens','output_tokens','reasoning_tokens','cached_input_tokens','provider_request_id')})
        self.report['model_calls'][-1]['latency_seconds']=round(time.monotonic()-started,3)
        self.flush()
        if result.actual_model!='gpt-6-luna':raise ValueError('unexpected recording model')
        text=render_reply(result.content)
        self.fence();blocks=re.findall(r'<tool_call>\s*(.*?)\s*</tool_call>',text,flags=re.S)
        if len(blocks)!=1:raise ValueError('one upstream tool required')
        raw=json.loads(blocks[0],object_pairs_hook=_object)
        # Both original parser and strict validation must agree; no alternate action parser.
        if self.upstream.parse_action(text)!=raw:raise ValueError('upstream parser differs')
        self.pending=upstream_action(self.upstream,raw,self.before.geometry)
        self.scaled=deepcopy(raw['arguments'])
        rh,rw=self.upstream.smart_resize(self.before.geometry.physical_height,self.before.geometry.physical_width,factor=16,min_pixels=3136,max_pixels=1003520*200)
        self.upstream.rescale_coordinates(self.scaled,rw,rh)
        if self.pending is not None and self.pending.kind=='finish':
            self.report['status']='model_claimed_'+raw['arguments']['status']
            persist(self.output/'terminal.png',self.before.png);self.flush()
        elif self.pending is not None:
            require_evaluation_action(self.pending,foreground=self.foreground,package=self.package)
            if self.pending==self.previous:raise ValueError('identical consecutive native action')
        return text

    def _send(self,name,values):
        if self.pending is None or self.pending.kind=='finish' or self.scaled['action']!=name:raise ValueError('upstream dispatch differs')
        keys={'click':('coordinate',),'long_press':('coordinate',),'swipe':('coordinate','coordinate2'),'scroll':('coordinate','coordinate2'),'type':('text',),'system_button':('button',)}[name]
        expected=[]
        for key in keys:
            value=self.scaled[key];expected.extend(value if isinstance(value,list) else [value])
        if tuple(expected)!=tuple(values):raise ValueError('upstream dispatch coordinates differ')
        action=self.pending;index=len(self.source)+1;stem=f'step-{index:03d}'
        persist(self.output/(stem+'-before.png'),self.before.png)
        persist(self.output/(stem+'-before.xml'),self.before.dom.encode('utf-8'))
        event=native_event(action,self.before,action_id=stem,line=index)
        row={'step':index,'state':'planned','upstream_action':self.scaled,'native':asdict(action),'source_event':event,
             'before_image':stem+'-before.png','before_geometry':asdict(self.before.geometry),'foreground':self.foreground}
        self.report['steps'].append(row);self.flush()
        def fence():
            self.fence();now,foreground=self.capture()
            require_current_frame(self.before,now,expected_foreground=self.foreground,current_foreground=foreground)
            require_evaluation_action(action,foreground=foreground,package=self.package)
            try:row['frame_guard']=require_guarded_frame(self.before.png,now.png,action,self.before.dom,now.dom)
            except ValueError:
                persist(self.output/(stem+'-drift-current.png'),now.png)
                raise
            self.fence();row['state']='dispatch_started';self.flush();self.fence()
        result=self.adapter._dispatch(self.driver,self.before,self.before,action,before_native_send=fence)
        if result.native_calls!=1 or result.outcome!='acknowledged':raise RuntimeError('native dispatch unacknowledged')
        self.source.append(event);row.update(state='acknowledged_after_missing',argv=list(result.argv))
        persist(self.output/'native-trace.json',{'schema':'android-native-trace-v2','native_action_count':len(self.source),'events':self.source})
        self.flush()
        after,_=self.capture();after=self.adapter.sanitize(after)
        persist(self.output/(stem+'-after.png'),after.png)
        row.update(state='observed',after_image=stem+'-after.png');self.previous=action;self.pending=None;self.flush()

    def click(self,x,y):self._send('click',(x,y))
    def long_press(self,x,y):self._send('long_press',(x,y))
    def slide(self,x,y,x2,y2):self._send(self.scaled['action'],(x,y,x2,y2))
    def type(self,text):self._send('type',(text,))
    def back(self):self._send('system_button',('Back',))


    def save_pin(self,target):
        source=self.output/'native-trace.json'
        complete=(self.report['status']=='model_claimed_success' and bool(self.source)
                  and len(self.report['steps'])==len(self.source) and all(r['state']=='observed' for r in self.report['steps']))
        rows=[{'action_id':r['source_event']['action_id'],'before_image':r['before_image'],
               'before_sha256':hashlib.sha256((self.output/r['before_image']).read_bytes()).hexdigest(),
               'before_hierarchy_sha256':hashlib.sha256((self.output/(r['source_event']['action_id']+'-before.xml')).read_bytes()).hexdigest(),
               'foreground':r['foreground']} for r in self.report['steps'] if 'argv' in r]
        pin={'schema':'mobile-agent-recording-pin-v1','target':target,'complete':complete,
             'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None,'steps':rows}
        persist(self.output/'recording-pin.json',pin)
        return pin



class TransientCapture(RuntimeError):
    reason='capture_transition'


def capture_stable(read_once,*,pause=time.sleep,max_reads=10):
    """Retry only read-only transitional foreground observations; never resend input/model."""
    if type(max_reads) is not int or not 1<=max_reads<=10:raise ValueError('capture read limit invalid')
    for index in range(max_reads):
        try:return read_once()
        except TransientCapture:
            if index==max_reads-1:raise
            pause(1)
