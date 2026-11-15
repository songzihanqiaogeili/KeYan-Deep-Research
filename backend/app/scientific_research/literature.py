from .observability import observed
"""Scholarly search with explicit provenance and a bounded source fallback."""
import copy
import json
import re
import time
from datetime import datetime,timezone
from urllib.parse import urlsplit
from .models import Paper,Page
from .providers import ArxivProvider,IDENTIFIER


def parse_openalex(payload):
    papers=[]
    for work in payload.get('results',[])[:30]:
        ident=work.get('id','')
        title=work.get('title') or work.get('display_name') or ''
        index=work.get('abstract_inverted_index')
        if not re.fullmatch(r'https://openalex.org/W\d{1,30}',ident) or not title or not isinstance(index,dict):
            continue
        positions={}
        for word,items in list(index.items())[:10000]:
            if not isinstance(word,str) or not isinstance(items,list):
                continue
            for pos in items[:1000]:
                if type(pos) is int and 0<=pos<=50000 and len(positions)<20000:
                    positions.setdefault(pos,word)
        abstract=' '.join(word for _,word in sorted(positions.items()))[:200000]
        if not abstract.strip():
            continue
        location=work.get('primary_location') or {}
        source=location.get('source') or {}
        doi=work.get('doi')
        if doi and not isinstance(doi,str):
            doi=None
        source_url=doi or location.get('landing_page_url') or ident
        if urlsplit(source_url).scheme not in {'http','https'}:
            source_url=ident
        arxiv_id=None
        for url in [location.get('landing_page_url'),(work.get('open_access') or {}).get('oa_url')]:
            if not isinstance(url,str):
                continue
            parsed=urlsplit(url)
            if parsed.hostname in {'arxiv.org','export.arxiv.org'} and parsed.path.startswith(('/abs/','/pdf/')):
                value=re.sub(r'^/(?:abs|pdf)/','',parsed.path).removesuffix('.pdf')
                if IDENTIFIER.fullmatch(value):
                    arxiv_id=value
        if arxiv_id is None and doi:
            doi_url=urlsplit(doi)
            match=re.fullmatch(r'/10[.]48550/arxiv[.](.+)',doi_url.path,re.I)
            if doi_url.hostname in {'doi.org','dx.doi.org'} and match and IDENTIFIER.fullmatch(match.group(1)):
                arxiv_id=match.group(1)
        authors=[a.get('author',{}).get('display_name','') for a in (work.get('authorships') or [])[:100] if isinstance(a,dict)]
        publication_type=('preprint' if work.get('type')=='preprint' else 'conference' if work.get('type')=='proceedings-article' else 'journal' if work.get('type')=='article' and source.get('type')=='journal' else 'unknown')
        papers.append(Paper(publication_type=publication_type,paper_id='openalex-'+ident.rsplit('/',1)[1],title=title[:1000],
            doi=doi[:300] if doi else None,arxiv_id=arxiv_id,source_url=source_url[:2000],
            authors=[a[:500] for a in authors if isinstance(a,str) and a.strip()],
            issns=[x for x in (source.get('issn') or [])[:10] if isinstance(x,str)],venue=(source.get('display_name') or '')[:1000],published_at=work.get('publication_date'),
            access_level='abstract',pages=[Page(number=1,text=abstract)]))
    return papers


class OpenAlexProvider:
    endpoint='https://api.openalex.org/works'
    def __init__(self):
        self.cache={}

    @observed('openalex.search')
    async def search(self,query,*,limit=10,year_from=None,year_to=None,rank_by_relevance=False):
        import httpx
        if not isinstance(query,str) or not 1<=len(query.strip())<=300 or not 1<=limit<=30:
            raise ValueError('Invalid scholarly query bounds')
        params={'search':query.strip(),'per-page':limit,'filter':'has_abstract:true'}
        filters=['has_abstract:true']
        if year_from is not None or year_to is not None:
            low,high=year_from or 1900,year_to or datetime.now(timezone.utc).year
            if type(low) is not int or type(high) is not int or not 1900<=low<=high<=2100:
                raise ValueError('Invalid publication year range')
            filters+= [f'from_publication_date:{low}-01-01',f'to_publication_date:{high}-12-31']
            params['sort']='publication_date:desc'
        if rank_by_relevance:params['sort']='relevance_score:desc'
        params['filter']=','.join(filters)
        key=json.dumps(params,sort_keys=True)
        saved=self.cache.get(key)
        if saved and time.monotonic()-saved[0]<3600:
            result=copy.deepcopy(saved[1]);result['audit']['cache_hit']=True;return result
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
            async with client.stream('GET',self.endpoint,params=params,headers={'User-Agent':'ScientificResearchWorkbench/0.4'}) as response:
                response.raise_for_status()
                parts,total=[],0
                async for part in response.aiter_bytes():
                    total+=len(part)
                    if total>2*1024*1024:
                        raise ValueError('OpenAlex response exceeds 2 MiB')
                    parts.append(part)
        payload=json.loads(b''.join(parts))
        papers=parse_openalex(payload)
        result={'papers':[p.model_dump() for p in papers],'audit':{
            'provider':'openalex','query':query,'executed_query':params,'limit':limit,'returned':len(papers),
            'retrieved_at':datetime.now(timezone.utc).isoformat(),'cache_hit':False,
            'access_level':'abstract','coverage':'OpenAlex indexed metadata and available abstracts; venue quality and fulltext not certified'}}
        if len(self.cache)>=128:self.cache.pop(next(iter(self.cache)))
        self.cache[key]=time.monotonic(),copy.deepcopy(result)
        return result


class LiteratureProvider:
    def __init__(self):
        self.primary=ArxivProvider()
        self.secondary=OpenAlexProvider()
        self.primary_retry_at=0.0

    async def search(self,query,*,limit=10,year_from=None,year_to=None):
        reason='arxiv_temporarily_unavailable'
        if time.monotonic()>=self.primary_retry_at:
            try:
                result=await self.primary.search(query,limit=limit,year_from=year_from,year_to=year_to)
                if result['papers']:
                    return result
                reason='arxiv_no_results'
            except Exception:
                self.primary_retry_at=time.monotonic()+120
                reason='arxiv_request_failed'
        try:
            result=await self.secondary.search(query,limit=limit,year_from=year_from,year_to=year_to)
            result=copy.deepcopy(result)
            result['audit'].update({'fallback_from':'arxiv','fallback_reason':reason})
            return result
        except Exception as exc:
            raise ValueError('literature_sources_unavailable') from exc

    @observed('literature.fulltext')
    async def fulltext(self,paper):
        return await self.primary.fulltext(paper)
