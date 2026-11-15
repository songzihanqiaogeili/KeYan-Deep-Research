"""Deterministic checks for explicit exclusions; not a semantic novelty judge."""
import re

def excluded_topics(brief):
    terms=list(brief.excluded_topics)
    text=brief.topic+' '+brief.constraints
    if re.search(r'pm\s*2[.．]?\s*5',text,re.I) and re.search(r'排除|不做|不要|不考虑|换.{0,6}方向|换.{0,6}领域|不行|exclude|avoid',text,re.I):
        terms.append('PM2.5')
    return list(dict.fromkeys(terms))

def conflicts(direction, terms):
    text=' '.join(str(direction.get(k,'')) for k in ('question','hypothesis','minimal_experiment','baselines','metrics'))
    compact=re.sub(r'\s+','',text).casefold().replace('．','.')
    return [term for term in terms if re.sub(r'\s+','',term).casefold().replace('．','.') in compact]
