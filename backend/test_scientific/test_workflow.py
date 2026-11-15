import asyncio
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.models import Brief, Paper, Page
from scientific_research.workflow import ResearchWorkflow
from scientific_research.export import markdown


class FixtureModel:
    fixture = True

    def __init__(self, fail=None, forged=False):
        self.active = self.peak = 0
        self.fail, self.forged = fail, forged
        self.contexts = []
        self.systems = []

    async def complete(self, role, system, context):
        self.contexts.append((role, context))
        self.systems.append((role, system))
        if role == 'reader':
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.01)
                if context['paper']['paper_id'] == self.fail:
                    raise ValueError('fixture reader failure')
                return {'claims': [{'text': 'Author reports a finding', 'kind': 'author_claim', 'quote': context['paper']['pages'][0]['text'], 'page': 1}]}
            finally:
                self.active -= 1
        ids = [c['evidence_id'] for c in context.get('claims', [])]
        if role == 'synthesizer':
            return {'findings': [{'text': 'A limited-corpus finding', 'evidence_ids': ids}], 'gaps': []}
        if role == 'proposer':
            return {'directions': [{'question': 'Does retrieval generalize?', 'hypothesis': 'It may generalize', 'evidence_ids': ['forged'] if self.forged else ids,
                'minimal_experiment': 'Compare held-out tasks with fixed budget', 'baselines': ['no memory'], 'metrics': ['success rate'],
                'risks': ['small corpus'], 'falsification_criteria': 'No improvement at equal budget', 'compute_requirements': 'Unknown; measure first'}]}
        return {'issues': []}


def papers(n=4):
    return [Paper(paper_id=f'p{i}', title=f'Paper {i}', pages=[Page(number=1, text=f'Finding {i} is reported.')]) for i in range(n)]


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_parallelism_stable_merge_and_skill_injection(self):
        model = FixtureModel()
        result = await ResearchWorkflow(model).run(Brief(topic='memory', max_concurrency=2), papers())
        self.assertEqual(model.peak, 2)
        self.assertEqual([c['paper_id'] for c in result['claims']], ['p0', 'p1', 'p2', 'p3'])
        self.assertTrue(result['synthetic_fixture'])
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(all('---' in system for _, system in model.systems))
        self.assertEqual(result['directions'][0]['novelty_check_status'], 'not_searched')
        self.assertIn('原文定位', markdown(result))
        result['gaps'] = [{'text': 'A candidate gap, not proven novelty', 'evidence_ids': [result['claims'][0]['evidence_id']]}]
        self.assertIn('A candidate gap, not proven novelty', markdown(result))
        json.dumps(result)

    async def test_one_reader_failure_does_not_discard_other_evidence(self):
        result = await ResearchWorkflow(FixtureModel(fail='p1')).run(Brief(topic='x'), papers())
        self.assertEqual(len(result['claims']), 3)
        self.assertEqual(result['status'], 'degraded')
        self.assertTrue(any(i['code'] == 'reader_failed' for i in result['issues']))

    async def test_unknown_direction_evidence_rejected(self):
        result = await ResearchWorkflow(FixtureModel(forged=True)).run(Brief(topic='x'), papers(1))
        self.assertEqual(result['directions'], [])
        self.assertEqual(result['status'], 'degraded')

    async def test_budget_exhaustion_is_explicit(self):
        result = await ResearchWorkflow(FixtureModel()).run(Brief(topic='x', max_calls=1, max_concurrency=1), papers(2))
        self.assertEqual(result['metrics']['model_calls'], 1)
        self.assertEqual(result['status'], 'degraded')
        self.assertTrue(any(i['code'] == 'call_budget_exhausted' for i in result['issues']))

    async def test_reviewer_gets_no_raw_documents(self):
        model = FixtureModel()
        await ResearchWorkflow(model).run(Brief(topic='x'), papers(1))
        ctx = next(c for role, c in model.contexts if role == 'reviewer')
        self.assertNotIn('papers', ctx)
        self.assertNotIn('pages', ctx)

    async def test_empty_corpus_fails_without_calling_model(self):
        result = await ResearchWorkflow(FixtureModel()).run(Brief(topic='x'), [])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['metrics']['model_calls'], 0)

    async def test_external_cancellation_propagates(self):
        task = asyncio.create_task(ResearchWorkflow(FixtureModel()).run(Brief(topic='x'), papers()))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_timeout_preserves_completed_reader_evidence(self):
        class SlowSynthesis(FixtureModel):
            async def complete(self, role, system, context):
                if role == 'synthesizer':
                    await asyncio.sleep(3)
                return await super().complete(role, system, context)
        result = await ResearchWorkflow(SlowSynthesis()).run(Brief(topic='x', timeout_seconds=1), papers(1))
        self.assertEqual(len(result['claims']), 1)
        self.assertEqual(result['status'], 'degraded')
        self.assertTrue(any(i['code'] == 'run_timeout' for i in result['issues']))

    async def test_oversized_aggregate_context_is_not_sent_to_model(self):
        class ManyClaims(FixtureModel):
            async def complete(self, role, system, context):
                if role == 'reader':
                    page = context['paper']['pages'][0]
                    return {'claims': [{'text': f'Claim {i} ' + 'x' * 2800, 'kind': 'author_claim',
                                        'quote': page['text'], 'page': 1} for i in range(30)]}
                return await super().complete(role, system, context)
        model = ManyClaims()
        result = await ResearchWorkflow(model).run(Brief(topic='x'), papers(1))
        self.assertTrue(any(i['code'] == 'context_budget_exhausted' for i in result['issues']))
        self.assertEqual(result['metrics']['model_calls'], 1)
        self.assertFalse(any(role == 'synthesizer' for role, _ in model.contexts))


