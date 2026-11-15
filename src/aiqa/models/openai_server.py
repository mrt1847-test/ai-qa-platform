"""Server OpenAI port: one bounded send per admitted call; keys arrive by server resolver.

Gateway owns request idempotency and per-attempt budgets. This object never loads local keys.
"""
from collections import Counter
from threading import Lock
from aiqa.models.openai_http import OpenAIProviderHttp
from aiqa.models.provider_http import ProviderHttpError


class OpenAIServerProvider:
    kind='openai'
    supports_observation=True
    supports_send_boundary=True

    def __init__(self,*,timeout_seconds=10,transport=None):
        # Reuse the local port's strict timeout validation without enabling any send.
        OpenAIProviderHttp(timeout_seconds=timeout_seconds)
        self.timeout_seconds=float(timeout_seconds)
        self._transport=transport
        self._counts=Counter()
        self._lock=Lock()

    @property
    def call_count(self):
        with self._lock:return sum(self._counts.values())

    def calls_for(self,role):
        with self._lock:return self._counts[role]

    def complete(self,*,model,role,secret,sanitized_inputs,token_output_limit,observation=None,before_send=None,mobile_context=None):
        options={}
        if mobile_context is not None:
            from aiqa.models.mobile_agent_context import MobileAgentContext
            if (type(mobile_context) is not MobileAgentContext or model!='gpt-6-luna' or role!='authoring'
                or observation is not None or sanitized_inputs!=()):
                raise ProviderHttpError('provider_mobile_context_invalid',provider_dispatched=False)
            try:
                options={'conversation':mobile_context.messages(),'mobile_action_format':True,
                         'mobile_action_literals':mobile_context.text_literals()}
            except (ValueError,TypeError,KeyError):
                raise ProviderHttpError('provider_mobile_context_invalid',provider_dispatched=False) from None
        port=OpenAIProviderHttp(allow_live=True,max_calls=1,timeout_seconds=self.timeout_seconds,transport=self._transport)
        try:
            return port.complete(model=model,role=role,secret=secret,sanitized_inputs=sanitized_inputs,
                token_output_limit=token_output_limit,observation=observation,before_send=before_send,**options)
        except ProviderHttpError as exc:
            exc.provider_dispatched=port.call_count>0
            raise
        finally:
            if port.call_count:
                with self._lock:self._counts[role]+=port.call_count
