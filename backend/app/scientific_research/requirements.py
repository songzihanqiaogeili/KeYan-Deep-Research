"""Task requirements and auditable metadata gates. No model can certify journal rank."""
import re
from datetime import date
from typing import Literal
from pydantic import Field
from .models import Brief,Paper,StrictModel
from .quality import excluded_topics,conflicts

SOFT=r'优先|最好|尽量|prefer|ideally'
TOP=r'顶刊|顶级期刊|顶尖期刊|top[- ]?(?:tier )?journal'
HARD=r'必须|仅限|只要|只看|一定|要求|发表刊物要'

class ResearchSpec(StrictModel):
    version: int = 3
    as_of_date: str = Field(default_factory=lambda:date.today().isoformat())
    research_mode: str = 'focused'
    search_mode: str = 'topic'
    venue_catalog: list[dict] = Field(default_factory=list)
    topic: str
    year_from: int | None = None
    year_to: int | None = None
    preferred_years: list[int] = Field(default_factory=list)
    publication_policy: Literal['any','prefer_journal','journal_only','verified_top_only']
    rank_requested: bool = False
    target_papers: int
    excluded_topics: list[str] = Field(default_factory=list)
    resource_constraints: str = ''
    interpretation_notes: list[str] = Field(default_factory=list)


def build_spec(brief: Brief) -> ResearchSpec:
    text=brief.topic+'；'+brief.constraints
    clauses=re.split(r'[，,。；;\n]',text)
    years=[];preferred=[]
    for clause in clauses:
        found=[]
        for match in re.finditer(r'(?<!\d)((?:19|20)\d{2})\s*年?\s*[-—–~至到]\s*((?:19|20)\d{2})\s*年?',clause):
            if int(match.group(1))>int(match.group(2)): raise ValueError('年份范围起点不能晚于终点。')
            found.extend([int(match.group(1)),int(match.group(2))])
        if not found:
            found=[int(y) if len(y)==4 else 2000+int(y) for y in re.findall(r'(?<!\d)((?:19|20)\d{2}|\d{2})\s*年',clause)]
        first_year=re.search(r'(?<!\d)(?:19|20)\d{2}|(?<!\d)\d{2}年',clause)
        prefix=clause[:first_year.start()] if first_year else clause
        modalities=list(re.finditer('(?:'+SOFT+')|(?:'+HARD+')',prefix,re.I))
        soft=bool(modalities and re.fullmatch(SOFT,modalities[-1].group(),re.I))
        if soft: preferred.extend(found)
        else: years.extend(found)
    structured=brief.year_from is not None or brief.year_to is not None
    low=brief.year_from if structured else min(years) if years else None
    high=brief.year_to if structured else max(years) if years else None
    positive=[c for c in clauses if re.search(TOP,c,re.I) and not re.search(r'不要求|不需要|不必|无需|不能.*宣称|不得.*宣称|不是.*硬|没有.*依据',c)]
    notes=[];policy=brief.publication_policy
    if policy=='auto':
        if any(re.search('(?:'+HARD+r')(?:(?!(?:'+SOFT+r')).){0,18}(?:'+TOP+')',c,re.I) for c in positive): policy='verified_top_only'
        elif re.search(r'(?:必须|仅限|只要|只看)(?:(?!(?:优先|最好|尽量)).){0,12}期刊|排除预印本|不要预印本',text): policy='journal_only'
        elif positive:
            policy='prefer_journal' if any(re.search(SOFT,c,re.I) for c in positive) else 'verified_top_only'
            if policy=='verified_top_only': notes.append('顶刊请求已按必须核验解读；如仅为偏好，可在发表条件中明确调整。')
        elif re.search(r'(?:必须|仅限|只要|只看)(?:(?!(?:优先|最好|尽量)).){0,12}期刊|排除预印本|不要预印本',text): policy='journal_only'
        elif re.search(r'(?:'+SOFT+r').{0,10}期刊',text,re.I): policy='prefer_journal'
        else: policy='any'
    rank_requested=policy=='verified_top_only' or (policy in {'prefer_journal','journal_only'} and bool(positive))
    if rank_requested: notes.append('采用导入名单作条件匹配，来源真实性未独立核实。' if brief.venue_catalog else '当前未接入权威顶刊名单/分区核验，期刊级别不能自动确认为已满足。')
    resource=text if re.search(r'GPU|显卡|单卡|个月|两个月|预算|budget|single gpu',text,re.I) else ''
    return ResearchSpec(search_mode=brief.search_mode,as_of_date=brief.as_of_date or date.today().isoformat(),research_mode=brief.research_mode,venue_catalog=[r.model_dump() for r in brief.venue_catalog],topic=brief.topic,year_from=low,year_to=high,preferred_years=sorted(set(preferred)) if not structured else [],
        publication_policy=policy,rank_requested=rank_requested,target_papers=brief.target_papers,
        excluded_topics=excluded_topics(brief),resource_constraints=resource,interpretation_notes=notes)


