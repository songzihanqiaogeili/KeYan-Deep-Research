import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.discovery import discover
from scientific_research.models import Brief, Paper, Page


class Model:
    async def complete(self, role, system, context):
        if role == 'planner':
            return {'queries':['spatiotemporal representation learning'], 'year_from':2026, 'year_to':2026,
                    'selection_criteria':['Exclude PM2.5 forecasting']}
        return {'selected_ids':['arxiv-one']}


def candidate():
    return Paper(paper_id='arxiv-one',title='Spatial representations',arxiv_id='2601.12345',access_level='abstract',published_at='2026-01-01',
                 pages=[Page(number=1,text='We study spatial representations.')]).model_dump()


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_finds_selects_and_reads_without_seed_papers(self):
        provider = type('Provider',(),{})()
        provider.search = AsyncMock(return_value={'papers':[candidate()], 'audit':{'provider':'fixture'}})
        provider.fulltext = AsyncMock(return_value=Paper.model_validate(candidate()).model_copy(update={'access_level':'fulltext'}))
        calls, events = [], []
        result = await discover(Brief(topic='研究空间与时间方向，排除 PM2.5'), Model(), provider,
                                on_event=events.append, reserve_call=lambda role:calls.append(role))
        self.assertEqual(len(result['papers']),1)
        self.assertEqual(result['papers'][0]['access_level'],'fulltext')
        self.assertEqual(calls,['planner','selector'])
        self.assertIn('literature_search', [e['type'] for e in events])
        self.assertEqual(provider.search.call_args.kwargs['year_from'],2026)

    async def test_fulltext_failure_is_explicit_abstract_fallback(self):
        provider = type('Provider',(),{})()
        provider.search=AsyncMock(return_value={'papers':[candidate()], 'audit':{}})
        provider.fulltext=AsyncMock(side_effect=ValueError('unavailable'))
        result=await discover(Brief(topic='x'), Model(), provider)
        self.assertEqual(result['papers'][0]['access_level'],'abstract')
        self.assertTrue(any(i['code']=='fulltext_unavailable' for i in result['issues']))

    async def test_no_results_and_invented_selection_ids_are_not_papers(self):
        provider=type('Provider',(),{})()
        provider.search=AsyncMock(return_value={'papers':[], 'audit':{}})
        empty=await discover(Brief(topic='x'),Model(),provider)
        self.assertEqual(empty['papers'],[])
        self.assertTrue(any(i['code']=='requirements_not_satisfied' for i in empty['issues']))
        class Forged(Model):
            async def complete(self,role,system,context):
                return {'selected_ids':['invented']} if role=='selector' else await super().complete(role,system,context)
        provider.search=AsyncMock(return_value={'papers':[candidate()], 'audit':{}})
        with self.assertRaisesRegex(ValueError,'selection_output_invalid'):
            await discover(Brief(topic='x'),Forged(),provider)

class ScreeningRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, papers=None):
        provider=type('Provider',(),{})()
        provider.search=AsyncMock(return_value={'papers':papers or [candidate()], 'audit':{'provider':'fixture'}})
        provider.fulltext=AsyncMock(side_effect=ValueError('no fulltext'))
        return provider

    async def test_explicit_year_overrides_model_and_resume_plan(self):
        provider=self.provider()
        saved={'queries':['spatial learning'], 'selection_criteria':[], 'year_from':2024,'year_to':2026}
        result=await discover(Brief(topic='只要26年的论文'),Model(),provider,saved_plan=saved)
        self.assertEqual(result['search_plan']['year_from'],2026)
        self.assertEqual(provider.search.call_args.kwargs['year_from'],2026)

    async def test_invalid_ids_retry_with_feedback_and_short_alias(self):
        class Repair(Model):
            attempts=0
            async def complete(self,role,system,context):
                if role!='selector': return await super().complete(role,system,context)
                self.attempts+=1
                if self.attempts==1:return {'selected_ids':['invented']}
                assert context['validation_error']
                return {'selected_ids':['P1'], 'reasons':{'P1':'relevant'}, 'unverified':['journal rank']}
        events=[]
        result=await discover(Brief(topic='x'),Repair(),self.provider(),on_event=events.append)
        self.assertEqual(len(result['papers']),1)
        self.assertTrue(any(e['type']=='selection_retry' for e in events))

    async def test_empty_selection_is_no_match_and_queries_remain_bounded(self):
        class Empty(Model):
            async def complete(self,role,system,context):
                return {'selected_ids':[], 'no_match_reason':'No relevant method match'} if role=='selector' else await super().complete(role,system,context)
        provider=self.provider(); events=[]
        result=await discover(Brief(topic='2026年相关时空论文'),Empty(),provider,on_event=events.append)
        self.assertEqual(result['papers'],[])
        self.assertTrue(any(i['code']=='requirements_not_satisfied' for i in result['issues']))
        self.assertLessEqual(provider.search.call_count,3)
        self.assertTrue(any(e['type']=='selection_diagnostic' for e in events))
        self.assertTrue(all(call.kwargs['year_from']==2026 for call in provider.search.call_args_list))

    async def test_out_of_year_metadata_is_not_read(self):
        paper=candidate(); paper['published_at']='2025-01-01'
        provider=self.provider([paper])
        result=await discover(Brief(topic='2026年论文'),Model(),provider)
        self.assertEqual(result['papers'],[])
        self.assertIn('year_out_of_range',result['screening'][0]['reason_codes'])
        provider.fulltext.assert_not_called()
