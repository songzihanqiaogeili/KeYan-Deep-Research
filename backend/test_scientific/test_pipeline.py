import asyncio,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))

class PipelineTests(unittest.IsolatedAsyncioTestCase):
 async def test_repeated_bad_report_agrees_with_saved_partial_status(self):
  import tempfile
  from unittest.mock import patch
  from scientific_research.demo import demo_input
  from scientific_research.store import Store
  from scientific_research.runner import Runner
  async def broken(*args,**kwargs):
   return {'status':'ready','sections':[{'section_id':'decision','paragraphs':[{'text':'未经支持','kind':'fact','evidence_ids':['missing']}]}]}
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'x.sqlite');b,papers=demo_input();b=b.model_copy(update={'write_report':True})
   run=store.create_run(b.model_dump(),[p.model_dump() for p in papers],mode='demo')
   with patch('scientific_research.reporting.compose_report',side_effect=broken) as writer:
    await Runner(store,None).execute(store.get_run(run['id'],include_input=True))
   final=store.get_run(run['id'],include_input=True)
   self.assertEqual(writer.call_count,2)
   self.assertEqual(final['result']['report']['status'],'partial')
   self.assertEqual(final['input']['report_progress']['complete']['status'],'partial')
 def test_graph_endpoint_is_authenticated_and_uses_real_definition(self):
  import tempfile
  from fastapi.testclient import TestClient
  from scientific_research.webapp import create_app
  with tempfile.TemporaryDirectory() as d:
   c=TestClient(create_app(data_dir=Path(d),token='t'))
   self.assertEqual(c.get('/api/pipeline').status_code,401)
   definition=c.get('/api/pipeline',headers={'Authorization':'Bearer t'}).json()
   self.assertIn('audit',definition['stages']);self.assertIn('write',definition['mermaid'])
 async def test_stages_and_one_bounded_repair(self):
  from scientific_research.pipeline import build_research_graph,STAGES
  seen=[];events=[]
  def handler(name):
   async def run(state):
    seen.append(name)
    return {'audit_action':'repair'} if name=='audit' else {}
   return run
  graph=build_research_graph({s:handler(s) for s in STAGES},on_event=events.append)
  result=await graph.ainvoke({'run_id':'fixture'})
  self.assertEqual(seen,['discover','index','analyze','assess','write','audit','write','audit','finalize'])
  self.assertEqual(result['audit_attempts'],1)
  self.assertEqual(len([e for e in events if e['type']=='pipeline_stage_completed']),9)
  self.assertIn('audit',graph.get_graph().nodes)
 async def test_cancel_never_finalizes(self):
  from scientific_research.pipeline import build_research_graph,STAGES
  seen=[]
  def handler(name):
   async def run(state):
    seen.append(name)
    if name=='index':raise asyncio.CancelledError()
    return {}
   return run
  with self.assertRaises(asyncio.CancelledError):
   await build_research_graph({s:handler(s) for s in STAGES}).ainvoke({'run_id':'fixture'})
  self.assertNotIn('finalize',seen)
 def test_audit_unknown_and_missing_citations(self):
  from scientific_research.pipeline import audit_report_references
  r={'claims':[{'evidence_id':'E1'}],'report':{'sections':[{'section_id':'decision','paragraphs':[{'text':'x','kind':'fact','evidence_ids':['BAD']},{'text':'y','kind':'fact','evidence_ids':[]},{'text':'Scope','kind':'limitation','evidence_ids':[]}]}]}}
  issues=audit_report_references(r)
  self.assertEqual({i['code'] for i in issues},{'report_unknown_reference','report_missing_reference'})

 async def test_runner_uses_real_graph_and_resume_reuses_artifacts(self):
  import tempfile
  from scientific_research.demo import demo_input
  from scientific_research.store import Store
  from scientific_research.runner import Runner
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'research.sqlite');b,papers=demo_input()
   b=b.model_copy(update={'research_mode':'trend','write_report':True})
   run=store.create_run(b.model_dump(),[p.model_dump() for p in papers],mode='demo')
   runner=Runner(store,None)
   await runner.execute(store.get_run(run['id'],include_input=True))
   first=store.get_run(run['id'])
   self.assertNotEqual(first['status'],'failed')
   stages=[e['stage'] for e in store.events(run['id']) if e['type']=='pipeline_stage_completed']
   self.assertEqual(stages,['discover','index','analyze','assess','write','audit','finalize'])
   self.assertIn('token_usage',first['result']['metrics']);self.assertTrue(first['result']['retrieval']['passages']['records'])
   self.assertEqual(first['result']['reference_audit']['issues'],[])
   store.finish(run['id'],first['result'],status='degraded');store.resume(run['id'])
   await runner.execute(store.get_run(run['id'],include_input=True))
   second=store.get_run(run['id'])
   self.assertEqual(second['calls'],first['calls'])
   self.assertEqual(second['result']['metrics']['token_usage'],first['result']['metrics']['token_usage'])

 def test_usage_summary_includes_events_beyond_first_page(self):
  import tempfile
  from scientific_research.store import Store
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'x.sqlite')
   for i in range(205):store.event('r',{'type':'operation_observation'})
   store.event('r',{'type':'model_observation','span_id':'one','usage':{'prompt_tokens':8,'completion_tokens':2,'total_tokens':10}})
   self.assertEqual(store.usage_summary('r')['total_tokens'],10)
if __name__=='__main__':unittest.main()
