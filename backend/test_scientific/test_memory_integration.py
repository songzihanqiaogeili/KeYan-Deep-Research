import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.store import Store
from scientific_research.research_memory import ResearchMemory

class MemoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
 async def test_run_snapshots_history_and_keeps_it_on_resume(self):
  from scientific_research.runner import Runner
  from scientific_research.demo import DemoModel,demo_input
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'x.sqlite');memory=ResearchMemory(store)
   seed={'status':'completed','brief':{'topic':'长期记忆 Agent'},'papers':[{'paper_id':'real','title':'Agent memory research','source_url':'https://example.org/paper'}]}
   self.assertTrue(memory.remember('prior',seed))
   b,papers=demo_input();b=b.model_copy(update={'write_report':True})
   run=store.create_run(b.model_dump(),[p.model_dump() for p in papers],mode='model')
   with patch('scientific_research.llm.OpenAIModel',DemoModel):
    await Runner(store,None).execute(store.get_run(run['id'],include_input=True))
    first=store.get_run(run['id'],include_input=True)
    self.assertNotEqual(first['status'],'failed')
    self.assertEqual(len(first['input']['memory_snapshot']),1)
    memory.delete('prior')
    store.finish(run['id'],first['result'],status='degraded');store.resume(run['id'])
    await Runner(store,None).execute(store.get_run(run['id'],include_input=True))
   second=store.get_run(run['id'],include_input=True)
   self.assertEqual(second['input']['memory_snapshot'],first['input']['memory_snapshot'])
   self.assertEqual(second['calls'],first['calls'])

 def test_memory_api_requires_auth_and_delete_preserves_history(self):
  from fastapi.testclient import TestClient
  from scientific_research.webapp import create_app
  from scientific_research.demo import demo_input
  with tempfile.TemporaryDirectory() as d:
   app=create_app(data_dir=Path(d),token='t');c=TestClient(app);h={'Authorization':'Bearer t'}
   b,papers=demo_input();run=app.state.store.create_run(b.model_dump(),[],mode='model')
   memory=ResearchMemory(app.state.store)
   memory.remember(run['id'],{'status':'completed','brief':{'topic':'graph research'},'papers':[{'paper_id':'p','title':'Graph study','source_url':'https://example.org/paper'}]})
   self.assertEqual(c.get('/api/research-memory?query=graph').status_code,401)
   self.assertTrue(c.get('/api/research-memory?query=graph',headers=h).json()['leads'])
   self.assertTrue(c.delete('/api/research-memory/'+run['id'],headers=h).json()['deleted'])
   self.assertIsNotNone(app.state.store.get_run(run['id']))
