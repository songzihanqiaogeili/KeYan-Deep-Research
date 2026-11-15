"""Optional, bounded local Ollama embeddings. Never pulls a model."""
import math
import os
from collections import OrderedDict
from urllib.parse import urlsplit
import httpx
from .tracing import digest
from .observability import observed


def validate_vectors(vectors, count):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError('embedding_count_mismatch')
    dimensions = None
    clean = []
    for vector in vectors:
        if not isinstance(vector, list) or not 1 <= len(vector) <= 4096:
            raise ValueError('embedding_dimension_invalid')
        if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) for x in vector):
            raise ValueError('embedding_nonfinite')
        if dimensions is not None and len(vector) != dimensions:
            raise ValueError('embedding_dimension_mismatch')
        dimensions = len(vector)
        norm = math.sqrt(sum(x*x for x in vector))
        if not math.isfinite(norm) or norm <= 0:
            raise ValueError('embedding_zero_norm')
        clean.append([x/norm for x in vector])
    return clean


class OllamaEmbeddings:
    def __init__(self, model, base_url='http://127.0.0.1:11434', *, transport=None, batch_size=16):
        parsed = urlsplit(base_url)
        if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.scheme not in {'http', 'https'}:
            raise ValueError('Embeddings require an explicit loopback Ollama URL')
        self.model = model
        self.identity = digest(['ollama-embed-v1', base_url, model])
        self.batch_size = max(1, min(16, batch_size))
        self.client = httpx.AsyncClient(base_url=base_url.rstrip('/'), timeout=20,
                                       trust_env=False, transport=transport)
        self.cache = OrderedDict()
        self.failed = False
        self.metrics = {'batches': 0, 'input_tokens': 0, 'cache_hits': 0}

    @classmethod
    def from_env(cls):
        model = os.environ.get('SCIENTIFIC_EMBEDDING_MODEL', '').strip()
        return cls(model, os.environ.get('SCIENTIFIC_EMBEDDING_BASE_URL', 'http://127.0.0.1:11434')) if model else None

    @observed('ollama.embed')
    async def embed(self, texts):
        if self.failed:
            raise RuntimeError('embedding_unavailable_for_this_run')
        if len(texts) > 256:
            raise ValueError('embedding_input_budget')
        texts = [str(t)[:1800] for t in texts]
        missing = list(dict.fromkeys(t for t in texts if t not in self.cache))
        self.metrics['cache_hits'] += len(texts)-len(missing)
        try:
            for start in range(0, len(missing), self.batch_size):
                if self.metrics['batches'] >= 32:
                    raise ValueError('embedding_batch_budget')
                batch = missing[start:start+self.batch_size]
                self.metrics['batches'] += 1
                response = await self.client.post('/api/embed', json={
                    'model': self.model, 'input': batch, 'truncate': True, 'keep_alive': '1m'})
                response.raise_for_status()
                payload = response.json()
                vectors = validate_vectors(payload.get('embeddings'), len(batch))
                self.metrics['input_tokens'] += max(0, int(payload.get('prompt_eval_count', 0)))
                for text, vector in zip(batch, vectors):
                    self.cache[text] = vector
            result = [self.cache[t] for t in texts]
            while len(self.cache) > 512:
                self.cache.popitem(last=False)
            return result
        except Exception:
            self.failed = True
            raise

    async def close(self):
        await self.client.aclose()
        self.cache.clear()
