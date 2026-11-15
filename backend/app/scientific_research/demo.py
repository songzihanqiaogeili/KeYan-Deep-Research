"""Synthetic data only: exercises orchestration, never pretends to be research."""
import asyncio
from .models import Brief, Paper, Page


def demo_input():
    return Brief(topic='多 Agent 长期记忆：合成流程演示', constraints='Single GPU; two months'), [
        Paper(paper_id='synthetic-a', title='Synthetic memory study A (not a real paper)',
              pages=[Page(number=1, text='In this synthetic example, shared memory improves retrieval on task A.')]),
        Paper(paper_id='synthetic-b', title='Synthetic memory study B (not a real paper)',
              pages=[Page(number=1, text='In this synthetic example, retrieval costs increase with the number of agents.')]),
    ]


class DemoModel:
    fixture = True

    async def complete(self, role, system, context):
        await asyncio.sleep(0.01)
        if role == 'outliner':
            ids=[c['evidence_id'] for c in context.get('evidence',[])]
            return {'sections':[{'section_id':sid,'question':'合成演示：本节应回答的研究问题',
                'main_point':'合成材料仅用于验证工作流程，不形成实际科研结论。','evidence_ids':ids}
                for sid in ('decision','comparison','papers','next_steps')]}
        if role in {'section_writer','section_reviser'}:
            ids=[c['evidence_id'] for c in context.get('evidence',[])]
            examples={
                'decision':('inference','这组虚构材料演示一个选题思路：考察共享记忆的收益，是否只是额外检索与计算带来的。示例 A 描述收益，示例 B 描述开销，因此需要把效果与成本放在相同预算下比较。'),
                'comparison':('inference','直接增加记忆容量与在固定预算下改进记忆策略，回答的是不同问题。后者需要控制调用次数、检索量和任务难度。当前合成材料没有这些对照，无法判断哪条路线更有效。'),
                'papers':('fact','虚构示例 A 用来演示从“共享记忆可能改善检索”的主张提出问题；虚构示例 B 则提醒读者关注 Agent 数量增加后的成本。它们在报告结构中分别承担收益依据与成本约束的角色，两者都不是真实可引用的论文。'),
                'next_steps':('proposal','若后续换成真实论文与任务，可先固定模型、任务集和调用预算，对比无共享记忆与共享记忆两组，同时记录任务成功率和调用成本。若等预算下优势消失，就暂不支持“记忆机制本身带来收益”的解释，先检查成本差异。')}
            kind,text=examples[context['section']['section_id']]
            return {'paragraphs':[{'text':text,'kind':kind,'evidence_ids':ids[:2]},
                {'text':'以上仅用于体验研究报告的论证结构；合成材料不能支撑真实科研结论或论文推荐。',
                 'kind':'limitation','evidence_ids':[]}]}
        if role == 'report_reviewer':
            return {'findings':[]}
        if role == 'reader':
            page = context['paper']['pages'][0]
            return {'claims': [{'text': page['text'], 'kind': 'author_claim', 'quote': page['text'], 'page': page['number']}]}
        ids = [c['evidence_id'] for c in context.get('claims', [])]
        if role=='paper_profiler':
            e=context['evidence'][0]['evidence_id'];f=lambda t:{'text':t,'evidence_ids':[e]}
            return {'branch':'合成记忆机制示例','relevance':'direct','problem':f('合成资料演示共享记忆的收益和成本问题。'),'method':f('通过虚构案例展示如何比较记忆机制。'),'contribution':f('作者陈述仅作为演示输入，不是真实研究成果。'),'reading_value':f('用于体验逐篇证据解读和引用回查。'),'next_question':None}
        if role == 'synthesizer':
            return {'findings': [{'text': '合成示例展示收益与开销需要同时评估；这不是实际科研发现。', 'evidence_ids': ids}], 'gaps': [],
                    'paper_notes':[{'paper_id':pid,'title_zh':'合成文献阅读示例','why_read':'用于演示如何从作者主张追溯原文，不构成真实阅读推荐。','relevance':'展示研究收益与成本需要分别核对的思路。','limitation':'合成材料不能支持实际科研判断。','evidence_ids':[c['evidence_id'] for c in context['claims'] if c['paper_id']==pid]} for pid in dict.fromkeys(c['paper_id'] for c in context['claims'])]}
        if role == 'proposer':
            return {'directions': [{'question': '合成示例：共享记忆收益是否来自额外计算？',
                'hypothesis': '在等预算下仍可能存在收益，需真实实验验证。', 'evidence_ids': ids,
                'minimal_experiment': '固定调用次数，对比无记忆与共享记忆；这里不运行实验。',
                'baselines': ['无记忆', '共享记忆'], 'metrics': ['任务成功率', '调用成本'],
                'risks': ['合成资料不能支持实际科研结论'], 'falsification_criteria': '等预算下没有收益',
                'compute_requirements': '需基于真实任务测量，本演示不提供资源估算'}]}
        return {'issues': []}
