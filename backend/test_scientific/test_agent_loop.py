import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.agent_loop import research
from scientific_research.models import Brief, Paper, Page


def paper():
    return Paper(paper_id='real-one', title='Spatial mechanisms', published_at='2026-01-02',
                 access_level='abstract', pages=[Page(number=1, text='A shared forcing explains spatial synchrony.')])


class Scripted:
    fixture = True
    identity = 'scripted-agent-test'
    def __init__(self, actions): self.actions = iter(actions)
    async def complete(self, role, system, context):
        if role == 'planner':
            return {'queries':['spatial mechanisms'],'selection_criteria':[], 'year_from':2026,'year_to':2026}
        assert role == 'controller'
        return next(self.actions)


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_resumed_success_clears_partial_selection_flag(self):
        states=[]
        brief=Brief(topic='x',max_agent_steps=6,target_papers=1)
        model=Scripted([
            {'action':'read_passages','paper_id':'P1','reason':'read'},
            {'action':'unknown','reason':'bad'},
            {'action':'unknown','reason':'bad'},
            {'action':'unknown','reason':'bad'}])
        first=await research(brief,model,seeds=[paper()],on_checkpoint=states.append)
        self.assertTrue(any(i['code']=='research_stopped_partial' for i in first['issues']))
        resumed=Scripted([{'action':'finish_research','selected_ids':['P1'],'reason':'done'}])
        final=await research(brief,resumed,saved_state=states[-1])
        self.assertFalse(any(i['code']=='research_stopped_partial' for i in final['issues']))

    async def test_resume_does_not_reset_total_step_budget(self):
        saved=[]
        brief=Brief(topic='x',max_agent_steps=1)
        model=Scripted([{'action':'read_passages','paper_id':'P1','reason':'read'}])
        first=await research(brief,model,seeds=[paper()],on_checkpoint=saved.append)
        self.assertEqual(len(first['papers']),1)
        class NeverCall(Scripted):
            async def complete(self,*args):
                raise AssertionError('Resume must not reset task-wide steps')
        again=[]
        await research(brief,NeverCall([]),saved_state=saved[-1],on_checkpoint=again.append)
        self.assertEqual(again[-1]['total_steps'],1)

    async def test_search_read_finish_and_reuse_checkpoint(self):
        provider = type('Provider', (), {})()
        provider.search = AsyncMock(return_value={'papers':[paper().model_dump()], 'audit':{'provider':'fixture'}})
        model = Scripted([
            {'action':'search_papers','query':'spatial mechanisms','reason':'缺少候选'},
            {'action':'read_passages','paper_id':'P1','reason':'检查方法依据'},
            {'action':'finish_research','selected_ids':['P1'],'reason':'已找到可阅读的参考'}])
        states, events = [], []
        result = await research(Brief(topic='2026年其他时空方向'), model, provider,
                                on_checkpoint=states.append, on_event=events.append)
        self.assertEqual(result['papers'][0]['paper_id'], 'real-one')
        self.assertTrue(any(e['type']=='agent_action' for e in events))
        again = await research(Brief(topic='2026年其他时空方向'), model, provider, saved_state=states[-1])
        self.assertEqual(again['papers'],result['papers'])
        self.assertEqual(provider.search.await_count,1)

    async def test_unknown_tool_and_paper_are_never_executed(self):
        provider = type('Provider', (), {})()
        provider.search = AsyncMock(return_value={'papers':[paper().model_dump()], 'audit':{}})
        model = Scripted([
            {'action':'run_shell','reason':'bad'},
            {'action':'fetch_fulltext','paper_id':'P999','reason':'bad'},
            {'action':'search_papers','query':'spatial mechanisms','reason':'search'},
            {'action':'read_passages','paper_id':'P1','reason':'read'},
            {'action':'finish_research','selected_ids':['P1'],'reason':'done'}])
        result = await research(Brief(topic='x'),model,provider)
        self.assertEqual(len(result['papers']),1)
        self.assertTrue(any(i['code']=='agent_action_rejected' for i in result['issues']))

    async def test_finish_cannot_select_unread_candidates(self):
        provider = type('Provider', (), {})()
        provider.search = AsyncMock(return_value={'papers':[paper().model_dump()], 'audit':{}})
        model = Scripted([
            {'action':'search_papers','query':'spatial mechanisms','reason':'search'},
            {'action':'finish_research','selected_ids':['P1'],'reason':'premature'},
            {'action':'read_passages','paper_id':'P1','reason':'read'},
            {'action':'finish_research','selected_ids':['P1'],'reason':'done'}])
        result=await research(Brief(topic='x'),model,provider)
        self.assertTrue(any(i['code']=='agent_action_rejected' for i in result['issues']))
