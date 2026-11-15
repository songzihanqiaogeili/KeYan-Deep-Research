import sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.models import Brief,Paper,Page
from scientific_research.requirements import build_spec,assess_paper

def paper(i=1,year=2026):
    return Paper(paper_id=f'p{i}',title=f'Spatiotemporal transfer method {i}',published_at=f'{year}-01-02',publication_type='journal',venue='Test Journal',doi=f'10.1234/test{i}',pages=[Page(number=1,text=f'Method {i} studies spatiotemporal transfer. External validation remains limited.')])

def fixture_selection(args):
    ids=[p['paper_id'] for p in args[2]['candidates'][:3]]
    return {'selected_ids':ids,'reasons':{i:'Fixture relevance supplied by test' for i in ids},'no_match_reason':'Empty fixture'}

class ContractTests(unittest.TestCase):
    def test_rank_requires_exact_identifier_and_auditable_rule(self):
        b=Brief(topic='必须顶刊',venue_catalog=[{'venue':'Test Journal','system':'导师名单','version':'2026-v1','label':'认可期刊','source_url':'https://example.org/list','qualifies':True}])
        result=assess_paper(paper(),build_spec(b))
        self.assertTrue(result['eligible'])
        self.assertIn('2026-v1',str(result))
        self.assertIn('未独立',str(result))
        self.assertFalse(assess_paper(paper().model_copy(update={'venue':'Test Journal Letters'}),build_spec(b))['eligible'])
    def test_catalog_does_not_promote_negative_rule(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError): Brief(topic='x',venue_catalog=[{'venue':'X','qualifies':True}])
        b=Brief(topic='必须顶刊',venue_catalog=[{'venue':'Test Journal','system':'自定义','version':'1','label':'排除','source_url':'https://example.org/list','qualifies':False}])
        self.assertFalse(assess_paper(paper(),build_spec(b))['eligible'])
    def test_passage_search_retains_page_and_matches_focus(self):
        from scientific_research.retrieval import retrieve_passages
        p=paper().model_copy(update={'pages':[Page(number=1,text='We introduce the background.'),Page(number=2,text='External validation uses a transfer benchmark across cities.')]})
        rows=retrieve_passages(p,'transfer benchmark',limit=1)
        self.assertEqual(rows[0]['page'],2)
        self.assertIn('transfer benchmark',rows[0]['quote'])
        self.assertEqual(rows[0]['document_hash'],__import__('scientific_research.documents',fromlist=['document_hash']).document_hash(p))

class TrendTests(unittest.IsolatedAsyncioTestCase):
    async def test_collection_is_bounded_parallel_and_resumable(self):
        from scientific_research.trend import collect_trend,trend_coverage,argument_ledger
        class Model:
            identity='fixture'
            async def complete(self,*args):return fixture_selection(args) if args[0]=='selector' else {'queries':['spatiotemporal transfer','spatiotemporal benchmark'],'selection_criteria':[]}
        class Provider:
            active=peak=calls=0
            async def search(self,q,**kw):
                import asyncio
                self.calls+=1;self.active+=1;self.peak=max(self.peak,self.active)
                await asyncio.sleep(.005);self.active-=1
                return {'papers':[paper(1,2023).model_dump(),paper(2,2026).model_dump()], 'audit':{'provider':'fixture','query':q}}
            async def fulltext(self,p):raise RuntimeError('unavailable')
        b=Brief(topic='时空建模',research_mode='trend',max_concurrency=2,max_papers=6)
        p=Provider();saved=[]
        result=await collect_trend(b,Model(),p,on_checkpoint=saved.append)
        self.assertLessEqual(p.peak,2);self.assertGreaterEqual(p.peak,2)
        self.assertEqual(len(result['papers']),2)
        self.assertEqual({p['published_at'][:4] for p in result['papers']},{'2023','2026'})
        self.assertTrue(result['search_plan']['query_tasks'])
        calls=p.calls
        second=await collect_trend(b,Model(),p,saved_state=saved[-1])
        self.assertEqual(p.calls,calls)
        self.assertEqual(second['papers'],result['papers'])
        coverage=trend_coverage(result['candidate_papers'],result['papers'],result['search_audit'])
        self.assertFalse(coverage['systematic_review']);self.assertEqual(coverage['candidate_count'],2)
    async def test_all_sources_down_is_failure_not_empty_recommendation(self):
        from scientific_research.trend import collect_trend
        class Model:
            async def complete(self,*args):return {'queries':['transfer'],'selection_criteria':[]}
        class Broken:
            async def search(self,*args,**kw):raise RuntimeError('offline')
        with self.assertRaisesRegex(ValueError,'literature_sources_unavailable'):
            await collect_trend(Brief(topic='时空',research_mode='trend'),Model(),Broken())
    async def test_ledger_rejects_unknown_ids_and_keeps_semantic_status(self):
        from scientific_research.trend import argument_ledger
        r={'claims':[{'evidence_id':'E1','paper_id':'p1','page':2,'quote':'Original evidence.','verification_status':'quote_located_semantics_unverified'}], 'findings':[{'text':'综合判断','evidence_ids':['E1']}], 'gaps':[], 'directions':[], 'report':{'sections':[{'section_id':'decision','paragraphs':[{'text':'未经支撑','kind':'fact','evidence_ids':['FAKE']}]}]}}
        rows=argument_ledger(r)
        self.assertEqual(rows[0]['support_status'],'quote_located_semantics_unverified')
        self.assertEqual(rows[-1]['support_status'],'invalid_reference')

