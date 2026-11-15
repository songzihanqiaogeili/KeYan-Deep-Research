"""Bounded seed-paper excerpts, not instructions or verified citation edges."""
import re
from .models import Paper
from .documents import document_hash

def seed_context(values):
    papers=[p if isinstance(p,Paper) else Paper.model_validate(p) for p in values]
    rows=[]
    for paper in papers[:3]:
        remaining=3000;pages=[]
        for page in paper.pages[:3]:
            text=page.text[:min(1200,remaining)]
            if text:pages.append({'number':page.number,'text':text});remaining-=len(text)
            if remaining<=0:break
        rows.append({'paper_id':paper.paper_id,'title':paper.title,'source_url':paper.source_url,'document_hash':document_hash(paper),'access_level':paper.access_level,'pages':pages,'trust':'untrusted_source_text'})
    return rows

def header_identifiers(paper):
    header=paper.pages[0].text[:2000]
    dois=set(re.findall(r'(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s<>]+)',header,re.I))
    arxivs=set(re.findall(r'arxiv\s*:\s*(\d{4}\.\d{4,5}(?:v\d+)?)',header,re.I))
    return {'doi':next(iter(dois)).rstrip('.,;') if len(dois)==1 else None,'arxiv_id':next(iter(arxivs)) if len(arxivs)==1 else None}

def same_seed_work(paper,seeds):
    norm=lambda d:re.sub(r'^https?://(?:dx[.])?doi[.]org/','',d or '',flags=re.I).lower().strip()
    arxiv=lambda d:re.sub(r'v\d+$','',d or '')
    for seed in seeds:
        if paper.paper_id==seed.paper_id or document_hash(paper)==document_hash(seed):return True
        ident=header_identifiers(seed)
        if norm(paper.doi) and norm(paper.doi)==norm(seed.doi or ident['doi']):return True
        if arxiv(paper.arxiv_id) and arxiv(paper.arxiv_id)==arxiv(seed.arxiv_id or ident['arxiv_id']):return True
    return False
