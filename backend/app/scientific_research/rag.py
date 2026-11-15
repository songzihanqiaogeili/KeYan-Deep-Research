"""Task-local BM25 + optional vector RRF retrieval with source provenance."""
import math
import re
import asyncio
import time
from collections import Counter
from .documents import document_hash
from .tracing import digest
from .embeddings import validate_vectors
from .observability import observed

STOP = {'the', 'a', 'an', 'of', 'to', 'and', 'or', 'in', 'on', 'for', 'with', 'is', 'are', 'this', 'that', 'we'}


def tokens(text):
    return [t for t in re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]', text.casefold()) if t not in STOP]


def bm25_scores(records, query):
    docs = [Counter(tokens(r.get('text', r.get('quote', '')))) for r in records]
    lengths = [sum(d.values()) for d in docs]
    n = len(docs)
    avg = sum(lengths)/max(n, 1)
    scores = [0.]*n
    for term in set(tokens(query)):
        df = sum(term in d for d in docs)
        if not df:
            continue
        idf = math.log(1+(n-df+.5)/(df+.5))
        for i, d in enumerate(docs):
            tf = d[term]
            if tf:
                scores[i] += idf*tf*2.2/(tf+1.2*(.25+.75*lengths[i]/max(avg, 1)))
    return scores


class Records(list):
    pass


def passage_records(papers, *, max_records=128):
    def rows(paper):
        hash_ = document_hash(paper)
        for page in paper.pages:
            for start in range(0, len(page.text), 1000):
                quote = page.text[start:start+1200]
                if quote.strip():
                    yield {
                        'chunk_id': digest([paper.paper_id, hash_, page.number, start]),
                        'paper_id': paper.paper_id, 'title': paper.title,
                        'page': page.number, 'start': start, 'quote': quote, 'text': quote,
                        'section': 'abstract' if paper.access_level == 'abstract' else 'page_text',
                        'source_url': paper.source_url, 'document_hash': hash_,
                        'access_level': paper.access_level}
    groups = [iter(rows(p)) for p in papers]
    # An upper bound includes whitespace-only windows, without allocating them.
    total = sum((len(page.text)+999)//1000 for p in papers for page in p.pages)
    result = Records()
    active = list(groups)
    while active and len(result) < max_records:
        remaining = []
        for group in active:
            if len(result) >= max_records:break
            row = next(group, None)
            if row is not None:result.append(row);remaining.append(group)
        active = remaining
    result.available_count = total
    return result


class TaskIndex:
    def __init__(self, records, *, embedder=None, max_records=128, deadline=None):
        self.records = list(records[:max_records])
        self.embedder = embedder
        self.vectors = []
        self.fallback_reason = ''
        self.mode = 'bm25'
        self.deadline = deadline
        self.base_identity = digest(['task-index-v2', getattr(embedder, 'identity', 'bm25'),
                                [(r['chunk_id'], r.get('text', r.get('quote', ''))) for r in self.records]])
        self.metrics = {
            'records': len(self.records), 'available_records': getattr(records, 'available_count', len(records)),
            'truncated': getattr(records, 'available_count', len(records)) > max_records, 'queries': 0}

    @property
    def identity(self):
        return digest([self.base_identity,self.mode,self.fallback_reason,bool(self.vectors)])

    async def embed(self,texts,timeout):
        remaining=self.deadline-time.monotonic() if self.deadline is not None else timeout
        if remaining<=0:raise TimeoutError('retrieval_deadline_reached')
        return await asyncio.wait_for(self.embedder.embed(texts),timeout=min(timeout,remaining))

    @observed('rag.index')
    async def build(self):
        if self.embedder and self.records:
            try:
                self.vectors = validate_vectors(
                    await self.embed([r.get('text', r.get('quote', '')) for r in self.records],30),
                    len(self.records))
                self.mode = 'hybrid'
            except Exception as exc:
                self.fallback_reason = type(exc).__name__
                self.vectors = []
        return self.metrics

    @observed('rag.search')
    async def search(self, query, *, limit=4, paper_id=None, allowed_ids=None):
        self.metrics['queries'] += 1
        positions = [i for i, r in enumerate(self.records)
                     if (paper_id is None or r.get('paper_id') == paper_id)
                     and (allowed_ids is None or r.get('evidence_id') in allowed_ids)]
        if not positions:
            return []
        rows = [self.records[i] for i in positions]
        lexical = bm25_scores(rows, query)
        lexical_order = sorted([i for i, s in enumerate(lexical) if s > 0], key=lambda i: (-lexical[i], i))
        semantic_order = []
        if self.vectors:
            try:
                q = validate_vectors(await self.embed([query],5), 1)[0]
                if len(q) != len(self.vectors[0]):
                    raise ValueError('embedding_query_dimension_mismatch')
                similarity = [sum(a*b for a, b in zip(q, self.vectors[i])) for i in positions]
                semantic_order = sorted([i for i, s in enumerate(similarity) if s > 0],
                                        key=lambda i: (-similarity[i], i))
            except Exception as exc:
                self.fallback_reason = type(exc).__name__
                self.vectors = []
                self.mode = 'bm25'
        ranks, scores = {}, {}
        for key, order in [('lexical_rank', lexical_order), ('semantic_rank', semantic_order)]:
            for rank, i in enumerate(order, 1):
                ranks.setdefault(i, {})[key] = rank
                scores[i] = scores.get(i, 0)+1/(60+rank)
        selected = sorted(scores, key=lambda i: (-scores[i], i))[:max(0, min(limit, 12))]
        return [{**rows[i], **ranks[i], 'score': round(scores[i], 8), 'retrieval_mode': self.mode,
                 'retrieval_identity': self.identity}
                for i in selected]


def claim_records(result):
    groups = {}
    for c in result['claims']:
        groups.setdefault(c['paper_id'], []).append({
            'chunk_id': c['evidence_id'], 'evidence_id': c['evidence_id'],
            'paper_id': c['paper_id'], 'text': c['text']+' '+c['quote']})
    return [group[i] for i in range(max(map(len, groups.values()), default=0))
            for group in groups.values() if i < len(group)]


class SeedRanker:
    """Ranks only collected candidates; similarity is not a citation edge."""
    def __init__(self, embedder):
        self.embedder = embedder
        self.identity = digest(['seed-ranker-v1', getattr(embedder, 'identity', 'disabled')])

    @observed('seed.semantic_rank')
    async def rank(self, papers, seeds, goal):
        if not self.embedder or not papers:
            return {'scores': {}, 'mode': 'disabled', 'fallback_reason': ''}
        query = goal[:300]+' '+' '.join(
            p.title[:150]+' '+p.pages[0].text[:350] for p in seeds[:3])
        texts = [query]+[p.title[:300]+' '+p.pages[0].text[:1400] for p in papers]
        try:
            vectors = validate_vectors(await self.embedder.embed(texts), len(texts))
            return {'scores': {p.paper_id: round(sum(a*b for a, b in zip(vectors[0], v)), 6)
                               for p, v in zip(papers, vectors[1:])},
                    'mode': 'semantic', 'fallback_reason': ''}
        except Exception as exc:
            return {'scores': {}, 'mode': 'fallback', 'fallback_reason': type(exc).__name__}
