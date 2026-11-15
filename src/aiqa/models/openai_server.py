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

    def complete(self,*,model,role,secret,sanitized_inputs,token_output_limit,observation=None,before_send=None):
        port=OpenAIProviderHttp(allow_live=True,max_calls=1,timeout_seconds=self.timeout_seconds,transport=self._transport)
        try:
            return port.complete(model=model,role=role,secret=secret,sanitized_inputs=sanitized_inputs,
                token_output_limit=token_output_limit,observation=observation,before_send=before_send)
        except ProviderHttpError as exc:
            exc.provider_dispatched=port.call_count>0
            raise
        finally:
            if port.call_count:
                with self._lock:self._counts[role]+=port.call_count