if __name__ == '__main__':
    unittest.main()

class RequirementQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_excluded_pm25_proposal_is_rejected_and_repaired_once(self):
        from scientific_research.demo import DemoModel,demo_input
        class RepairModel(DemoModel):
            attempts=0
            async def complete(self,role,system,context):
                result=await super().complete(role,system,context)
                if role=='proposer':
                    self.attempts+=1
                    if self.attempts==1:result['directions'][0]['question']='PM2.5预测怎么改进？'
                    else:
                        assert context.get('validation_feedback')
                        result['directions'][0]['question']='如何识别城市交通网络的异常传播？'
                return result
        brief,docs=demo_input();model=RepairModel()
        brief=brief.model_copy(update={'topic':'之前做PM2.5时空预测，老师说不行，需要换个方向'})
        result=await ResearchWorkflow(model).run(brief,docs)
        self.assertEqual(model.attempts,2)
        self.assertEqual(len(result['directions']),1)
        self.assertNotIn('PM2.5',result['directions'][0]['question'])

    async def test_persistently_excluded_proposals_never_reach_result(self):
        from scientific_research.demo import DemoModel,demo_input
        class Bad(DemoModel):
            async def complete(self,role,system,context):
                result=await super().complete(role,system,context)
                if role=='proposer': result['directions'][0]['minimal_experiment']='使用PM2.5数据进行预测'
                return result
        brief,docs=demo_input()
        result=await ResearchWorkflow(Bad()).run(brief.model_copy(update={'constraints':'排除PM2.5预测'}),docs)
        self.assertEqual(result['directions'],[])
        self.assertTrue(any(i['code']=='requirement_conflict' for i in result['issues']))

    async def test_paper_notes_cannot_cite_another_papers_evidence(self):
        from scientific_research.demo import DemoModel,demo_input
        class ForgedNote(DemoModel):
            async def complete(self,role,system,context):
                result=await super().complete(role,system,context)
                if role=='synthesizer':
                    claims=context['claims']; result['paper_notes']=[{'paper_id':claims[0]['paper_id'],'title_zh':'中文标题','why_read':'方法参考','relevance':'相关但待核实','limitation':'缺少全文','evidence_ids':[claims[-1]['evidence_id']]}]
                return result
        brief,docs=demo_input()
        result=await ResearchWorkflow(ForgedNote()).run(brief,docs)
        self.assertEqual(result['paper_notes'],[])
        self.assertTrue(any(i['code']=='invalid_paper_note' for i in result['issues']))

    async def test_abstract_note_cannot_claim_fulltext_was_checked(self):
        from scientific_research.demo import DemoModel,demo_input
        class Notes(DemoModel):
            async def complete(self,role,system,context):
                result=await super().complete(role,system,context)
                if role=='synthesizer':
                    c=context['claims'][0]
                    result['paper_notes']=[{'paper_id':c['paper_id'],'title_zh':'中文标题','why_read':'方法参考','relevance':'相关但待核实','limitation':'已经核验全文推导','evidence_ids':[c['evidence_id']]}]
                return result
        brief,docs=demo_input();docs=[d.model_copy(update={'access_level':'abstract'}) for d in docs]
        result=await ResearchWorkflow(Notes()).run(brief,docs)
        self.assertIn('尚未核验',result['paper_notes'][0]['limitation'])
        self.assertNotIn('已经核验',result['paper_notes'][0]['limitation'])
