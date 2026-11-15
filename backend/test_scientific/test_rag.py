import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.models import Paper,Page

class RagTests(unittest.IsolatedAsyncioTestCase):
 async def test_parallel_readers_freeze_each_actual_retrieval_identity(self):
  import asyncio
  from scientific_research.demo import DemoModel,demo_input
  from scientific_research.workflow import ResearchWorkflow
  b,papers=demo_input();started=asyncio.Event()
  class Retriever:
   identity='hybrid';mode='hybrid';fallback_reason=''
   async def search(self,q,*,paper_id,**kw):
    if paper_id=='synthetic-b':
     await started.wait();self.identity='fallback';self.mode='bm25'
    p=next(p for p in papers if p.paper_id==paper_id)
    return [{'page':1,'quote':p.pages[0].text,'chunk_id':paper_id,'retrieval_identity':self.identity}]
  class Model(DemoModel):
   async def complete(self,role,system,ctx):
    if role=='reader' and ctx['paper']['paper_id']=='synthetic-a':
     started.set();await asyncio.sleep(.02)
    return await super().complete(role,system,ctx)
  class Cache:
   values={}
   def cache_get(self,key):return None
   def cache_put(self,key,value):self.values[key]=value
  cache=Cache()
  await ResearchWorkflow(Model()).run(b,papers,cache=cache,retriever=Retriever())
  a=next(v for v in cache.values.values() if v['claims'][0]['paper_id']=='synthetic-a')
  self.assertEqual(a.get('retrieval_identity'),'hybrid')
 async def test_index_and_query_respect_deadline_and_effective_identity(self):
  import asyncio,time
  from scientific_research.rag import TaskIndex
  class Slow:
   identity='same-model'
   async def embed(self,texts):await asyncio.sleep(.2);return [[1.,0.] for t in texts]
  rows=[{'chunk_id':'a','text':'transport'}]
  failed=TaskIndex(rows,embedder=Slow(),deadline=time.monotonic()+.01)
  start=time.monotonic();await failed.build()
  self.assertLess(time.monotonic()-start,.15);self.assertEqual(failed.mode,'bm25')
  class Good(Slow):
   async def embed(self,texts):return [[1.,0.] for t in texts]
  healthy=TaskIndex(rows,embedder=Good());await healthy.build()
  self.assertNotEqual(failed.identity,healthy.identity)
  before=healthy.identity;healthy.deadline=time.monotonic()-1
  await healthy.search('transport')
  self.assertNotEqual(before,healthy.identity)
 async def test_materializes_only_budgeted_chunks(self):
  from scientific_research.rag import passage_records
  from unittest.mock import patch
  from scientific_research.tracing import digest
  papers=[Paper(paper_id=str(i),title='x',pages=[Page(number=1,text='content '*20000)]) for i in range(3)]
  with patch('scientific_research.rag.digest',wraps=digest) as count:
   rows=passage_records(papers,max_records=4)
  self.assertEqual(len(rows),4);self.assertEqual(count.call_count,4)
 async def test_semantic_synonym_keeps_page_hash_and_isolates_paper(self):
  from scientific_research.rag import TaskIndex,passage_records
  class E:
   identity='fake-v1'
   async def embed(self,texts):return [[1.,0.] if 'heart' in t or 'cardiac' in t else [0.,1.] for t in texts]
  papers=[Paper(paper_id='a',title='Cardiology',pages=[Page(number=7,text='The heart muscle contracts.')]),Paper(paper_id='b',title='Other',pages=[Page(number=2,text='The road carries traffic.')])]
  idx=TaskIndex(passage_records(papers),embedder=E());await idx.build()
  hit=(await idx.search('cardiac',limit=1))[0]
  self.assertEqual(hit['paper_id'],'a');self.assertEqual(hit['page'],7);self.assertTrue(hit['document_hash'])
  self.assertIn('semantic_rank',hit)
  self.assertFalse(await idx.search('cardiac',paper_id='unknown'))
 async def test_bad_embeddings_fall_back_and_no_lexical_hit_is_not_fabricated(self):
  from scientific_research.rag import TaskIndex
  class E:
   identity='bad'
   async def embed(self,texts):return [[float('nan')]]*len(texts)
  idx=TaskIndex([{'chunk_id':'a','text':'Graph transport evidence','paper_id':'a'}],embedder=E());await idx.build()
  hit=await idx.search('transport')
  self.assertEqual(hit[0]['chunk_id'],'a');self.assertEqual(idx.mode,'bm25')
  self.assertTrue(idx.fallback_reason);self.assertEqual(await idx.search('unfindable'),[])
 async def test_record_budget_round_robins_sources(self):
  from scientific_research.rag import passage_records,TaskIndex
  papers=[Paper(paper_id=str(i),title='x',pages=[Page(number=1,text='Long text. '*1000)]) for i in range(3)]
  rows=passage_records(papers,max_records=4)
  self.assertEqual(len(rows),4);self.assertEqual({r['paper_id'] for r in rows},{'0','1','2'})
  idx=TaskIndex(rows,max_records=2);await idx.build();self.assertEqual(idx.metrics['records'],2);self.assertTrue(idx.metrics['truncated'])
 async def test_claim_selection_cannot_escape_allowlist(self):
  from scientific_research.rag import TaskIndex
  idx=TaskIndex([{'chunk_id':'e1','evidence_id':'e1','paper_id':'a','text':'transport'},{'chunk_id':'e2','evidence_id':'e2','paper_id':'b','text':'transport transport'}]);await idx.build()
  rows=await idx.search('transport',allowed_ids={'e1'});self.assertEqual([r['evidence_id'] for r in rows],['e1'])
 async def test_no_lexical_overlap_still_reads_bounded_original_text(self):
  from scientific_research.demo import demo_input,DemoModel
  from scientific_research.workflow import ResearchWorkflow
  b,papers=demo_input();b=b.model_copy(update={'research_mode':'trend','topic':'完全不同的中文问题'})
  r=await ResearchWorkflow(DemoModel()).run(b,papers)
  self.assertTrue(r['claims'])
  self.assertTrue(any(e['type']=='retrieval_no_match' for e in r['events']))

class EmbeddingTests(unittest.IsolatedAsyncioTestCase):
 async def test_ollama_batches_and_rejects_wrong_count(self):
  from scientific_research.embeddings import OllamaEmbeddings
  import httpx
  requests=[]
  def response(req):
   import json
   body=json.loads(req.content);requests.append(body)
   return httpx.Response(200,json={'embeddings':[[1.,0.] for t in body['input']],'prompt_eval_count':2})
  e=OllamaEmbeddings('bge-m3',transport=httpx.MockTransport(response),batch_size=2)
  self.assertEqual(len(await e.embed(['a','b','c'])),3);self.assertEqual(len(requests),2);await e.close()
  bad=OllamaEmbeddings('bge-m3',transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'embeddings':[]})))
  with self.assertRaisesRegex(ValueError,'embedding'):await bad.embed(['a'])
  await bad.close()
if __name__=='__main__':unittest.main()
