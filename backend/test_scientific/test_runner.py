import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.runner import Runner, DirectoryLock
from scientific_research.store import Store
from scientific_research.demo import DemoModel, demo_input


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_resume_keeps_analysis_and_completed_chapters(self):
        class FlakyReport(DemoModel):
            identity='same-model'
            fail=True
            roles=[]
            async def complete(self,role,system,context):
                type(self).roles.append(role)
                if role=='report_reviewer' and self.fail: raise TimeoutError('injected review failure')
                return await super().complete(role,system,context)
        brief,papers=demo_input()
        brief=brief.model_copy(update={'write_report':True})
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            ident=store.create_run(brief.model_dump(),[p.model_dump() for p in papers],mode='model')['id']
            with patch('scientific_research.llm.OpenAIModel',FlakyReport):
                await Runner(store,None).execute(store.claim_next())
                self.assertEqual(store.get_run(ident)['result']['report']['status'],'partial')
                FlakyReport.fail=False;FlakyReport.roles=[]
                store.resume(ident)
                await Runner(store,None).execute(store.claim_next())
            self.assertEqual(FlakyReport.roles,['report_reviewer'])
            final=store.get_run(ident)
            self.assertEqual(final['status'],'completed')
            self.assertEqual(final['result']['report']['status'],'ready')

    async def test_adaptive_research_replaces_rejected_seed_and_writes_report(self):
        class Adaptive(DemoModel):
            actions=iter([
                {'action':'search_papers','query':'agent memory','reason':'补充符合要求的论文'},
                {'action':'read_passages','paper_id':'P2','reason':'阅读方法依据'},
                {'action':'finish_research','selected_ids':['P2'],'reason':'选用已读的相关材料'}])
            async def complete(self,role,system,context):
                if role=='planner':
                    return {'queries':['agent memory'],'selection_criteria':[],'year_from':None,'year_to':None}
                if role=='controller': return next(self.actions)
                return await super().complete(role,system,context)
        brief,papers=demo_input()
        brief=brief.model_copy(update={'agent_loop':True,'write_report':True,'target_papers':1})
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            provider=type('Provider',(),{})()
            provider.search=AsyncMock(return_value={'papers':[papers[1].model_dump()],'audit':{'provider':'fixture'}})
            ident=store.create_run(brief.model_dump(),[papers[0].model_dump()],mode='model',auto_search=True)['id']
            with patch('scientific_research.llm.OpenAIModel',Adaptive):
                await Runner(store,provider).execute(store.claim_next())
            run=store.get_run(ident,include_input=True)
            self.assertEqual([p['paper_id'] for p in run['result']['papers']],['synthetic-b'])
            self.assertEqual(run['input']['seed_papers'][0]['paper_id'],'synthetic-a')
            self.assertTrue(run['input']['agent_progress']['finished'])
            self.assertEqual(run['result']['report']['status'],'ready')
            self.assertEqual(len(run['result']['report']['sections']),4)
            self.assertEqual(run['calls'],run['result']['metrics']['model_calls'])

    async def test_resume_retries_failed_analysis_instead_of_reusing_it(self):
        class Flaky(DemoModel):
            identity='same-model'
            fail=True
            syntheses=0
            async def complete(self,role,system,context):
                if role=='synthesizer':
                    type(self).syntheses+=1
                    if self.fail: raise ValueError('injected synthesis failure')
                return await super().complete(role,system,context)
        brief,papers=demo_input()
        brief=brief.model_copy(update={'write_report':True})
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            ident=store.create_run(brief.model_dump(),[p.model_dump() for p in papers],mode='model')['id']
            with patch('scientific_research.llm.OpenAIModel',Flaky):
                await Runner(store,None).execute(store.claim_next())
                self.assertTrue(any(i['code']=='synthesis_failed' for i in store.get_run(ident)['result']['issues']))
                Flaky.fail=False
                store.resume(ident)
                await Runner(store,None).execute(store.claim_next())
            final=store.get_run(ident)
            self.assertEqual(Flaky.syntheses,2)
            self.assertEqual(final['status'],'completed')
            self.assertEqual(final['result']['metrics']['cached_papers'],2)
            self.assertEqual(final['result']['report']['status'],'ready')

    async def test_auto_search_runs_without_seeds_and_resume_reuses_discovery(self):
        from scientific_research.models import Paper,Page
        class AutoModel(DemoModel):
            async def complete(self,role,system,context):
                if role=='planner':
                    return {'queries':['spatiotemporal learning'],'selection_criteria':[],'year_from':None,'year_to':None}
                if role=='selector':
                    return {'selected_ids':['real-candidate']}
                return await super().complete(role,system,context)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            brief,_=demo_input()
            paper=Paper(paper_id='real-candidate',title='Fixture retrieved paper',arxiv_id='2601.12345',pages=[Page(number=1,text='Synthetic source for regression test.')])
            provider=type('Provider',(),{})()
            provider.search=AsyncMock(return_value={'papers':[paper.model_dump()],'audit':{'provider':'fixture'}})
            provider.fulltext=AsyncMock(return_value=paper)
            ident=store.create_run(brief.model_dump(),[],mode='model',auto_search=True)['id']
            with patch('scientific_research.llm.OpenAIModel',AutoModel):
                await Runner(store,provider).execute(store.claim_next())
                result=store.get_run(ident)['result']
                self.assertEqual(len(result['claims']),1)
                self.assertTrue(result['search_plan'])
                store.finish(ident,result,status='degraded')
                store.resume(ident)
                await Runner(store,provider).execute(store.claim_next())
            self.assertEqual(provider.search.await_count,1)
            self.assertEqual(provider.fulltext.await_count,1)
            self.assertEqual(store.get_run(ident)['result']['metrics']['cached_papers'],1)

    async def test_similar_work_records_query_and_does_not_claim_novelty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'research.db')
            brief, papers = demo_input()
            run = store.create_run(brief.model_dump(), [p.model_dump() for p in papers], mode='model', novelty=True)
            provider = type('Provider', (), {})()
            provider.search = AsyncMock(return_value={'papers': [], 'audit': {'provider': 'test-fixture', 'query': 'memory'}})
            with patch('scientific_research.llm.OpenAIModel', DemoModel):
                await Runner(store, provider).execute(store.claim_next())
            saved = store.get_run(run['id'])
            self.assertEqual(saved['result']['directions'][0]['novelty_check_status'], 'searched_no_results')
            self.assertEqual(saved['result']['search_audit'][0]['provider'], 'test-fixture')
            self.assertEqual(saved['calls'], 5)

    async def test_directory_lock_prevents_two_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = DirectoryLock(Path(tmp) / 'lock'), DirectoryLock(Path(tmp) / 'lock')
            first.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    second.acquire()
            finally:
                first.release()

    async def test_terminal_result_survives_store_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'research.db'
            store = Store(path)
            brief, papers = demo_input()
            ident = store.create_run(brief.model_dump(), [p.model_dump() for p in papers], mode='demo')['id']
            await Runner(store, None).execute(store.claim_next())
            reopened = Store(path)
            self.assertEqual(reopened.get_run(ident)['status'], 'completed')
            self.assertTrue(reopened.events(ident))

    async def test_failed_screening_resume_keeps_plan_without_second_planner(self):
        class InvalidSelector(DemoModel):
            planner_calls=0
            async def complete(self,role,system,context):
                if role=='planner':
                    type(self).planner_calls+=1
                    return {'queries':['spatial representation learning'],'selection_criteria':[],'year_from':2026,'year_to':2026}
                if role=='selector':return {'selected_ids':['invented']}
                return await super().complete(role,system,context)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            brief,_=demo_input()
            from scientific_research.models import Paper,Page
            paper=Paper(paper_id='real',title='Real fixture',published_at='2026-01-01',pages=[Page(number=1,text='Fixture abstract')])
            provider=type('Provider',(),{})()
            provider.search=AsyncMock(return_value={'papers':[paper.model_dump()],'audit':{'provider':'fixture'}})
            ident=store.create_run(brief.model_dump(),[],mode='model',auto_search=True)['id']
            with patch('scientific_research.llm.OpenAIModel',InvalidSelector):
                await Runner(store,provider).execute(store.claim_next())
                self.assertEqual(store.get_run(ident)['status'],'failed')
                self.assertEqual(store.get_run(ident)['calls'],3)
                store.resume(ident)
                await Runner(store,provider).execute(store.claim_next())
            self.assertEqual(InvalidSelector.planner_calls,1)
            self.assertEqual(store.get_run(ident)['calls'],5)
            self.assertEqual(store.events(ident)[-2]['code'],'selection_output_invalid')
