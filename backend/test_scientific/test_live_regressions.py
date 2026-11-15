import sys,re,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.agent_loop import research
from scientific_research.models import Brief,Paper,Page
from scientific_research.demo import DemoModel,demo_input
from scientific_research.workflow import ResearchWorkflow
from scientific_research.reporting import compose_report

class ResearchActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_controller_only_receives_unread_legal_paper_ids(self):
        class Model:
            identity='legal-actions'
            steps=0
            async def complete(self,role,system,context):
                if role=='planner': return {'queries':['spatial forecasting'],'selection_criteria':[],'year_from':None,'year_to':None}
                self.steps+=1
                tools={t['name']:t for t in context['tools']}
                if self.steps==1: return {'action':'read_passages','paper_id':'P1','reason':'read'}
                if self.steps==2:
                    assert tools['read_passages']['allowed_paper_ids']==['P2']
                    return {'action':'read_passages','paper_id':'P2','reason':'read second'}
                assert tools['finish_research']['allowed_paper_ids']==['P1','P2']
                assert 'read_passages' not in tools
                return {'action':'finish_research','selected_ids':['P1','P2'],'reason':'done'}
        papers=[Paper(paper_id=f'p{i}',title=f'Paper {i}',access_level='abstract',pages=[Page(number=1,text='Spatial representation source.')]) for i in (1,2)]
        result=await research(Brief(topic='x'),Model(),seeds=papers)
        self.assertEqual(len(result['papers']),2)
        self.assertFalse(any(i['code']=='research_stopped_partial' for i in result['issues']))

    async def test_reread_after_fulltext_retrieval_uses_new_source(self):
        from unittest.mock import AsyncMock
        original=Paper(paper_id='p1',title='Paper',arxiv_id='2601.12345',access_level='abstract',pages=[Page(number=1,text='An abstract claim.')])
        full=original.model_copy(update={'access_level':'fulltext','pages':[Page(number=1,text='A longer fulltext claim.')]})
        actions=iter([{'action':'read_passages','paper_id':'P1','query':'same focus','reason':'read'},
                      {'action':'fetch_fulltext','paper_id':'P1','reason':'get source'},
                      {'action':'read_passages','paper_id':'P1','query':'same focus','reason':'read new source'},
                      {'action':'finish_research','selected_ids':['P1'],'reason':'done'}])
        class Model:
            async def complete(self,role,system,context):
                if role=='planner': return {'queries':['spatial forecasting'],'selection_criteria':[],'year_from':None,'year_to':None}
                return next(actions)
        provider=type('Provider',(),{})()
        provider.fulltext=AsyncMock(return_value=full)
        result=await research(Brief(topic='x',target_papers=1),Model(),provider,seeds=[original])
        self.assertFalse(any(i['code']=='research_stopped_partial' for i in result['issues']))
        self.assertEqual(result['papers'][0]['access_level'],'fulltext')

class SourceMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_agents_receive_saved_bibliographic_metadata(self):
        class Metadata(DemoModel):
            async def complete(self,role,system,context):
                if role in {'synthesizer','reviewer'}:
                    assert context['paper_metadata'][0]['published_at']=='2026-01-02'
                    assert not any('pages' in p for p in context['paper_metadata'])
                return await super().complete(role,system,context)
        brief,papers=demo_input()
        papers=[p.model_copy(update={'published_at':'2026-01-02'}) for p in papers]
        result=await ResearchWorkflow(Metadata()).run(brief,papers)
        self.assertEqual(result['status'],'completed')

class WritingContextTests(unittest.IsolatedAsyncioTestCase):
    async def make_result(self):
        brief,papers=demo_input()
        return await ResearchWorkflow(DemoModel()).run(brief,papers)

    async def test_short_citations_are_resolved_back_to_exact_evidence(self):
        class ShortIds(DemoModel):
            async def complete(self,role,system,context):
                if role in {'section_writer','section_reviser'}:
                    ids=[e['evidence_id'] for e in context['evidence']]
                    assert all(re.fullmatch(r'E\d+',i) for i in ids)
                    return {'paragraphs':[{'text':'作者在该材料中提出了可进一步比较的方法主张。','kind':'fact','evidence_ids':ids[:1]}]}
                return await super().complete(role,system,context)
        result=await self.make_result()
        report=await compose_report(result,ShortIds())
        self.assertEqual(report['status'],'ready')
        known={c['evidence_id'] for c in result['claims']}
        for section in report['sections']:
            self.assertTrue(set(section['paragraphs'][0]['evidence_ids']).issubset(known))

    async def test_repair_receives_failed_draft_and_allowed_ids(self):
        class Repair(DemoModel):
            async def complete(self,role,system,context):
                if role=='section_writer':
                    return {'paragraphs':[{'text':'这是待校验的作者主张。','kind':'fact','evidence_ids':['E999']}]}
                if role=='section_reviser':
                    assert context['draft']['paragraphs'][0]['evidence_ids']==['E999']
                    assert 'E1' in str(context['feedback'])
                    return {'paragraphs':[{'text':'依据提供的材料重新表述作者主张。','kind':'fact','evidence_ids':[context['evidence'][0]['evidence_id']]}]}
                return await super().complete(role,system,context)
        report=await compose_report(await self.make_result(),Repair())
        self.assertEqual(report['status'],'ready')

    async def test_section_context_does_not_include_outside_citations(self):
        class Scoped(DemoModel):
            async def complete(self,role,system,context):
                if role=='outliner':
                    raw=await super().complete(role,system,context)
                    for section in raw['sections']: section['evidence_ids']=[context['evidence'][0]['evidence_id']]
                    return raw
                if role in {'section_writer','section_reviser'}:
                    allowed={e['evidence_id'] for e in context['evidence']}
                    for key in ('findings','directions','paper_notes'):
                        assert all(set(item['evidence_ids']).issubset(allowed) for item in context.get(key,[]))
                    return {'paragraphs':[{'text':'本节仅依据当前可用证据说明参考价值。','kind':'fact','evidence_ids':list(allowed)[:1]}]}
                return await super().complete(role,system,context)
        report=await compose_report(await self.make_result(),Scoped())
        self.assertEqual(report['status'],'ready')

class FinalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_two_steps_prioritize_selection_from_read_materials(self):
        class Model:
            step=0
            async def complete(self,role,system,context):
                if role=='planner': return {'queries':['spatial forecasting'],'selection_criteria':[],'year_from':None,'year_to':None}
                self.step+=1
                if self.step<=2: return {'action':'read_passages','paper_id':f'P{self.step}','reason':'read'}
                assert [t['name'] for t in context['tools']]==['finish_research']
                return {'action':'finish_research','selected_ids':['P1','P2'],'reason':'select read references'}
        papers=[Paper(paper_id=f'p{i}',title=f'Paper {i}',access_level='abstract',pages=[Page(number=1,text='Spatial reference.')]) for i in (1,2)]
        result=await research(Brief(topic='x',max_agent_steps=4),Model(),seeds=papers)
        self.assertFalse(any(i['code']=='research_stopped_partial' for i in result['issues']))

    async def test_explicitly_excluded_source_cannot_be_selected(self):
        class Model:
            step=0
            async def complete(self,role,system,context):
                if role=='planner': return {'queries':['spatial forecasting'],'selection_criteria':[],'year_from':None,'year_to':None}
                self.step+=1
                if self.step==1: return {'action':'read_passages','paper_id':'P1','reason':'read'}
                return {'action':'finish_research','selected_ids':['P1'],'reason':'select'}
        p=Paper(paper_id='p1',title='Urban forecasting',access_level='abstract',pages=[Page(number=1,text='We forecast PM2.5 with spatial sensor data.')])
        result=await research(Brief(topic='x',excluded_topics=['PM2.5']),Model(),seeds=[p])
        self.assertEqual(result['papers'],[])
        self.assertIn('excluded_topic',result['screening'][0]['reason_codes'])
        self.assertTrue(any(i['code']=='requirements_not_satisfied' for i in result['issues']))

class ReportProvenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_metadata_changes_invalidate_ready_checkpoint(self):
        import copy
        class Seen(DemoModel):
            calls=0
            async def complete(self,role,system,context):
                self.calls+=1
                return await super().complete(role,system,context)
        brief,papers=demo_input();result=await ResearchWorkflow(DemoModel()).run(brief,papers)
        model=Seen();saved=[]
        await compose_report(result,model,on_checkpoint=saved.append)
        before=model.calls
        corrected=copy.deepcopy(result);corrected['papers'][0]['venue']='Corrected venue'
        await compose_report(corrected,model,saved_state=saved[-1])
        self.assertGreater(model.calls,before)

    async def test_report_roles_receive_explicit_current_date(self):
        from datetime import datetime,timezone
        class Dated(DemoModel):
            async def complete(self,role,system,context):
                if role in {'outliner','section_writer','report_reviewer'}:
                    assert context['as_of_date']==datetime.now(timezone.utc).date().isoformat()
                return await super().complete(role,system,context)
        brief,papers=demo_input();result=await ResearchWorkflow(DemoModel()).run(brief,papers)
        report=await compose_report(result,Dated())
        self.assertEqual(report['status'],'ready')

    def test_context_preserves_complete_direction_provenance(self):
        from scientific_research.context_builder import report_context
        ids=['A','B','C','D','outside']
        context=report_context({'brief':{},'directions':[{'question':'why','evidence_ids':ids}]})
        self.assertEqual(context['directions'][0]['evidence_ids'],ids)

class ArchiveIdentifierTests(unittest.TestCase):
    def test_recognizes_valid_arxiv_doi_but_not_untrusted_or_invalid_paths(self):
        from scientific_research.literature import parse_openalex
        for doi,expected in [('https://doi.org/10.48550/arXiv.2610.32329','2610.32329'),
                             ('https://evil.example/10.48550/arxiv.2610.32329',None),
                             ('https://doi.org/10.48550/arxiv.not-an-id',None)]:
            with self.subTest(doi=doi):
                papers=parse_openalex({'results':[{'id':'https://openalex.org/W123','title':'Example','doi':doi,'abstract_inverted_index':{'Study':[0]}}]})
                self.assertEqual(papers[0].arxiv_id,expected)