def _data(value): return value.model_dump() if isinstance(value,Paper) else dict(value)


def assess_paper(paper,spec: ResearchSpec) -> dict:
    p=_data(paper);checks=[];codes=[]
    def add(name,label,status,strength,message,code=None):
        checks.append({'criterion':name,'label':label,'status':status,'strength':strength,'message':message})
        if code: codes.append(code)
    text=p.get('title','')+' '+ ' '.join(page.get('text','') for page in p.get('pages',[]))+' '+p.get('abstract','')
    if spec.excluded_topics:
        blocked=conflicts({'question':text},spec.excluded_topics)
        add('excluded_topics','排除主题','unmet' if blocked else 'met','required',
            '材料包含排除主题：'+', '.join(blocked) if blocked else '未发现明确排除关键词；仍需检查实际研究对象。','excluded_topic' if blocked else None)
    published=p.get('published_at') or '';year=None
    try:
        year=int(published) if re.fullmatch(r'(?:19|20)\d{2}',published) else date.fromisoformat(published[:10]).year
    except (ValueError,TypeError): pass
    if spec.year_from is not None or spec.year_to is not None:
        valid=year is not None and (spec.year_from is None or year>=spec.year_from) and (spec.year_to is None or year<=spec.year_to)
        add('year','发表年份','unverified' if year is None else 'met' if valid else 'unmet','required',
            '未获得有效发表年份。' if year is None else f'索引年份：{year}；按任务年份范围核对。',
            'year_unverified' if year is None else 'year_out_of_range' if not valid else None)
    elif spec.preferred_years:
        add('year','年份偏好','met' if year in spec.preferred_years else 'unverified' if year is None else 'unmet','preferred','年份属于偏好，不作为硬性淘汰条件。')
    try:
        future=date.fromisoformat(published[:10])>date.fromisoformat(spec.as_of_date)
    except (ValueError,TypeError):future=year is not None and year>int(spec.as_of_date[:4])
    if future:
        add('publication_date','发表截止日期','unverified','required',
            '索引日期晚于本次调研日期；需核对已在线发表版本，当前不作为已发表证据。','future_publication_date')
    kind=p.get('publication_type','unknown')
    if kind=='unknown' and p.get('arxiv_id'): kind='preprint'
    if spec.publication_policy in {'journal_only','prefer_journal','verified_top_only'}:
        strength='required' if spec.publication_policy in {'journal_only','verified_top_only'} else 'preferred'
        status='met' if kind=='journal' else 'unverified' if kind=='unknown' else 'unmet'
        add('publication_type','期刊记录',status,strength,
            '索引标为期刊记录；不等于已核验录用或级别。' if kind=='journal' else '当前是预印本/非期刊记录。' if kind!='unknown' else '发表形式缺少可核对元数据。',
            'publication_type_unverified' if kind=='unknown' and strength=='required' else 'journal_record_required' if status=='unmet' and strength=='required' else None)
    if spec.rank_requested:
        from .rankings import match_venue
        rank=match_venue(p,spec.venue_catalog)
        if rank is not None:
            add('journal_rank','指定名单资格','met' if rank['qualifies'] else 'unmet','required' if spec.publication_policy=='verified_top_only' else 'preferred',
                f"导入名单 {rank['system']} / {rank['version']} / {rank['label']}；{rank['source_url']}；未独立核实来源真实性，不等于论文质量证明。",None if rank['qualifies'] else 'rank_not_qualified')
        else:
            add('journal_rank','顶刊资格','unverified','required' if spec.publication_policy=='verified_top_only' else 'preferred',
            '未接入指定年度的权威名单，不能从刊名或出版社推断顶刊资格。','rank_unverified')
    required=[c for c in checks if c['strength']=='required']
    status='rejected' if any(c['status']=='unmet' for c in required) else 'unverified' if any(c['status']=='unverified' for c in required) else 'eligible'
    return {'paper_id':p['paper_id'],'title':p.get('title',''),'venue':p.get('venue',''),'published_at':p.get('published_at'),
            'publication_type':kind,'eligible':status=='eligible','status':status,'checks':checks,'reason_codes':codes,
            'reasons':[c['message'] for c in checks if c['status']!='met'] or ['可进入相关性分析；元数据条件通过不代表科学结论成立。']}


