"""Bounded public arXiv metadata search; returned material is abstract-only."""
import asyncio
import copy
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from .models import Paper, Page
from .observability import observed

NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}
IDENTIFIER = re.compile(r'^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$')


def parse_feed(text: str) -> list[Paper]:
    if len(text.encode('utf-8')) > 2 * 1024 * 1024 or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('Unsafe or oversized Atom feed')
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError('Invalid arXiv Atom response') from exc
    if root.tag != '{http://www.w3.org/2005/Atom}feed':
        raise ValueError('Expected an Atom feed')
    papers = []
    for entry in root.findall('a:entry', NS)[:30]:
        source = entry.findtext('a:id', '', NS).strip()
        if '/api/errors' in source:
            raise ValueError('arXiv rejected the search query')
        identifier = re.sub(r'^https?://arxiv.org/abs/', '', source)
        title = ' '.join(entry.findtext('a:title', '', NS).split())
        abstract = ' '.join(entry.findtext('a:summary', '', NS).split())
        if not IDENTIFIER.fullmatch(identifier) or not title or not abstract:
            continue
        paper_id = 'arxiv-' + identifier.replace('/', '-').replace('.', '-')
        papers.append(Paper(publication_type='preprint',paper_id=paper_id, title=title[:1000], arxiv_id=identifier,
                            doi=entry.findtext('x:doi', None, NS),
                            source_url=f'https://arxiv.org/abs/{identifier}', access_level='abstract',
                            authors=[e.text.strip()[:500] for e in entry.findall('a:author/a:name', NS) if e.text][:100],
                            published_at=entry.findtext('a:published', None, NS),
                            updated_at=entry.findtext('a:updated', None, NS),
                            pages=[Page(number=1, text=abstract[:200000])]))
    return papers


class ArxivProvider:
    endpoint = 'https://export.arxiv.org/api/query'

    def __init__(self):
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache = {}

    async def _fetch(self, query: str, limit: int, sort_by='relevance') -> str:
        import httpx
        async with self._lock:
            delay = 3.1 - (time.monotonic() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = time.monotonic()
            async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
                async with client.stream('GET', self.endpoint,
                    params={'search_query': query, 'max_results': limit, 'start': 0, 'sortBy': sort_by,'sortOrder':'descending'},
                    headers={'User-Agent': 'ScientificResearchWorkbench/0.2 (local research metadata client)'}) as response:
                    response.raise_for_status()
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        size += len(part)
                        if size > 2 * 1024 * 1024:
                            raise ValueError('arXiv response exceeds 2 MiB')
                        parts.append(part)
            return b''.join(parts).decode('utf-8')

    @observed('arxiv.search')
    async def search(self, query: str, *, limit=10, year_from=None, year_to=None) -> dict:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 300 or not 1 <= limit <= 30:
            raise ValueError('Query must be 1–300 characters; limit must be 1–30')
        words = re.findall(r'[\w-]+', query.strip())[:16]
        if not words:
            raise ValueError('No searchable words')
        expression = ' AND '.join(f'all:"{word}"' for word in words)
        if year_from is not None or year_to is not None:
            low, high = year_from or 1900, year_to or datetime.now(timezone.utc).year
            if not isinstance(low,int) or not isinstance(high,int) or not 1900<=low<=high<=2100:
                raise ValueError('Invalid publication year range')
            expression += f' AND submittedDate:[{low}01010000 TO {high}12312359]'
        sort_by='submittedDate' if year_from is not None or year_to is not None else 'relevance'
        key = expression, limit, sort_by
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < 3600:
            value = copy.deepcopy(cached[1])
            value['audit']['cache_hit'] = True
            return value
        text = await self._fetch(expression, limit, sort_by)
        papers = parse_feed(text)
        value = {'papers': [p.model_dump() for p in papers], 'audit': {
            'provider': 'arxiv', 'query': query, 'executed_query': expression, 'limit': limit,
            'retrieved_at': datetime.now(timezone.utc).isoformat(), 'returned': len(papers),
            'access_level': 'abstract', 'cache_hit': False,
            'sort_by':sort_by,'year_from':year_from,'year_to':year_to,
            'coverage': 'arXiv relevance-ranked subset; not a systematic literature review'}}
        if len(self._cache) >= 128:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = time.monotonic(), copy.deepcopy(value)
        return value

    @observed('arxiv.fulltext')
    async def fulltext(self, paper: Paper) -> Paper:
        """Only fetch validated arXiv identifiers, never model-supplied URLs."""
        import tempfile
        import httpx
        from pathlib import Path
        from urllib.parse import urljoin,urlsplit
        from .documents import load_pdf
        if not paper.arxiv_id or not IDENTIFIER.fullmatch(paper.arxiv_id):
            raise ValueError('Only validated arXiv IDs support automatic fulltext')
        url=f'https://arxiv.org/pdf/{paper.arxiv_id}'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'paper.pdf'
            async with self._lock:
                delay=3.1-(time.monotonic()-self._last_request)
                if delay>0:
                    await asyncio.sleep(delay)
                self._last_request=time.monotonic()
                async with httpx.AsyncClient(timeout=35,follow_redirects=False) as client:
                    for _ in range(4):
                        parsed=urlsplit(url)
                        if parsed.scheme!='https' or parsed.hostname not in {'arxiv.org','export.arxiv.org'} or parsed.username or parsed.password or parsed.port not in (None,443):
                            raise ValueError('Untrusted fulltext redirect')
                        async with client.stream('GET',url,headers={'User-Agent':'ScientificResearchWorkbench/0.3'}) as response:
                            if response.status_code in {301,302,303,307,308}:
                                url=urljoin(url,response.headers.get('location',''))
                                continue
                            response.raise_for_status()
                            total=0
                            with path.open('wb') as target:
                                async for part in response.aiter_bytes():
                                    total+=len(part)
                                    if total>25*1024*1024:
                                        raise ValueError('Fulltext exceeds 25 MiB')
                                    target.write(part)
                            break
                    else:
                        raise ValueError('Too many fulltext redirects')
            with path.open('rb') as source:
                if source.read(5)!=b'%PDF-':
                    raise ValueError('Fulltext endpoint did not return a PDF')
            task=asyncio.create_task(asyncio.to_thread(load_pdf,path,title=paper.title))
            try:
                parsed=await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            return Paper.model_validate({**paper.model_dump(),'pages':[p.model_dump() for p in parsed.pages],'access_level':'fulltext'})
