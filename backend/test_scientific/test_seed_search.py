import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.models import Brief,Paper,Page

def seed(text='We model 3D object relations with graph neural networks.'):
 return Paper(paper_id='seed',title='User filename.pdf',pages=[Page(number=1,text=text)])

class SeedSearchTests(unittest.IsolatedAsyncioTestCase):
 async def test_seed_text_controls_plan_and_selection(self):
  from scientific_research.trend import collect_trend
  class M:
   identity='fixture'
   async def complete(self,role,system,ctx):
    assert '3D object relations' in ctx['seed_papers'][0]['pages'][0]['text']
    if role=='planner':return {'queries':['3D scene graph relations'],'selection_criteria':[]}
    return {'selected_ids':['P1'],'reasons':{'P1':'与种子同为3D物体关系建模'}}
  class P:
   async def search(self,q,**kw):
    return {'papers':[Paper(paper_id='new',title='New scene graph paper',published_at='2026-01-01',pages=[Page(number=1,text='We learn 3D scene graph relations.')]).model_dump(),seed().model_dump()],'audit':{'provider':'fixture'}}
  b=Brief(topic='按论文扩展',search_mode='paper',research_mode='trend')
  found=await collect_trend(b,M(),P(),seeds=[seed()])
  self.assertEqual([p['paper_id'] for p in found['papers']],['new'])
  self.assertEqual(found['seed_documents'][0]['paper_id'],'seed')
  self.assertIn('种子',found['candidate_papers'][0]['relation_to_seed'])
 async def test_seed_context_is_bounded_and_content_key_changes(self):
  from scientific_research.seed_search import seed_context
  a=seed_context([seed('a'*20000)])
  self.assertLessEqual(sum(len(p['text']) for d in a for p in d['pages']),9000)
  self.assertNotEqual(a[0]['document_hash'],seed_context([seed('b'*20000)])[0]['document_hash'])
 async def test_paper_mode_requires_seed(self):
  from scientific_research.trend import collect_trend
  with self.assertRaisesRegex(ValueError,'seed_documents_required'):
   await collect_trend(Brief(topic='x',search_mode='paper'),None,None)

 async def test_focused_seed_search_does_not_require_historical_coverage(self):
  from scientific_research.trend import collect_trend
  class M:
   async def complete(self,role,sys,ctx):
    if role=='planner':return {'queries':['scene graph'],'selection_criteria':[]}
    return {'selected_ids':['P1'],'reasons':{'P1':'对应种子的研究问题'}}
  class P:
   async def search(self,*a,**kw):return {'papers':[Paper(paper_id='new',title='Related',published_at='2026-01-01',pages=[Page(number=1,text='Related research.')]).model_dump()],'audit':{'provider':'fixture'}}
  out=await collect_trend(Brief(topic='x',search_mode='paper',research_mode='focused',target_papers=1),M(),P(),seeds=[seed()])
  self.assertFalse(any(i['code']=='historical_coverage_gap' for i in out['issues']))

 async def test_direct_problem_results_precede_newer_method_only_results(self):
  from scientific_research.trend import collect_trend
  class M:
   async def complete(self,role,system,ctx):
    if role=='planner':return {'queries':['3D scene graph','Wasserstein alignment'],'selection_criteria':[]}
    return {'selected_ids':[p['paper_id'] for p in ctx['candidates']], 'reasons':{p['paper_id']:'相关候选' for p in ctx['candidates']}}
  class P:
   async def search(self,q,**kw):
    direct=q=='3D scene graph'
    return {'papers':[Paper(paper_id='direct' if direct else 'method',title='Scene graph comparison' if direct else 'General transport method',published_at='2024-01-01' if direct else '2026-01-01',pages=[Page(number=1,text='Core scene graph study.' if direct else 'General alignment theory.')]).model_dump()],'audit':{'provider':'fixture','query':q}}
  out=await collect_trend(Brief(topic='x',search_mode='paper',research_mode='focused',target_papers=1),M(),P(),seeds=[seed()])
  self.assertEqual([p['paper_id'] for p in out['papers']],['direct'])
  self.assertEqual(out['candidate_papers'][0]['search_queries'],['3D scene graph'])

 async def test_semantic_rank_selects_better_same_year_candidate_without_overriding_problem_priority(self):
  from scientific_research.trend import collect_trend
  class M:
   async def complete(self,role,system,ctx):
    if role=='planner':return {'queries':['scene graphs'],'selection_criteria':[]}
    return {'selected_ids':[p['paper_id'] for p in ctx['candidates']], 'reasons':{p['paper_id']:'同问题对比' for p in ctx['candidates']}}
  class P:
   async def search(self,q,**kw):return {'papers':[Paper(paper_id=pid,title=pid,published_at='2026-01-01',pages=[Page(number=1,text='scene graph '+pid)]).model_dump() for pid in ['weak','strong']],'audit':{'provider':'fixture'}}
  class Ranker:
   identity='fake-ranker'
   async def rank(self,papers,seeds,goal):return {'scores':{'weak':.1,'strong':.9},'mode':'semantic','fallback_reason':''}
  out=await collect_trend(Brief(topic='x',search_mode='paper',research_mode='focused',target_papers=1),M(),P(),seeds=[seed()],ranker=Ranker())
  self.assertEqual(out['papers'][0]['paper_id'],'strong')
  self.assertEqual(next(p for p in out['candidate_papers'] if p['paper_id']=='strong')['semantic_score'],.9)

 async def test_network_failure_with_seed_is_not_a_no_match(self):
  from scientific_research.trend import collect_trend
  class M:
   async def complete(self,*a):return {'queries':['scene graph'],'selection_criteria':[]}
  class P:
   async def search(self,*a,**kw):raise ConnectionError('offline')
  with self.assertRaisesRegex(ValueError,'literature_sources_unavailable'):
   await collect_trend(Brief(topic='x',search_mode='paper'),M(),P(),seeds=[seed()])

class SeedIdentityTests(unittest.TestCase):
 def test_pdf_identifier_matches_index_abstract(self):
  from scientific_research.seed_search import same_seed_work
  original=seed('Synthetic paper header. DOI: 10.1234/seed-paper')
  indexed=Paper(paper_id='index-copy',title='Actual indexed title',doi='https://doi.org/10.1234/seed-paper',pages=[Page(number=1,text='A different abstract representation.')])
  self.assertTrue(same_seed_work(indexed,[original]))
 def test_ambiguous_header_dois_are_not_guessed(self):
  from scientific_research.seed_search import same_seed_work
  original=seed('DOI: 10.1234/one DOI: 10.1234/two')
  indexed=seed().model_copy(update={'paper_id':'new','doi':'10.1234/one'})
  self.assertFalse(same_seed_work(indexed,[original]))

class SeedApiTests(unittest.TestCase):
 def test_missing_seeds_and_disabled_search_rejected_before_model(self):
  from scientific_research.webapp import create_app
  from fastapi.testclient import TestClient
  with tempfile.TemporaryDirectory() as d:
   app=create_app(data_dir=Path(d),token='test');c=TestClient(app);h={'Authorization':'Bearer test'}
   r=c.post('/api/runs',headers=h,json={'brief':{'topic':'x','search_mode':'paper'}})
   self.assertEqual(r.status_code,422)
   self.assertIn('种子',r.json()['detail'])
   self.assertFalse(app.state.store.list_runs())
if __name__=='__main__':unittest.main()