def assess_delivery(spec: ResearchSpec,selected,candidates=()) -> dict:
    corpus={p['paper_id']:p for p in map(_data,candidates)}
    chosen=list(map(_data,selected))
    corpus.update({p['paper_id']:p for p in chosen})
    screening=[assess_paper(p,spec) for p in corpus.values()]
    by_id={d['paper_id']:d for d in screening}
    qualified=[p for p in chosen if by_id[p['paper_id']]['eligible']]
    count=len(qualified)
    condition='met' if count>=spec.target_papers else 'partial' if count else 'unverified' if any(d['status']=='unverified' for d in screening) else 'unmet' if screening else 'no_matches'
    access={p.get('access_level','abstract') for p in qualified}
    scope='none' if not access else next(iter(access)) if len(access)==1 else 'mixed'
    labels={'met':'已获得可进入相关性分析的参考，仍需核验科研结论。','partial':'合格参考数量不足，不能宣称已满足全部要求。',
            'unverified':'候选的硬性条件尚未核验，暂不形成推荐。','unmet':'候选未满足硬性条件，暂不形成推荐。','no_matches':'本次没有获得可核对的候选资料，暂不形成推荐。'}
    return {'requirement_status':condition,'recommendation_status':'preliminary' if count else 'not_ready',
            'qualified_count':count,'requested_count':spec.target_papers,'evidence_scope':scope,
            'resource_status':'unverified' if spec.resource_constraints else 'not_specified',
            'scientific_validity_verified':False,'summary':labels[condition],
            'preferences_pending':list(dict.fromkeys(c['label']+'：'+c['message'] for d in screening if d['paper_id'] in {p['paper_id'] for p in qualified} for c in d['checks'] if c['strength']=='preferred' and c['status']!='met')),
            'screening':screening}



def no_source_report(spec,delivery):
    policy={'any':'不限发表形式','prefer_journal':'优先期刊','journal_only':'仅期刊记录','verified_top_only':'必须核验顶刊'}[spec['publication_policy']]
    reasons=list(dict.fromkeys(reason for d in delivery['screening'] for reason in d['reasons']))[:8]
    texts=[delivery['summary'],
           '发表条件：'+policy+'。本次找到 '+str(len(delivery['screening']))+' 条候选记录，能够进入推荐分析的材料为 0。',
           '；'.join(reasons) if reasons else '本次未取得可以核对的候选材料，不编造参考论文。',
           '请补充可核对的来源资料，或明确调整任务中的硬性条件后新建研究。'+('当前没有权威顶刊名单核验能力；不能把刊名、出版社或模型判断当作等级证明。' if spec.get('rank_requested') else '')]
    titles=['本次条件核验结果','哪些要求尚未满足','候选资料与核验边界','下一步如何继续']
    sections=[{'section_id':sid,'title':title,'status':'written','paragraphs':[{'text':text,'kind':'limitation','evidence_ids':[]}]} for sid,title,text in zip(('decision','comparison','papers','next_steps'),titles,texts)]
    return {'title':'科研任务条件核验结果','status':'partial','sections':sections,'review_findings':[],
            'review_completed':False,'issues':[{'code':'requirements_not_satisfied','detail':'未调用模型写作，不构成论文推荐。'}],
            'scope':'本次交付的是条件核验结果；没有通过硬性条件的来源，不形成科研建议。'}