if __name__=='__main__':unittest.main()

class TrendIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_receives_trend_coverage_and_source_ledger(self):
        from scientific_research.demo import demo_input,DemoModel
        from scientific_research.workflow import ResearchWorkflow
        from scientific_research.reporting import compose_report
        from scientific_research.trend import argument_ledger
        class Model(DemoModel):
            async def complete(self,role,system,ctx):
                if role in {'outliner','section_writer','report_reviewer'}:
                    assert ctx['trend_coverage']['candidate_count']==2
                return await super().complete(role,system,ctx)
        b,ps=demo_input();b=b.model_copy(update={'research_mode':'trend'})
        r=await ResearchWorkflow(DemoModel()).run(b,ps)
        r['trend_coverage']={'candidate_count':2,'analyzed_count':2,'systematic_review':False}
        r['report']=await compose_report(r,Model())
        self.assertEqual(r['report']['format'],'branch_review_v1')
        self.assertEqual(r['report']['status'],'ready')
        self.assertIn('发展脉络',r['report']['sections'][0]['title'])
        self.assertTrue(argument_ledger(r))

class CatalogApiTests(unittest.TestCase):
    def test_catalog_is_authenticated_validated_and_preview_uses_saved_rules(self):
        from fastapi.testclient import TestClient
        from scientific_research.webapp import create_app
        with tempfile.TemporaryDirectory() as d:
            app=create_app(data_dir=Path(d),token='fixture-token')
            c=TestClient(app);headers={'Authorization':'Bearer fixture-token'}
            body={'entries':[{'venue':'Test Journal','system':'导师名单','version':'2026-v1','label':'认可','source_url':'https://example.org/list','qualifies':True}]}
            self.assertEqual(c.put('/api/venue-catalog',json=body).status_code,401)
            self.assertEqual(c.put('/api/venue-catalog',json=body,headers=headers).status_code,200)
            self.assertEqual(c.get('/api/venue-catalog',headers=headers).json()['entries'][0]['version'],'2026-v1')
            self.assertEqual(c.put('/api/venue-catalog',json={'entries':[{'venue':'bad'}]},headers=headers).status_code,422)
            spec=c.post('/api/requirements/preview',json={'topic':'必须顶刊','research_mode':'trend'},headers=headers).json()
            self.assertEqual(spec['venue_catalog'][0]['version'],'2026-v1')
            self.assertEqual(app.state.store.list_runs(),[])

