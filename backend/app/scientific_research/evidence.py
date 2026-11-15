"""Quote location validates provenance, not semantic entailment."""
import hashlib
import re
from .models import Paper, ExtractedClaim
from .documents import document_hash


def issue(code, target='', detail=''):
    return {'code': code, 'target': target, 'detail': detail}


def normalize(text):
    return re.sub(r'\s+', ' ', text).strip()


def validate_extraction(paper: Paper, payload: dict):
    accepted, issues = [], []
    pages = {p.number: p.text for p in paper.pages}
    candidates = payload.get('claims', [])
    if not isinstance(candidates, list):
        return [], [issue('invalid_extraction', paper.paper_id)]
    for raw in candidates[:30]:
        try:
            claim = ExtractedClaim.model_validate(raw)
        except (ValueError, TypeError):
            issues.append(issue('invalid_claim', paper.paper_id))
            continue
        if paper.access_level == 'abstract' and claim.kind != 'author_claim':
            issues.append(issue('abstract_scope_violation', paper.paper_id))
            continue
        if claim.page not in pages or normalize(claim.quote) not in normalize(pages[claim.page]):
            issues.append(issue('unlocated_quote', paper.paper_id))
            continue
        digest = document_hash(paper)
        eid = hashlib.sha256(f'{paper.paper_id}:{digest}:{claim.page}:{normalize(claim.quote)}:{claim.kind}:{claim.text}'.encode()).hexdigest()[:24]
        accepted.append({**claim.model_dump(), 'evidence_id': eid, 'paper_id': paper.paper_id,
                         'document_hash': digest, 'access_level': paper.access_level,
                         'location_type': 'abstract_segment' if paper.access_level == 'abstract' else 'pdf_page',
                         'verification_status': 'quote_located_semantics_unverified'})
    unique = {c['evidence_id']: c for c in accepted}
    return list(unique.values()), issues
