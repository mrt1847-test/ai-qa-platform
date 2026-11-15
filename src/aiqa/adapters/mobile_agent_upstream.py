"""Execute pinned Mobile-Agent's original main; only model/device I/O is replaced.

This runner owns cwd/stdout while active. Invoke in a dedicated process, never a server thread.
"""
from __future__ import annotations
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
import hashlib,importlib.util,json,os,sys,threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from aiqa.replay.android_plan import build_typed_android_action,TypedAndroidAction

from aiqa.contracts.mobile_agent_engine import MOBILE_AGENT_COMMIT,MOBILE_AGENT_MANIFEST_SHA256

COMMIT=MOBILE_AGENT_COMMIT
_LOCK=threading.Lock()
_MANIFEST_SHA=MOBILE_AGENT_MANIFEST_SHA256


def _module(name,path,source):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    exec(compile(source,str(path),'exec',dont_inherit=True),module.__dict__)
    return module


def _source_root(root=None):
    root=Path(root) if root else Path(__file__).resolve().parents[3]/'third_party/mobile_agent'
    manifest_bytes=(root/'manifest.json').read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest()!=_MANIFEST_SHA:raise ValueError()
    manifest=json.loads(manifest_bytes)
    if set(manifest['files'])!={'run_gui_owl_1_5_for_mobile.py','utils.py','packages.py','LICENSE'}:raise ValueError()
    if manifest['commit']!=COMMIT:raise ValueError()
    sources={name:(root/'upstream'/name).read_bytes() for name in manifest['files']}
    for name,v in manifest['files'].items():
        if hashlib.sha256(sources[name]).hexdigest()!=v['vendored_sha256']:raise ValueError()
    return root,sources


def load_upstream(*,root=None):
    try:
        root,sources=_source_root(root)
        utils=_module('_aiqa_mobile_utils',root/'upstream/utils.py',sources['utils.py'])
        packages=_module('_aiqa_mobile_packages',root/'upstream/packages.py',sources['packages.py'])
        # Original imports are absolute; restore prior modules immediately after import.
        previous={n:sys.modules.get(n) for n in ('utils','packages')}
        try:
            sys.modules.update(utils=utils,packages=packages)
            runner=_module('_aiqa_mobile_runner',root/'upstream/run_gui_owl_1_5_for_mobile.py',sources['run_gui_owl_1_5_for_mobile.py'])
        finally:
            for name,old in previous.items():
                if old is None:sys.modules.pop(name,None)
                else:sys.modules[name]=old
        runner.SYSTEM_PROMPT=utils.SYSTEM_PROMPT
        return runner
    except (OSError,KeyError,ValueError,TypeError):
        raise ValueError('pinned Mobile-Agent source unavailable or changed') from None


def upstream_action(upstream,raw,geometry):
    """Run original rescale, then map its resized pixels back to physical display."""
    if type(raw) is not dict or set(raw)!={'name','arguments'} or raw['name']!='mobile_use':raise ValueError('upstream tool invalid')
    args=deepcopy(raw['arguments'])
    if type(args) is not dict or type(args.get('action')) is not str:raise ValueError('upstream action invalid')
    name=args['action'];allowed={
        'click':{'action','coordinate'},'long_press':{'action','coordinate'},
        'swipe':{'action','coordinate','coordinate2'},'scroll':{'action','coordinate','coordinate2'},
        'type':{'action','text'},'system_button':{'action','button'},
        'terminate':{'action','status'},'wait':{'action','time'}}
    if name not in allowed or set(args)!=allowed[name]:raise ValueError('upstream action unsupported')
    if name=='terminate':
        if type(args['status']) is not str or args['status'] not in {'success','failure'}:raise ValueError('terminal status invalid')
        return TypedAndroidAction('finish')
    if name=='wait':
        if type(args['time']) not in (int,float) or not 0<=args['time']<=2:raise ValueError('wait outside cap')
        return None
    rh,rw=upstream.smart_resize(geometry.physical_height,geometry.physical_width,factor=16,min_pixels=3136,max_pixels=1003520*200)
    for key in ('coordinate','coordinate2'):
        if key in args and (type(args[key]) is not list or len(args[key])!=2 or any(type(n) not in (int,float) or not 0<=n<=1000 for n in args[key])):
            raise ValueError('normalized coordinate invalid')
    scaled=upstream.rescale_coordinates(args,rw,rh)
    def point(key):
        x,y=scaled[key]
        return min(geometry.physical_width-1,int(round(x*geometry.physical_width/rw))),min(geometry.physical_height-1,int(round(y*geometry.physical_height/rh)))
    kw={'width':geometry.physical_width,'height':geometry.physical_height,'rotation':geometry.rotation}
    if name in {'click','long_press','swipe','scroll'}:
        kw['x'],kw['y']=point('coordinate')
        if name in {'swipe','scroll'}:kw['x2'],kw['y2']=point('coordinate2');kw['duration_ms']=800
        elif name=='long_press':kw['x2'],kw['y2']=kw['x'],kw['y'];kw['duration_ms']=800
        return build_typed_android_action('tap' if name=='click' else 'swipe',**kw)
    if name=='type':return build_typed_android_action('text',text=scaled['text'],**kw)
    if scaled['button']!='Back':raise ValueError('upstream system button unsupported')
    return build_typed_android_action('key',keycode=4,**kw)