class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_queries_can_retry_after_interruption(self):
        from scientific_research.trend import collect_trend
        class Model:
            identity='retry-fixture'
            async def complete(self,*a):return fixture_selection(a) if a[0]=='selector' else {'queries':['transfer'],'selection_criteria':[]}
        class Provider:
            failed=True
            async def search(self,*a,**kw):
                if self.failed:raise RuntimeError('offline')
                return {'papers':[paper().model_dump()],'audit':{'provider':'fixture'}}
        p=Provider();saved=[];b=Brief(topic='时空',research_mode='trend')
        with self.assertRaises(ValueError):await collect_trend(b,Model(),p,on_checkpoint=saved.append)
        p.failed=False
        found=await collect_trend(b,Model(),p,saved_state=saved[-1])
        self.assertEqual(len(found['papers']),1)
    async def test_persistent_snapshot_and_passage_authorization(self):
        from fastapi.testclient import TestClient
        from scientific_research.webapp import create_app
        from unittest.mock import patch,AsyncMock
        import os
        with tempfile.TemporaryDirectory() as d:
            app=create_app(data_dir=Path(d),token='t');c=TestClient(app);h={'Authorization':'Bearer t'}
            entry={'venue':'Test Journal','system':'Custom','version':'one','label':'Selected','source_url':'https://example.org/list','qualifies':True}
            c.put('/api/venue-catalog',json={'entries':[entry]},headers=h)
            doc=app.state.store.put_document(paper().model_dump())
            with patch.dict(os.environ,{'SCIENTIFIC_LLM_API_KEY':'fixture','SCIENTIFIC_LLM_MODEL':'fixture'}),patch('scientific_research.webapp.model_status',new=AsyncMock(return_value={'model_ready':True})):
                r=c.post('/api/runs',json={'brief':{'topic':'x','research_mode':'trend'},'auto_search':False,'document_ids':[doc]},headers=h)
            self.assertEqual(r.status_code,202,r.text);ident=r.json()['id']
            c.put('/api/venue-catalog',json={'entries':[]},headers=h)
            saved=app.state.store.get_run(ident,include_input=True)['input']['brief']
            self.assertEqual(saved['venue_catalog'][0]['version'],'one')
            path=f'/api/runs/{ident}/passages?paper_id=p1&query=transfer'
            self.assertEqual(c.get(path).status_code,401)
            self.assertEqual(c.get(path,headers=h).status_code,200)
            self.assertEqual(c.get(path.replace('p1','unknown'),headers=h).status_code,404)
            self.assertFalse(c.get(path,headers=h).json()['semantic_support_verified'])

class TrendMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_dedup_keeps_journal_metadata_independent_of_source_order(self):
        from scientific_research.trend import collect_trend
        class M:
            async def complete(self,*a):return fixture_selection(a) if a[0]=='selector' else {'queries':['transfer'],'selection_criteria':[]}
        old=paper().model_copy(update={'paper_id':'arxiv-copy','publication_type':'preprint','venue':'','issns':[]})
        pub=paper().model_copy(update={'paper_id':'journal-copy','issns':['1234-5678']})
        class P:
            async def search(self,*a,**kw):return {'papers':[old.model_dump(),pub.model_dump()],'audit':{'provider':'fixture'}}
        b=Brief(topic='x',research_mode='trend',publication_policy='journal_only')
        r=await collect_trend(b,M(),P())
        self.assertEqual(r['papers'][0]['publication_type'],'journal')
        self.assertEqual(r['papers'][0]['issns'],['1234-5678'])
        tasks=r['search_plan']['query_tasks']
        history=next(t for t in tasks if t['research_goal']=='historical_context')
        recent=next(t for t in tasks if t['research_goal']=='recent_focus')
        self.assertLess(history['year_to'],recent['year_from'])

class PartialCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_resume_retries_failed_queries_only(self):
        from scientific_research.trend import collect_trend
        class M:
            async def complete(self,*a):return fixture_selection(a) if a[0]=='selector' else {'queries':['good','bad'],'selection_criteria':[]}
        class P:
            failed=True;calls=0
            async def search(self,q,**kw):
                self.calls+=1
                if q=='bad' and self.failed:raise RuntimeError('offline')
                return {'papers':[paper(1,2023).model_dump(),paper(2,2026).model_dump()],'audit':{'provider':'fixture'}}
        p=P();saved=[];b=Brief(topic='x',research_mode='trend')
        first=await collect_trend(b,M(),p,on_checkpoint=saved.append)
        self.assertTrue(any(i['code']=='research_stopped_partial' for i in first['issues']))
        count=p.calls;p.failed=False
        second=await collect_trend(b,M(),p,saved_state=saved[-1])
        self.assertEqual(p.calls-count,2)
        self.assertFalse(any(a['status']=='failed' for a in second['search_audit']))
    async def test_preprint_with_matching_venue_is_not_verified_journal(self):
        b=Brief(topic='必须顶刊',venue_catalog=[{'venue':'Test Journal','system':'Custom','version':'1','label':'selected','source_url':'https://example.org/list','qualifies':True}])
        p=paper().model_copy(update={'publication_type':'preprint'})
        self.assertFalse(assess_paper(p,build_spec(b))['eligible'])

