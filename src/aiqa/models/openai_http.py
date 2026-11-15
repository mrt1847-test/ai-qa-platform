"""Explicit, bounded OpenAI Responses port; local smoke use, no implicit key loading."""
from __future__ import annotations
import base64
from dataclasses import dataclass
import hashlib
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

    def __init__(self, *, allow_live=False, max_calls=3, transport=None):
        if type(max_calls) is not int or not 1<=max_calls<=3:raise ValueError('call cap must be 1..3')
        self.allow_live=allow_live
        self.max_calls=max_calls
        self._transport=transport
        self._stopped=False
        self.calls=[]

    @property
    def call_count(self):return len(self.calls)

    def complete(self, *, model, role, secret, sanitized_inputs, token_output_limit, observation=None):
        if not self.allow_live or self._stopped or self.call_count>=self.max_calls:
            raise ProviderHttpError('provider_disabled_or_exhausted')
        if (type(secret) is not str or not secret or any(c.isspace() for c in secret)
            or type(model) is not str or not model or len(model)>128
            or role not in {'authoring','verification','healing','structure'}
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
        if model.startswith('gpt-5'):body['reasoning']={'effort':'minimal'}
        self.calls.append({'model':model,'role':role,'token_output_limit':token_output_limit})
        try:
            with httpx.Client(timeout=60,trust_env=False,follow_redirects=False,transport=self._transport) as client:
                with client.stream('POST','https://api.openai.com/v1/responses',json=body,
                    headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'}) as reply:
                    if reply.status_code!=200:
                        reason={401:'provider_unauthorized',403:'provider_unauthorized',429:'provider_quota'}.get(reply.status_code,'provider_http_error')
                        raise ProviderHttpError(reason,status=reply.status_code)
                    raw=bytearray()
                    for chunk in reply.iter_bytes():
                        raw.extend(chunk)
                        if len(raw)>2_000_000:raise ProviderHttpError('provider_response_too_large')
            data=json.loads(raw)
            if type(data) is not dict or data.get('status')!='completed':raise ValueError()
            identity,actual,usage=data['id'],data['model'],data['usage']
            if type(identity) is not str or not identity or type(actual) is not str or not actual:raise ValueError()
            if type(usage) is not dict:raise ValueError()
            counts=tuple(usage[k] for k in ('input_tokens','output_tokens','total_tokens'))
            if any(type(v) is not int or v<0 for v in counts) or counts[2]!=counts[0]+counts[1]:raise ValueError()
            texts=[]
            for item in data['output']:
                if item.get('type')=='message':
                    if item.get('role')!='assistant' or item.get('status') not in (None,'completed'):raise ValueError()
                    for part in item['content']:
                        if part.get('type')!='output_text' or type(part.get('text')) is not str:raise ValueError()
                        texts.append(part['text'])
            text=''.join(texts).strip()
            if not text:raise ValueError()
            return OpenAIProviderResult(text,identity,200,actual,*counts)
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
