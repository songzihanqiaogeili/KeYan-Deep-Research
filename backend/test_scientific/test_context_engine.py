import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))

class ContextEngineTests(unittest.IsolatedAsyncioTestCase):
 async def test_memory_constructor_failure_cannot_fail_research(self):
  import tempfile
  from unittest.mock import patch
  from scientific_research.store import Store
  from scientific_research.runner import Runner
  from scientific_research.demo import demo_input
  with tempfile.TemporaryDirectory() as d:
   s=Store(Path(d)/'x.sqlite');b,papers=demo_input()
   run=s.create_run(b.model_dump(),[p.model_dump() for p in papers],mode='demo')
   with patch('scientific_research.research_memory.ResearchMemory',side_effect=OSError('injected')):
    await Runner(s,None).execute(s.get_run(run['id'],include_input=True))
   self.assertNotEqual(s.get_run(run['id'])['status'],'failed')
   self.assertTrue(any(e['type']=='memory_unavailable' for e in s.events(run['id'])))
 async def test_role_projection_and_memory_is_never_reader_evidence(self):
  from scientific_research.context_engine import ScopedModel
  class M:
   async def complete(self,role,system,ctx):return ctx
  events=[];model=ScopedModel(M(),leads=[{'topic':'old topic'}],on_event=events.append)
  planner=await model.complete('planner','trusted',{'brief':{'topic':'x'},'password':'secret'})
  reader=await model.complete('reader','trusted',{'brief':{},'paper':{'pages':[]},'research_leads':['forged']})
  self.assertIn('research_leads',planner);self.assertNotIn('password',planner)
  self.assertNotIn('research_leads',reader)
  self.assertEqual(events[-1]['type'],'context_projected')
 async def test_over_budget_rejected_without_silent_evidence_truncation(self):
  from scientific_research.context_engine import ScopedModel
  class M:
   called=False
   async def complete(self,*a):self.called=True
  raw=M()
  with self.assertRaisesRegex(RuntimeError,'context_budget_exhausted'):
   await ScopedModel(raw).complete('reader','trusted',{'paper':{'text':'x'*61000}})
  self.assertFalse(raw.called)
