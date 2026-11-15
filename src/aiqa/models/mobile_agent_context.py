"""Original Mobile-Agent conversation from server-owned intent and settled history.

This pure helper does not confer authority: the producer must bind inputs to the
same authorized recording/attempt. It never consumes worker messages or reads paths.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass,field
from io import BytesIO
import hashlib
import json
import re

from aiqa.adapters.mobile_agent_upstream import load_protocol,render_reply,upstream_action
from aiqa.contracts.model_observations import ProviderObservation,parse_geometry
from aiqa.contracts.worker_attempt import RecordingIntent
from aiqa.models.openai_http import _conversation
from aiqa.models.mobile_action_format import is_native_text_literal
from aiqa.recording.intent import authoring_inputs,reject_secret_plaintext
from aiqa.security.redaction import _validate_png


@dataclass(frozen=True,slots=True)
class MobileAgentHistoryTurn:
    output:str
    observation:ProviderObservation|None


@dataclass(frozen=True,slots=True)
class MobileAgentContext:
    _document:str=field(repr=False)

    def messages(self):
        # A fresh snapshot prevents caller mutation crossing requests.
        return tuple(json.loads(self._document)['messages'])

    def text_literals(self):
        return tuple(json.loads(self._document)['text_literals'])

    def fingerprint(self):
        return hashlib.sha256(self._document.encode('utf-8')).hexdigest()


def _unique(pairs):
    result={}
    for name,value in pairs:
        if name in result:raise ValueError('duplicate history field')
        result[name]=value
    return result


def _not_constant(value):
    raise ValueError('non-finite history value')


def _history_output(protocol,output,geometry,literals):
    if type(output) is not str or not 1<=len(output.encode('utf-8'))<=16384:
        raise ValueError('history output size')
    rendered=render_reply(output)
    if rendered.count('<tool_call>')!=1 or rendered.count('</tool_call>')!=1:
        raise ValueError('one original action required')
    block=re.fullmatch(r'Action: ([^\r\n]{1,256})\n<tool_call>\s*(.*?)\s*</tool_call>\s*',rendered,flags=re.S)
    if (block is None or rendered.count('Action:')!=1 or not block[1].strip()
        or any(ord(char)<32 for char in block[1])):raise ValueError('original summary invalid')
    raw=json.loads(block[2],object_pairs_hook=_unique,parse_constant=_not_constant)
    if protocol.parse_action(rendered)!=raw:raise ValueError('original parser differs')
    from aiqa.replay.android_plan import PlanRejected
    try:action=upstream_action(protocol,raw,geometry)
    except PlanRejected:raise ValueError('history native action invalid') from None
    if action is not None and action.kind=='text' and action.text not in literals:
        raise ValueError('history typing outside frozen inputs')
    if action is not None and action.kind=='finish':raise ValueError('terminal history cannot continue')
    return rendered


def _image(frame):
    from PIL import Image
    if type(frame) is not ProviderObservation or type(frame.png) is not bytes or not 0<len(frame.png)<=2000000:
        raise ValueError('server image invalid')
    geometry=parse_geometry(frame.geometry)
    _validate_png(frame.png,geometry.physical_width,geometry.physical_height)
    if frame.image_hash!='sha256:'+hashlib.sha256(frame.png).hexdigest():
        raise ValueError('server image hash differs')
    encoded=BytesIO()
    with Image.open(BytesIO(frame.png)) as image:
        resized=image.convert('RGB').resize((1000,1000),Image.Resampling.LANCZOS)
        # Fresh pixels drop source ICC/text/exif metadata before model transmission.
        Image.frombytes('RGB',resized.size,resized.tobytes()).save(encoded,format='PNG')
    png=encoded.getvalue()
    if len(png)>2000000:raise ValueError('normalized image too large')
    return 'data:image/png;base64,'+base64.b64encode(png).decode('ascii')


def build_mobile_agent_context(*,intent,current,history,model='gpt-6-luna'):
    if (type(intent) is not RecordingIntent or type(current) is not ProviderObservation or model!='gpt-6-luna'
        or type(history) is not tuple or len(history)>79 or intent.secret_refs):
        raise ValueError('server context invalid')
    if type(intent.objective) is not str or not intent.objective.strip():
        raise ValueError('server objective missing')
    reject_secret_plaintext(intent.variables)
    instruction='\n'.join((*authoring_inputs(intent),'path_policy:'+json.dumps(intent.path_policy,ensure_ascii=False,sort_keys=True)))
    if len(instruction.encode('utf-8'))>12000:raise ValueError('server goal too large')
    literals=tuple(dict.fromkeys(value for value in intent.variables.values() if is_native_text_literal(value)))
    if len(literals)>32:raise ValueError('server input literals invalid')
    current_geometry=parse_geometry(current.geometry)
    protocol=load_protocol()
    images={f'server/screenshot_{len(history)}.png':_image(current)}
    outputs=[]
    for index,turn in enumerate(history):
        if type(turn) is not MobileAgentHistoryTurn:raise ValueError('server history invalid')
        name=f'server/screenshot_{index}.png'
        output=_history_output(protocol,turn.output,current_geometry,literals)
        if index>=len(history)-4:images[name]=_image(turn.observation)
        outputs.append({'output':output,'image':name})
    original=protocol.build_messages(f'server/screenshot_{len(history)}.png',instruction,outputs,model)
    messages=[]
    for message in original:
        role=message['role'];content=[]
        for part in message['content']:
            if set(part)=={'text'}:
                content.append({'type':'output_text' if role=='assistant' else 'input_text','text':part['text']})
            elif set(part)=={'image'} and part['image'].startswith('file://'):
                content.append({'type':'input_image','image_url':images[part['image'][7:]],'detail':'high'})
            else:raise ValueError('original content invalid')
        messages.append({'role':role,'content':content,**({'phase':'final_answer'} if role=='assistant' else {})})
    _conversation(tuple(messages))
    return MobileAgentContext(json.dumps({'messages':messages,'text_literals':literals},ensure_ascii=False,separators=(',',':'),allow_nan=False))
