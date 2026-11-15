"""Deterministic report diagnostics; semantic quality needs bound human labels."""
import re
from .documents import document_hash
from .evidence import normalize
from .quality import conflicts, excluded_topics
from .tracing import digest


def ratio(passed, total, *, status=None):
    return {'passed': passed, 'total': total, 'rate': passed / total if total else None,
            'status': status or ('measured' if total else 'not_applicable')}


def annotation_hash(result):
    """Bind labels to exact report content; timing and run UUID are deliberately excluded."""
    return digest({key: result.get(key) for key in ('brief', 'papers', 'claims', 'findings', 'gaps', 'directions',
                   'paper_notes', 'status', 'issues', 'limitations', 'search_plan', 'search_audit', 'synthetic_fixture')})


def evaluate_result(result, source_papers, brief, *, annotation=None, required_questions=()):
    source = {p.paper_id: p for p in source_papers}
    claims = result.get('claims', [])
    known = {c.get('evidence_id') for c in claims}
    located = 0
    for claim in claims:
        paper = source.get(claim.get('paper_id'))
        if not paper:
            continue
        pages = {p.number: p.text for p in paper.pages}
        quote = claim.get('quote', '')
        if (isinstance(quote, str) and quote.strip() and claim.get('page') in pages
                and normalize(quote) in normalize(pages[claim['page']])
                and claim.get('document_hash') == document_hash(paper)
                and claim.get('access_level') == paper.access_level):
            located += 1
    statements = [item for key in ('findings', 'gaps', 'directions', 'paper_notes') for item in result.get(key, [])]
    referenced = sum(bool(item.get('evidence_ids')) and set(item['evidence_ids']).issubset(known) for item in statements)
    violations = []
    terms = excluded_topics(brief)
    for index, direction in enumerate(result.get('directions', [])):
        hits = conflicts(direction, terms)
        if hits:
            violations.append({'type': 'excluded_topic', 'direction': index, 'terms': hits})
    text = brief.topic + ' ' + brief.constraints
    years = re.findall(r'(?<!\d)((?:19|20)\d{2}|\d{2})年', text)
    years = [int(y) if len(y) == 4 else 2000 + int(y) for y in years]
    if years:
        for paper in result.get('papers', []):
            date = paper.get('published_at') or ''
            year = int(date[:4]) if re.match(r'^\d{4}', date) else None
            if year is None or not min(years) <= year <= max(years):
                violations.append({'type': 'year_unverified_or_outside', 'paper_id': paper['paper_id']})
    applicable = bool(terms or years)
    semantic = ratio(0, 0, status='needs_annotation')
    coverage = ratio(0, 0, status='needs_annotation')
    readability = actionability = task_success = None
    if annotation is not None:
        if annotation.get('result_hash') != annotation_hash(result):
            raise ValueError('Annotation does not match this report')
        checks = annotation.get('claim_checks', [])
        seen = set()
        for check in checks:
            if check.get('evidence_id') not in known or check['evidence_id'] in seen or type(check.get('supported')) is not bool:
                raise ValueError('Invalid or duplicate claim annotation')
            seen.add(check['evidence_id'])
        semantic = ratio(sum(c['supported'] for c in checks), len(checks))
        answered = annotation.get('question_checks', {})
        if not set(answered).issubset(set(required_questions)) or any(type(v) is not bool for v in answered.values()):
            raise ValueError('Invalid question annotation')
        coverage = ratio(sum(answered.values()), len(required_questions),
                         status='measured' if len(answered) == len(required_questions) else 'partial_annotation')
        if len(answered) < len(required_questions):
            coverage['rate'] = None
        for name in ('readability', 'actionability'):
            value = annotation.get(name)
            if value is not None and (type(value) is not int or not 0 <= value <= 4):
                raise ValueError('Rubric rating must be an integer in 0..4')
        readability, actionability = annotation.get('readability'), annotation.get('actionability')
        task_success = annotation.get('task_success')
        if task_success is not None and type(task_success) is not bool:
            raise ValueError('task_success requires a human boolean label')
    signals = []
    if located < len(claims) or referenced < len(statements):
        signals.append('evidence_integrity')
    if violations:
        signals.append('requirement_violation')
    if not result.get('directions'):
        signals.append('no_direction_produced')
    return {'workflow_status': result.get('status'), 'has_direction': bool(result.get('directions')),
            'task_success': task_success, 'result_hash': annotation_hash(result),
            'hard_constraints': {'applicable': applicable, 'passed': not violations if applicable else None,
                                 'violations': violations,
                                 'checked_dimensions': ['explicit_topic_exclusion', 'publication_year'],
                                 'not_checked': ['journal_rank', 'resource_feasibility', 'semantic_requirement_satisfaction']},
            'quote_location': ratio(located, len(claims)),
            'evidence_reference': ratio(referenced, len(statements)),
            'semantic_support': semantic, 'question_coverage': coverage,
            'semantic_support_scope': 'human-checked extracted claims only; not whole-report scientific validity',
            'readability': readability, 'actionability': actionability,
            'model_calls': result.get('metrics', {}).get('model_calls'),
            'diagnostic_signals': signals,
            'attribution_status': 'signals_only_not_causal_attribution'}


def summarize(scores):
    def average(name):
        values = [score[name]['rate'] for score in scores if score[name]['rate'] is not None]
        return sum(values) / len(values) if values else None
    applicable = [s for s in scores if s['hard_constraints']['applicable']]
    success = [s['task_success'] for s in scores if s.get('task_success') is not None]
    return {'cases': len(scores), 'reports_with_directions': sum(s['has_direction'] for s in scores),
            'hard_constraint_cases': len(applicable),
            'hard_constraint_pass_rate': sum(s['hard_constraints']['passed'] for s in applicable) / len(applicable) if applicable else None,
            'constraint_scope': 'explicit topic exclusions and publication years only; no journal-rank verification',
            'quote_location_rate': average('quote_location'),
            'evidence_reference_rate': average('evidence_reference'),
            'semantic_support_rate': average('semantic_support'),
            'human_scored_cases': len(success), 'task_success_rate': sum(success) / len(success) if success else None,
            'warning': 'Location and reference validity do not measure semantic support or scientific value.'}