def run_upstream(upstream,*,io,predict,output,instruction,max_steps=10,sleep=None):
    """Actual original main. io must enforce action policy and persist before native send."""
    import time
    if threading.current_thread()!=threading.main_thread() or not _LOCK.acquire(blocking=False):raise RuntimeError('dedicated process required')
    output=Path(output).resolve();old=Path.cwd()
    try:
        output.mkdir(parents=True,exist_ok=False)
        tag=('AIQA_'+uuid4().hex).ljust(80,'_')
        args=SimpleNamespace(adb_path='injected-adb',device='injected-device',api_key='injected-secret-reference',
            base_url='https://api.openai.com/v1',model='gpt-6-luna',instruction=tag,add_info=instruction,max_steps=max_steps,
            app_resolver_api_key=None,app_resolver_base_url=None,app_resolver_model='disabled')
        class Model:
            def __init__(self,*a,**kw):pass
            def predict_mm(self,messages):return predict(messages),None,None
        upstream.parse_args=lambda:args
        upstream.AdbTools=lambda **kwargs:io
        upstream.GUIOwlWrapper=Model
        upstream.time=SimpleNamespace(sleep=sleep or time.sleep)
        os.chdir(output)
        with (output/'upstream.log').open('w',encoding='utf-8') as log,redirect_stdout(log):upstream.main()
        return {'upstream_commit':COMMIT,'main_invocations':1,'main_file':upstream.main.__code__.co_filename}
    finally:
        os.chdir(old);_LOCK.release()



def render_reply(text):
    """Luna structured-output codec only; original upstream parser still interprets the tool."""
    if not text.lstrip().startswith('{'):return text
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate model field')
            result[key]=value
        return result
    raw=json.loads(text,object_pairs_hook=unique)
    if (type(raw) is not dict or set(raw)!={'summary','name','arguments'} or raw['name']!='mobile_use'
        or type(raw['summary']) is not str or not 1<=len(raw['summary'])<=256
        or any(ord(c)<32 for c in raw['summary'])):raise ValueError('single action format invalid')
    tool={'name':raw['name'],'arguments':raw['arguments']}
    return 'Action: '+raw['summary']+'\n<tool_call>\n'+json.dumps(tool,ensure_ascii=False,separators=(',',':'))+'\n</tool_call>'



def load_protocol(*,root=None):
    """Load original pure protocol functions without runner absolute imports or cwd changes."""
    import ast
    try:
        root,sources=_source_root(root)
        utils=_module('_aiqa_mobile_protocol_utils',root/'upstream/utils.py',sources['utils.py'])
        path=root/'upstream/run_gui_owl_1_5_for_mobile.py'
        tree=ast.parse(sources['run_gui_owl_1_5_for_mobile.py'])
        selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in {'parse_action','rescale_coordinates'}]
        if len(selected)!=2:raise ValueError()
        namespace={'json':json}
        exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec',dont_inherit=True),namespace)
        return SimpleNamespace(SYSTEM_PROMPT=utils.SYSTEM_PROMPT,build_messages=utils.build_messages,
            smart_resize=utils.smart_resize,parse_action=namespace['parse_action'],rescale_coordinates=namespace['rescale_coordinates'])
    except (OSError,KeyError,ValueError,TypeError,SyntaxError):
        raise ValueError('pinned Mobile-Agent protocol unavailable or changed') from None
