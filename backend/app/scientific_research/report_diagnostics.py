"""Inspectable structural warnings; deliberately not a scientific quality score."""
import re

def diagnose_report(result):
    known={c['evidence_id']:c.get('paper_id') for c in result.get('claims',[])}
    sections=[];seen={};warnings=[];all_ids=set()
    for section in (result.get('report') or {}).get('sections',[]):
        sid=section['section_id'];ids=set();characters=0
        for p in section.get('paragraphs',[]):
            text=p.get('text','');characters+=len(text);ids.update(p.get('evidence_ids',[]))
            normalized=re.sub(r'\W+','',text.casefold())
            if len(normalized)>=80:
                if normalized in seen and seen[normalized]!=sid:
                    warnings.append({'code':'repeated_cross_section_prose','section_id':sid,'also_in':seen[normalized]})
                seen[normalized]=sid
        all_ids.update(ids)
        sections.append({'section_id':sid,'characters':characters,'citation_count':len(ids),
                         'source_count':len({known[i] for i in ids if i in known})})
    papers=result.get('papers',[])
    if papers and not any(p.get('access_level')=='fulltext' for p in papers):
        warnings.append({'code':'abstract_only_scope','detail':'摘要资料不能完整核验实验或领域缺口。'})
    return {'sections':sections,'cited_source_count':len({known[i] for i in all_ids if i in known}),
            'fulltext_papers':sum(p.get('access_level')=='fulltext' for p in papers),
            'warnings':warnings,'semantic_quality_verified':False,'scope':'structure_and_source_coverage_only'}
