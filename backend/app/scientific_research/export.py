"""Portable report; always expose evidence and research boundaries."""


def requirement_markdown(result):
    spec=result.get('task_spec');delivery=result.get('delivery')
    if not spec or not delivery: return []
    policies={'any':'不限发表形式','prefer_journal':'优先期刊','journal_only':'仅期刊记录','verified_top_only':'必须核验顶刊资格'}
    lines=['## 任务条件与资料范围','',delivery['summary'],
           '- 发表条件：'+policies[spec['publication_policy']],
           '- 年份硬条件：'+str(spec.get('year_from') or '不限')+' — '+str(spec.get('year_to') or '不限'),
           '- 通过元数据硬条件的参考：'+str(delivery['qualified_count'])+' / '+str(delivery['requested_count']),
           '- 资料范围：'+delivery['evidence_scope'],
           '- 科研结论/创新性：未核验','']
    if delivery['resource_status']=='unverified': lines+=['- 资源与周期可行性：未核验','']
    for text in delivery.get('preferences_pending',[]): lines+=['- 偏好待确认：'+text]
    if delivery['screening']:
        lines+=['','### 候选条件核验','']
        for row in delivery['screening']: lines+=['- '+row['title']+'：'+row['status']+'；'+'；'.join(row['reasons'])]
    return lines+['']


def markdown(result: dict) -> str:
    if result.get('report'):
        report=result['report']
        lines=[f"# {report['title']}", '', f"状态：{report['status']}", '']
        if result.get('synthetic_fixture'): lines+=['> 合成测试演示，不可作为实际科研结论。','']
        if result.get('seed_documents'):
            lines+=['## 研究起点','']+[p['title'] for p in result['seed_documents']]+['关联基于文本内容比较，未核实引用图关系。','']
        lines+=requirement_markdown(result)
        c=result.get('trend_coverage')
        if c:lines+=['## 调研样本覆盖','',f"候选 {c['candidate_count']} 条；分析 {c['analyzed_count']} 篇；全文 {c['fulltext_count']} 篇。",c['scope'],'']
        for section in report['sections']:
            lines += [f"## {section['title']}",'']
            for paragraph in section.get('paragraphs',[]):
                lines += [paragraph['text'], '证据：'+', '.join(paragraph['evidence_ids']) if paragraph['evidence_ids'] else '', '']
            if not section.get('paragraphs'): lines += [section.get('message','本节未完成。'),'']
        lines += ['## 参考文献','']
        for paper in result['papers']: lines += [f"- {paper['title']} — {paper.get('source_url','')}，{paper['access_level']}"]
        lines += ['', '## 报告边界', '', report['scope']]
        if report.get('review_findings'): lines += ['', '## 模型审核意见（可能有误，须对照原文）', '']
        for finding in report.get('review_findings',[]): lines += [f"- {finding['section_id']}：{finding['detail']}"]
        if result.get('argument_ledger'):
            lines+=['','## 论点与证据清单','']
            for row in result['argument_ledger']:lines+=[row['text']+' — '+row['support_status'],'证据：'+', '.join(row['evidence_ids'])]
        return '\n'.join(lines)+'\n'
    lines = [f"# {result['brief']['topic']}", '', f"状态：{result['status']}", '']
    if result.get('synthetic_fixture'):
        lines += ['> 合成测试演示：以下内容不是实际论文分析，不可作为科研结论。', '']
    lines += requirement_markdown(result)
    lines += ['## 分析范围与限制', '']
    lines += [f'- {s}' for s in result.get('limitations', [])]
    lines += ['', '## 方法与问题分析', '']
    for finding in result.get('findings', []):
        lines += [finding['text'], f"证据：{', '.join(finding['evidence_ids'])}", '']
    lines += ['## 候选研究缺口（尚待验证）', '']
    for gap in result.get('gaps', []):
        lines += [gap['text'], f"证据：{', '.join(gap['evidence_ids'])}", '']
    lines += ['## 方向候选（查新状态见各候选，不保证创新）', '']
    for d in result.get('directions', []):
        lines += [f"### {d['question']}", '', f"假设：{d['hypothesis']}", f"最小实验：{d['minimal_experiment']}",
                  f"基线：{'; '.join(d['baselines'])}", f"指标：{'; '.join(d['metrics'])}",
                  f"资源：{d['compute_requirements']}", f"风险：{'; '.join(d['risks'])}",
                  f"否定条件：{d['falsification_criteria']}", f"证据：{', '.join(d['evidence_ids'])}", '']
        lines += [f"相似工作查询状态：{d.get('novelty_check_status', 'not_searched')}", '']
        for work in d.get('similar_work', []):
            lines += [f"- {work['title']} — {work['source_url']}"]
    lines += ['## 原文定位与证据', '']
    for c in result.get('claims', []):
        location = '摘要片段（不是 PDF 页码）' if c['access_level'] == 'abstract' else f"物理页 {c['page']}"
        lines += [f"- [{c['evidence_id']}] {c['paper_id']}，{location}，{c['access_level']}，{c['kind']}",
                  f"  判断：{c['text']}", f"  原文：{c['quote']}", '']
    lines += ['## 未解决问题', '']
    lines += [f"- {i['code']}：{i.get('target', '')} {i.get('detail', '')}" for i in result.get('issues', [])]
    if result.get('search_audit'):
        import json
        lines += ['', '## 检索记录与范围', '', '```json', json.dumps(result['search_audit'], ensure_ascii=False, indent=2), '```']
    return '\n'.join(lines) + '\n'
