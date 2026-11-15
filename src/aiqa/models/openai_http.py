"""Explicit, bounded OpenAI Responses port; local smoke use, no implicit key loading."""
from __future__ import annotations
import base64
from contextlib import closing
from dataclasses import dataclass
import hashlib
import math
import json
from pathlib import Path
import httpx
from aiqa.contracts.model_observations import parse_geometry
from aiqa.models.provider_http import ProviderHttpError, ProviderHttpResult


@dataclass(frozen=True, slots=True)
class OpenAIProviderResult(ProviderHttpResult):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None


def load_local_api_key(path: Path) -> str:
    """Read the one explicit local credential without shell expansion or diagnostics."""
    try:
        if path.stat().st_size>16384:raise ValueError()
        values=[]
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            if not line.startswith('OPENAI_API_KEY='):raise ValueError()
            value=line.split('=',1)[1].strip()
            if len(value)>=2 and value[0] in ('"', "'") and value[-1]==value[0]:value=value[1:-1]
            if not value or any(c.isspace() for c in value):raise ValueError()
            values.append(value)
        if len(values)!=1:raise ValueError()
        return values[0]
    except (OSError,UnicodeError,ValueError):
        raise ValueError('local API credential is missing or invalid') from None


class OpenAIProviderHttp:
    kind='openai'
    supports_observation=True

    def __init__(self, *, allow_live=False, max_calls=3, reasoning_effort=None, transport=None, response_sink=None, timeout_seconds=60):
        if type(max_calls) is not int or not 1<=max_calls<=12:raise ValueError('call cap must be 1..12')
        if reasoning_effort not in {None,'none','low','medium','high'}:raise ValueError('reasoning effort unsupported')
        if response_sink is not None and not callable(response_sink):raise ValueError('response sink invalid')
        if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not 0<timeout_seconds<=60:raise ValueError('provider timeout invalid')
        self.timeout_seconds=float(timeout_seconds)
        self._response_sink=response_sink
        self.reasoning_effort=reasoning_effort
        self.allow_live=allow_live
        self.max_calls=max_calls
        self._transport=transport
        self._stopped=False
        self.calls=[]

    @property
    def call_count(self):return len(self.calls)

    def complete(self, *, model, role, secret, sanitized_inputs, token_output_limit, observation=None, before_send=None, conversation=None, mobile_action_format=False, mobile_action_literals=None):
        if not self.allow_live or self._stopped or self.call_count>=self.max_calls:
            raise ProviderHttpError('provider_disabled_or_exhausted')
        if (type(secret) is not str or not secret or any(c.isspace() for c in secret)
            or type(model) is not str or not model or len(model)>128
            or role not in {'authoring','verification','healing','structure','maintenance'}
            or type(token_output_limit) is not int or not 16<=token_output_limit<=2048
            or type(sanitized_inputs) is not tuple or any(type(s) is not str for s in sanitized_inputs)
            or sum(len(s) for s in sanitized_inputs)>20000):
            raise ProviderHttpError('provider_input_invalid')
        content=[{'type':'input_text','text':s} for s in sanitized_inputs]
        if not content:content=[{'type':'input_text','text':'Return only a response for the requested role.'}]
        if observation is not None:
            from aiqa.security.redaction import _validate_png
            try:
                geo=parse_geometry(observation.geometry)
                if not 0<len(observation.png)<=2_000_000:raise ValueError()
                _validate_png(observation.png,geo.physical_width,geo.physical_height)
                if observation.image_hash!='sha256:'+hashlib.sha256(observation.png).hexdigest():raise ValueError()
            except (ValueError,TypeError,AttributeError):raise ProviderHttpError('provider_observation_invalid') from None
            content.append({'type':'input_text','text':'Coordinate frame: '+json.dumps(observation.geometry,sort_keys=True)})
            content.append({'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(observation.png).decode('ascii'),'detail':'high'})
        body={'model':model,'store':False,'max_output_tokens':token_output_limit,
            'input':[{'role':'user','content':content}]}
        if conversation is not None:
            if observation is not None or sanitized_inputs:raise ProviderHttpError('provider_input_invalid')
            body['input']=_conversation(conversation)
        if mobile_action_format:
            if conversation is None or role!='authoring' or model!='gpt-6-luna':raise ProviderHttpError('provider_input_invalid')
            from aiqa.models.mobile_action_format import MOBILE_ACTION_FORMAT
            if mobile_action_literals is None:body['text']={'format':MOBILE_ACTION_FORMAT}
            else:
                from aiqa.models.mobile_action_format import mobile_action_format_for
                try:body['text']={'format':mobile_action_format_for(mobile_action_literals)}
                except ValueError:raise ProviderHttpError('provider_input_invalid') from None
        if mobile_action_literals is not None and not mobile_action_format:raise ProviderHttpError('provider_input_invalid')
        if model.startswith('gpt-6'):body['reasoning']={'effort':self.reasoning_effort or 'low'}
        elif self.reasoning_effort is not None:body['reasoning']={'effort':self.reasoning_effort}
        elif model.startswith('gpt-5'):body['reasoning']={'effort':'minimal'}
        if before_send is not None and not callable(before_send):raise ProviderHttpError('provider_input_invalid')
        try:
            with httpx.Client(timeout=self.timeout_seconds,trust_env=False,follow_redirects=False,transport=self._transport) as client:
                request=client.build_request('POST','https://api.openai.com/v1/responses',json=body,
                    headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
                if before_send is not None:before_send()
                self.calls.append({'model':model,'role':role,'token_output_limit':token_output_limit})
                with closing(client.send(request,stream=True)) as reply:
                    if reply.status_code!=200:
                        reason={401:'provider_unauthorized',403:'provider_unauthorized',429:'provider_quota'}.get(reply.status_code,'provider_http_error')
                        raise ProviderHttpError(reason,status=reply.status_code)
                    raw=bytearray()
                    for chunk in reply.iter_bytes():
                        raw.extend(chunk)
                        if len(raw)>2_000_000:raise ProviderHttpError('provider_response_too_large')
            if self._response_sink is not None:self._response_sink(bytes(raw))
            data=json.loads(raw)
            if type(data) is not dict or data.get('status')!='completed':raise ValueError()
            identity,actual,usage=data['id'],data['model'],data['usage']
            if type(identity) is not str or not identity or type(actual) is not str or not actual:raise ValueError()
            if type(usage) is not dict:raise ValueError()
            counts=tuple(usage[k] for k in ('input_tokens','output_tokens','total_tokens'))
            if any(type(v) is not int or v<0 for v in counts) or counts[2]!=counts[0]+counts[1]:raise ValueError()
            def detail(group,name,limit):
                values=usage.get(group)
                if values is None or name not in values:return None
                value=values[name]
                if type(value) is not int or not 0<=value<=limit:raise ValueError()
                return value
            reasoning=detail('output_tokens_details','reasoning_tokens',counts[1])
            cached=detail('input_tokens_details','cached_tokens',counts[0])
            texts=[]
            messages=[item for item in data['output'] if item.get('type')=='message']
            finals=[item for item in messages if item.get('phase')=='final_answer']
            chosen=finals if finals else [item for item in messages if item.get('phase') is None]
            if len(chosen)!=1 or any(item.get('phase') not in {None,'commentary','final_answer'} for item in messages):raise ValueError()
            for item in chosen:
                if item.get('type')=='message':
                    if item.get('role')!='assistant' or item.get('status') not in (None,'completed'):raise ValueError()
                    for part in item['content']:
                        if part.get('type')!='output_text' or type(part.get('text')) is not str:raise ValueError()
                        texts.append(part['text'])
            text=''.join(texts).strip()
            if not text:raise ValueError()
            return OpenAIProviderResult(text,identity,200,actual,*counts,reasoning_tokens=reasoning,cached_input_tokens=cached)
        except ProviderHttpError:
            self._stopped=True
            raise
        except httpx.TimeoutException:
            self._stopped=True
            raise ProviderHttpError('provider_timeout') from None
        except httpx.HTTPError:
            self._stopped=True
            raise ProviderHttpError('provider_transport') from None
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError):
            self._stopped=True
            raise ProviderHttpError('provider_response_invalid') from None


def _conversation(messages):
    """Bounded Responses conversation; embedded validated PNGs only, no remote URLs."""
    import struct
    from aiqa.security.redaction import _validate_png
    try:
        if type(messages) is not tuple or not 1<=len(messages)<=12:raise ValueError()
        images=0;size=0
        for message in messages:
            if type(message) is not dict or set(message) not in ({'role','content'},{'role','content','phase'}) or message['role'] not in {'system','user','assistant'}:raise ValueError()
            if 'phase' in message and (message['role']!='assistant' or message['phase']!='final_answer'):raise ValueError()
            if type(message['content']) is not list or not 1<=len(message['content'])<=4:raise ValueError()
            for item in message['content']:
                if type(item) is not dict:raise ValueError()
                if item.get('type')=='input_image':
                    if message['role']!='user' or set(item)!={'type','image_url','detail'} or item['detail']!='high':raise ValueError()
                    url=item['image_url']
                    if type(url) is not str or not url.startswith('data:image/png;base64,') or len(url)>2_700_000:raise ValueError()
                    raw=base64.b64decode(url.split(',',1)[1],validate=True)
                    if not 24<=len(raw)<=2_000_000:raise ValueError()
                    width,height=struct.unpack_from('>II',raw,16);_validate_png(raw,width,height)
                    images+=1;size+=len(raw)
                else:
                    kind='output_text' if message['role']=='assistant' else 'input_text'
                    if set(item)!={'type','text'} or item['type']!=kind or type(item['text']) is not str or len(item['text'])>32000:raise ValueError()
                    size+=len(item['text'].encode('utf-8'))
        if images>5 or size>8_000_000:raise ValueError()
        return list(messages)
    except (ValueError,TypeError,KeyError,UnicodeError,struct.error):raise ProviderHttpError('provider_input_invalid') from None