class RunnerTrendTests(unittest.IsolatedAsyncioTestCase):
    async def test_imported_trend_run_delivers_reading_list_and_ledger(self):
        from scientific_research.demo import demo_input,DemoModel
        from scientific_research.store import Store
        from scientific_research.runner import Runner
        from unittest.mock import patch
        b,ps=demo_input();b=b.model_copy(update={'research_mode':'trend','write_report':True,'target_papers':1})
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'research.sqlite')
            row=store.create_run(b.model_dump(),[p.model_dump() for p in ps],mode='model')
            with patch('scientific_research.llm.OpenAIModel',DemoModel):await Runner(store,None).execute(store.get_run(row['id'],include_input=True))
            r=store.get_run(row['id'])['result']
            self.assertTrue(r['synthetic_fixture'])
            self.assertEqual(len(r['reading_recommendations']),1)
            self.assertTrue(r['argument_ledger'])
            self.assertEqual(r['trend_coverage']['analyzed_count'],2)

class RelevanceAndDateTests(unittest.IsolatedAsyncioTestCase):
    async def test_irrelevant_candidates_never_reach_reader_selection(self):
        from scientific_research.trend import collect_trend
        class M:
            async def complete(self,role,system,ctx):
                if role=='planner':return {'queries':['cross city transfer'],'selection_criteria':[]}
                return {'selected_ids':['P2'],'reasons':{'P2':'摘要明确研究跨城市泛化'},'rejected':[{'paper_id':'P1','reason':'教育管理不相关'}]}
        class P:
            async def search(self,*a,**kw):return {'papers':[paper(1,2023).model_copy(update={'title':'Education management'}).model_dump(),paper(2,2026).model_dump()],'audit':{'provider':'fixture'}}
        r=await collect_trend(Brief(topic='跨城市迁移',research_mode='trend'),M(),P())
        self.assertEqual([p['paper_id'] for p in r['papers']],['p2'])
        self.assertEqual(r['candidate_papers'][0]['relevance_status'],'not_selected')
    async def test_unknown_selector_id_fails_closed(self):
        from scientific_research.trend import collect_trend
        class M:
            async def complete(self,role,*a):
                if role=='planner':return {'queries':['transfer'],'selection_criteria':[]}
                return {'selected_ids':['FAKE'],'reasons':{'FAKE':'imagined'}}
        class P:
            async def search(self,*a,**kw):return {'papers':[paper().model_dump()],'audit':{'provider':'fixture'}}
        with self.assertRaisesRegex(ValueError,'selection_output_invalid'):
            await collect_trend(Brief(topic='x',research_mode='trend'),M(),P())
    async def test_future_index_date_is_not_accepted_as_published_evidence(self):
        from datetime import date,timedelta
        p=paper().model_copy(update={'published_at':(date.today()+timedelta(days=30)).isoformat()})
        r=assess_paper(p,build_spec(Brief(topic='近期论文')))
        self.assertFalse(r['eligible']);self.assertIn('future_publication_date',r['reason_codes'])

class CutoffResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_year_only_future_date_fails_closed(self):
        from datetime import date
        p=paper().model_copy(update={'published_at':str(date.today().year+1)})
        self.assertFalse(assess_paper(p,build_spec(Brief(topic='x')))['eligible'])
    async def test_overnight_resume_keeps_successful_steps(self):
        from datetime import date
        from unittest.mock import patch
        from scientific_research.trend import collect_trend
        class M:
            async def complete(self,*a):return fixture_selection(a) if a[0]=='selector' else {'queries':['transfer'],'selection_criteria':[]}
        class P:
            calls=0
            async def search(self,*a,**kw):
                self.calls+=1;return {'papers':[paper(1,2023).model_dump(),paper(2,2026).model_dump()],'audit':{'provider':'fixture'}}
        class LaterDate(date):
            @classmethod
            def today(cls):return cls(2030,1,1)
        b=Brief(topic='x',research_mode='trend');p=P();saved=[]
        first=await collect_trend(b,M(),p,on_checkpoint=saved.append);count=p.calls
        with patch('scientific_research.requirements.date',LaterDate):
            second=await collect_trend(b,M(),p,saved_state=saved[-1])
        self.assertEqual(p.calls,count);self.assertEqual(first,second)
