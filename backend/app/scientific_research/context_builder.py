"""Small report contexts retaining provenance, uncertainty and task constraints."""
from datetime import datetime, timezone


def evidence_packet(result, ids=None, *, limit=8):
    allowed=set(ids) if ids is not None else None
    papers={p['paper_id']:p for p in result['papers']}
    claims=[c for c in result['claims'] if allowed is None or c['evidence_id'] in allowed]
    # Interleave papers so one long paper cannot crowd every other source out.
    groups={pid:[c for c in claims if c['paper_id']==pid] for pid in papers}
    ordered=[]
    while any(groups.values()) and len(ordered)<limit:
        for group in groups.values():
            if group and len(ordered)<limit: ordered.append(group.pop(0))
    return [{'evidence_id':c['evidence_id'],'paper_id':c['paper_id'],
             'title':papers[c['paper_id']]['title'][:300],
             'published_at':papers[c['paper_id']].get('published_at'),
             'venue':papers[c['paper_id']].get('venue','')[:300],
             'source_url':papers[c['paper_id']].get('source_url','')[:500],'text':c['text'][:600],
             'quote':c['quote'][:1200],'page':c['page'],'access_level':c['access_level'],
             'kind':c['kind'],'verification_status':c['verification_status']} for c in ordered]


def report_context(result):
    directions=[]
    for d in result.get('directions',[])[:3]:
        directions.append({k:(v[:600] if isinstance(v,str) else v[:4] if isinstance(v,list) and k!='evidence_ids' else v)
                           for k,v in d.items() if k in {'question','hypothesis','minimal_experiment','baselines','metrics','risks','evidence_ids','compute_requirements'}})
    notes=[{k:(v[:600] if isinstance(v,str) else v) for k,v in n.items()} for n in result.get('paper_notes',[])[:3]]
    return {'as_of_date':(result.get('created_at') or datetime.now(timezone.utc).date().isoformat())[:10],
            'trend_coverage':result.get('trend_coverage'),'task_spec':result.get('task_spec'),'brief':result['brief'],'findings':result.get('findings',[])[:5],
            'directions':directions,'paper_notes':notes}



def section_progress(outline,drafts,current_id):
    """Bounded writing continuity; prior prose is never a new evidence source."""
    progress=[]
    for plan in outline:
        sid=plan['section_id']
        if sid==current_id: continue
        draft=drafts.get(sid,{})
        written=draft.get('status')=='written'
        text=' '.join(p['text'] for p in draft.get('paragraphs',[])[:2]) if written else ''
        progress.append({'section_id':sid,'question':plan['question'][:300],
                         'status':'written' if written else 'planned','completed_summary':text[:240],
                         'usage':'structure_only_not_evidence'})
    return progress
