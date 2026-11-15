"""Explicitly configured real model; no import-time network or legacy config."""
import json
import os
import hashlib
from contextvars import ContextVar
from urllib.parse import urlsplit


class OpenAIModel:
    fixture = False

    def __init__(self):
        from .config import load_project_env
        load_project_env()
        from openai import AsyncOpenAI
        key = os.environ.get('SCIENTIFIC_LLM_API_KEY')
        self.model = os.environ.get('SCIENTIFIC_LLM_MODEL')
        self.usage_context = ContextVar('scientific_model_usage', default=None)
        if not key or not self.model:
            raise ValueError('Set SCIENTIFIC_LLM_API_KEY and SCIENTIFIC_LLM_MODEL')
        endpoint=urlsplit(os.environ.get('SCIENTIFIC_LLM_BASE_URL') or '')
        self.ollama_qwen=endpoint.hostname in {'127.0.0.1','localhost','::1'} and endpoint.port==11434 and self.model.lower().startswith('qwen')
        self.identity = hashlib.sha256((self.model + (os.environ.get('SCIENTIFIC_LLM_BASE_URL') or 'default') + ('no-thinking-v1' if self.ollama_qwen else '')).encode()).hexdigest()
        timeout=float(os.environ.get('SCIENTIFIC_LLM_TIMEOUT','90'))
        if not 10<=timeout<=900:
            raise ValueError('SCIENTIFIC_LLM_TIMEOUT must be 10–900 seconds')
        self.timeout_seconds = timeout
        self.client = AsyncOpenAI(api_key=key, base_url=os.environ.get('SCIENTIFIC_LLM_BASE_URL') or None,
                                  timeout=timeout, max_retries=0)

    async def complete(self, role, system, context):
        usage_context = getattr(self, 'usage_context', None)
        if usage_context is not None:
            usage_context.set(None)
        options={'reasoning_effort':'none'} if self.ollama_qwen else {}
        output_limit={'controller':1000,'planner':1500,'outliner':1600,'section_writer':2200,
                      'section_reviser':2200,'report_reviewer':1800}.get(role,6000)
        response = await self.client.chat.completions.create(
            model=self.model, messages=[{'role': 'system', 'content': system},
                                       {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}],
            response_format={'type': 'json_object'}, temperature=0.2, max_tokens=output_limit, **options,
        )
        usage = getattr(response, 'usage', None)
        if usage_context is not None and usage is not None:
            usage_context.set({key: getattr(usage, key, None) for key in
                               ('prompt_tokens', 'completion_tokens', 'total_tokens')})
        if response.choices[0].finish_reason == 'length':
            raise ValueError('model output truncated')
        return json.loads(response.choices[0].message.content or '{}')

    async def close(self):
        await self.client.close()
