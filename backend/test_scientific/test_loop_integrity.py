import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.agent_loop import research
from scientific_research.models import Brief, Paper, Page
from scientific_research.documents import document_hash


def source(**updates):
    values = dict(paper_id='original', title='Spatial synchrony', arxiv_id='2601.00001',
                  access_level='abstract', source_url='https://arxiv.org/abs/2601.00001',
                  pages=[Page(number=1, text='Spatial synchrony follows shared forcing.')])
    values.update(updates)
    return Paper(**values)


def action(name, **kwargs):
    return {'action': name, 'reason': 'fixture step', **kwargs}


class Controller:
    identity = 'loop-integrity'
    fixture = True
    def __init__(self, actions):
        self.actions = iter(actions)
        self.planner_calls = 0
        self.controller_calls = 0
    async def complete(self, role, system, context):
        if role == 'planner':
            self.planner_calls += 1
            return {'queries': ['spatial synchrony'], 'selection_criteria': [],
                    'year_from': None, 'year_to': None}
        self.controller_calls += 1
        return next(self.actions)


class LoopIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_mismatched_fulltext_preserves_original_and_read_status(self):
        for changed in [dict(paper_id='other'), dict(arxiv_id='2601.99999'),
                        dict(title='Entirely different paper')]:
            with self.subTest(changed=changed):
                original = source()
                provider = type('Provider', (), {})()
                provider.fulltext = AsyncMock(return_value=source(
                    **{**changed, 'access_level': 'fulltext',
                       'pages': [Page(number=1, text='Unrelated full text.')]}))
                saved = []
                model = Controller([action('read_passages', paper_id='P1'),
                    action('fetch_fulltext', paper_id='P1'),
                    action('finish_research', selected_ids=['P1'])])
                result = await research(Brief(topic='spatial', target_papers=1), model,
                    provider, seeds=[original], on_checkpoint=saved.append)
                self.assertEqual(result['papers'], [original.model_dump()])
                errors = [o for s in saved for o in s['observations'] if o['status']=='error']
                self.assertEqual(errors[-1]['code'], 'fulltext_identity_mismatch')
                self.assertEqual(errors[-1]['action'], 'fetch_fulltext')

    async def test_abstract_fulltext_response_is_failure_without_overwriting(self):
        original = source()
        provider = type('Provider', (), {})()
        provider.fulltext = AsyncMock(return_value=source(pages=[Page(number=1, text='Changed abstract')]))
        saved=[]
        result=await research(Brief(topic='spatial',target_papers=1), Controller([
            action('read_passages',paper_id='P1'), action('fetch_fulltext',paper_id='P1'),
            action('finish_research',selected_ids=['P1'])]), provider,
            seeds=[original],on_checkpoint=saved.append)
        self.assertEqual(result['papers'],[original.model_dump()])
        self.assertTrue(any(o.get('code')=='fulltext_unavailable' for s in saved for o in s['observations']))

    async def test_changed_seed_text_invalidates_finished_checkpoint(self):
        saved=[]
        brief=Brief(topic='spatial',target_papers=1)
        await research(brief,Controller([action('read_passages',paper_id='P1'),
            action('finish_research',selected_ids=['P1'])]),seeds=[source()],on_checkpoint=saved.append)
        changed=source(pages=[Page(number=1,text='Spatial synchrony revised source.')])
        model=Controller([action('read_passages',paper_id='P1'),action('finish_research',selected_ids=['P1'])])
        result=await research(brief,model,seeds=[changed],saved_state=saved[-1])
        self.assertEqual(result['papers'],[changed.model_dump()])
        self.assertEqual(model.planner_calls,1)

    async def test_changed_planner_skill_invalidates_state_and_unbound_plan(self):
        import scientific_research.agent_loop as loop
        saved=[]
        brief=Brief(topic='spatial',target_papers=1)
        await research(brief,Controller([action('read_passages',paper_id='P1'),
            action('finish_research',selected_ids=['P1'])]),seeds=[source()],on_checkpoint=saved.append)
        load=loop.load_skill
        with patch.object(loop,'load_skill',side_effect=lambda role: load(role)+(' changed' if role=='planner' else '')):
            model=Controller([action('read_passages',paper_id='P1'),action('finish_research',selected_ids=['P1'])])
            await research(brief,model,seeds=[source()],saved_state=saved[-1],saved_plan=saved[-1]['plan'])
        self.assertEqual(model.planner_calls,1)
        self.assertEqual(model.controller_calls,2)

    async def test_resume_preserves_consecutive_rejections(self):
        saved=[]
        brief=Brief(topic='spatial',target_papers=1,max_agent_steps=10)
        class Interrupted(Controller):
            async def complete(self,role,system,context):
                if role=='controller' and self.controller_calls==2:
                    raise ValueError('call_budget_exhausted')
                return await super().complete(role,system,context)
        with self.assertRaisesRegex(ValueError,'call_budget_exhausted'):
            await research(brief,Interrupted([action('read_passages',paper_id='P1'),
                action('invalid')]),seeds=[source()],on_checkpoint=saved.append)
        model=Controller([action('invalid'),action('invalid'),
                          action('get_paper_metadata',paper_id='P1')])
        final=[]
        result=await research(brief,model,saved_state=saved[-1],on_checkpoint=final.append)
        self.assertEqual(model.controller_calls,2)
        self.assertEqual(final[-1]['no_progress'],3)
        self.assertEqual(result['loop_metrics']['stop_reason'],'no_progress_limit')
        self.assertEqual(final[-1]['stop_reason'],'no_progress_limit')

    async def test_read_uses_retrieval_provenance_and_explicit_fallback(self):
        for query,mode in [('synchrony','bm25'),('zzzznotfound','source_preview')]:
            with self.subTest(query=query):
                saved=[]
                await research(Brief(topic='spatial',target_papers=1),Controller([
                    action('read_passages',paper_id='P1',query=query),
                    action('finish_research',selected_ids=['P1'])]),seeds=[source()],on_checkpoint=saved.append)
                read=next(o for s in saved for o in s['observations'] if o.get('action')=='read_passages')
                self.assertEqual(read['retrieval_mode'],mode)
                row=read['passages'][0]
                self.assertEqual(row['paper_id'],'original')
                self.assertEqual(row['document_hash'],document_hash(source()))
                self.assertEqual(row['source_url'],source().source_url)
                self.assertEqual(row['text'],source().pages[0].text[row['start']:row['start']+len(row['text'])])
                self.assertTrue(row['chunk_id'])
                self.assertEqual(read['fallback_reason'],'no_lexical_hits' if mode=='source_preview' else '')

    async def test_finished_metrics_are_measured_and_checkpointed(self):
        saved=[]
        result=await research(Brief(topic='spatial',target_papers=1),Controller([
            action('read_passages',paper_id='P1'),action('finish_research',selected_ids=['P1'])]),
            seeds=[source()],on_checkpoint=saved.append)
        self.assertEqual(result['loop_metrics'],dict(stop_reason='selected',total_steps=2,
            no_progress=0,tool_counts={'read_passages':1},read_papers=1,selected_papers=1))
        self.assertEqual(saved[-1]['stop_reason'],'selected')
