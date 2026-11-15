"""Exact membership in user supplied, versioned venue catalogs, never inferred rank."""
import re

def match_venue(paper,catalog):
    norm=lambda s:re.sub(r'\s+',' ',s.strip()).casefold()
    issns={s.replace('-','').upper() for s in paper.get('issns',[])}
    matches=[]
    for rule in catalog:
        keys={s.replace('-','').upper() for s in rule.get('issns',[])}
        same=bool(issns&keys) if issns and keys else norm(paper.get('venue',''))==norm(rule['venue'])
        if same:matches.append(rule)
    if not matches:return None
    # Conflicting imported decisions are not silently resolved in favour of acceptance.
    if len({r['qualifies'] for r in matches})>1:return None
    return matches[0]
