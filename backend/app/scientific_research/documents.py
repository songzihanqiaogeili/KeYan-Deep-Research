"""Local document import and conservative work-level deduplication."""
import hashlib
import re
from pathlib import Path
from .models import Paper, Page


def document_hash(paper: Paper) -> str:
    payload = '\n'.join(f'{p.number}\0{p.text}' for p in paper.pages)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def deduplicate(papers: list[Paper]) -> list[Paper]:
    ids, aliases = {}, {}
    parents = list(range(len(papers)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, paper in enumerate(papers):
        fingerprint = document_hash(paper)
        if paper.paper_id in ids and ids[paper.paper_id] != fingerprint:
            raise ValueError(f'conflicting paper_id: {paper.paper_id}')
        ids[paper.paper_id] = fingerprint
        doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', paper.doi or '', flags=re.I).lower().strip()
        arxiv = re.sub(r'v\d+$', '', paper.arxiv_id or '')
        keys = [('content', fingerprint)]
        if doi:
            keys.append(('doi', doi))
        if arxiv:
            keys.append(('arxiv', arxiv))
        for key in keys:
            if key in aliases:
                left, right = root(index), root(aliases[key])
                parents[max(left, right)] = min(left, right)
            aliases[key] = index

    def preference(paper):
        match = re.search(r'v(\d+)$', paper.arxiv_id or '')
        return paper.access_level == 'fulltext', int(match.group(1)) if match else 0

    groups = {}
    for index, paper in enumerate(papers):
        key = root(index)
        if key not in groups or preference(paper) > preference(groups[key]):
            groups[key] = paper
    return list(groups.values())


def merge_materials(papers: list[Paper]) -> list[Paper]:
    """Upgrade a known work's abstract to fulltext before strict ID collision checks."""
    selected={}
    for paper in papers:
        old=selected.get(paper.paper_id)
        if old and document_hash(old)!=document_hash(paper):
            arxiv=lambda p:re.sub(r'v\d+$','',p.arxiv_id or '')
            doi=lambda p:re.sub(r'^https?://(?:dx\.)?doi\.org/','',p.doi or '',flags=re.I).lower().strip()
            known_work=(arxiv(old) and arxiv(old)==arxiv(paper)) or (doi(old) and doi(old)==doi(paper))
            if not known_work or old.access_level==paper.access_level:
                raise ValueError(f'conflicting paper_id: {paper.paper_id}')
            if old.access_level=='fulltext':
                continue
        selected[paper.paper_id]=paper
    return deduplicate(list(selected.values()))


def load_pdf(path: Path, *, title: str | None = None) -> Paper:
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError('PDF exceeds 25 MiB')
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError('encrypted PDF is unsupported')
    if len(reader.pages) > 500:
        raise ValueError('PDF exceeds 500 pages')
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or '').strip()
        except KeyError:  # blank PDF pages can have no /Contents
            text = ''
        if text:
            pages.append(Page(number=number, text=text))
    if not pages:
        raise ValueError('No extractable text; scanned PDFs require OCR')
    content_id = hashlib.sha256(path.read_bytes()).hexdigest()[:20]
    return Paper(paper_id=f'pdf-{content_id}', title=title or path.stem, pages=pages)
