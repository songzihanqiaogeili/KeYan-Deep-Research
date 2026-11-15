import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.reporting import compose_report
from scientific_research.demo import DemoModel,demo_input
from scientific_research.workflow import ResearchWorkflow


class ReportingTests(unittest.IsolatedAsyncioTestCase):
    async def test_reviewer_receives_ninth_claim_selected_by_rag(self):
        import copy
        class NinthIndex:
            identity='ninth';mode='fixture';fallback_reason=''
            async def search(self,*a,**kw):return [{'evidence_id':'ninth'}]
        class Model(DemoModel):
            async def complete(self,role,system,ctx):
                if role=='report_reviewer':
                    assert any(e['evidence_id']=='E9' and 'Ninth source quote' in e['quote'] for e in ctx['evidence'])
                return await super().complete(role,system,ctx)
        b,papers=demo_input();result=await ResearchWorkflow(DemoModel()).run(b,papers)
        claim=result['claims'][0]
        result['claims']=[{**copy.deepcopy(claim),'evidence_id':str(i)} for i in range(8)]+[{**copy.deepcopy(claim),'evidence_id':'ninth','quote':'Ninth source quote'}]
        report=await compose_report(result,Model(),evidence_index=NinthIndex())
        self.assertEqual(report['status'],'ready')
    async def test_later_sections_receive_bounded_completed_section_context(self):
        class Continuity(DemoModel):
            async def complete(self,role,system,context):
                if role in {'section_writer','section_reviser'}:
                    sid=context['section']['section_id']
                    if sid!='decision':
                        earlier=next(p for p in context['other_sections'] if p['section_id']=='decision')
                        assert earlier['status']=='written'
                        assert '已经说明主结论' in earlier['completed_summary']
                        assert len(earlier['completed_summary'])<=240
                        assert earlier['usage']=='structure_only_not_evidence'
                    text='这里已经说明主结论，后面的章节应推进论证。' if sid=='decision' else '本节根据自身问题推进分析，避免重述已有章节。'
                    return {'paragraphs':[{'text':text,'kind':'limitation','evidence_ids':[]}]}
                return await super().complete(role,system,context)
        brief,papers=demo_input();result=await ResearchWorkflow(DemoModel()).run(brief,papers)
        report=await compose_report(result,Continuity())
        self.assertEqual(report['status'],'ready')

    async def test_resume_reuses_drafts_and_retries_unavailable_review(self):
        class RetryReview(DemoModel):
            identity='review-retry'
            def __init__(self): self.fail=True;self.roles=[]
            async def complete(self,role,system,context):
                self.roles.append(role)
                if role=='report_reviewer' and self.fail: raise TimeoutError('injected')
                return await super().complete(role,system,context)
        brief,papers=demo_input();result=await ResearchWorkflow(DemoModel()).run(brief,papers)
        model=RetryReview();saved=[]
        first=await compose_report(result,model,on_checkpoint=saved.append)
        self.assertEqual(first['status'],'partial')
        model.fail=False;model.roles=[]
        second=await compose_report(result,model,saved_state=saved[-1])
        self.assertEqual(second['status'],'ready')
        self.assertEqual(model.roles,['report_reviewer'])

    async def test_blocking_review_revises_only_target_section(self):
        class LocalRevision(DemoModel):
            def __init__(self): self.reviews=0;self.revised=[]
            async def complete(self,role,system,context):
                if role=='report_reviewer':
                    self.reviews+=1
                    if self.reviews==1:
                        return {'findings':[{'section_id':'decision','kind':'missing_answer','severity':'blocking','detail':'说明选题依据'}]}
                if role=='section_reviser': self.revised.append(context['section']['section_id'])
                return await super().complete(role,system,context)
        brief,papers=demo_input();result=await ResearchWorkflow(DemoModel()).run(brief,papers)
        model=LocalRevision();report=await compose_report(result,model)
        self.assertEqual(model.revised,['decision'])
        self.assertEqual(model.reviews,2)
        self.assertEqual(report['status'],'ready')

    async def test_review_receives_every_allowed_citation(self):
        import copy
        class NinthCitation(DemoModel):
            async def complete(self,role,system,context):
                if role=='outliner':
                    raw=await super().complete(role,system,context)
                    raw['sections'][0]['evidence_ids']=['E9']
                    return raw
                if role=='report_reviewer':
                    available={e['evidence_id'] for e in context['evidence']}
                    cited={i for section in context['sections'] for p in section['paragraphs'] for i in p['evidence_ids']}
                    assert cited.issubset(available)
                return await super().complete(role,system,context)
        brief,papers=demo_input();result=await ResearchWorkflow(DemoModel()).run(brief,papers)
        claim=result['claims'][0]
        result['claims']=[{**copy.deepcopy(claim),'evidence_id':f'E{i}'} for i in range(1,10)]
        report=await compose_report(result,NinthCitation())
        self.assertEqual(report['status'],'ready')
        self.assertTrue(any(i['code']=='outline_fallback' for i in report['issues']))

    async def test_report_has_sections_and_resume_avoids_completed_drafts(self):
        brief,papers=demo_input()
        result=await ResearchWorkflow(DemoModel()).run(brief,papers)
        model=DemoModel();saved=[];calls=[]
        report=await compose_report(result,model,on_checkpoint=saved.append,reserve_call=calls.append)
        self.assertEqual(len(report['sections']),4)
        self.assertEqual(report['status'],'ready')
        self.assertTrue(all(s['paragraphs'] for s in report['sections']))
        count=len(calls)
        again=await compose_report(result,model,saved_state=saved[-1],reserve_call=calls.append)
        self.assertEqual(again,report)
        self.assertEqual(len(calls),count)

    async def test_forged_citations_never_appear_as_report_facts(self):
        class Forged(DemoModel):
            async def complete(self,role,system,context):
                if role in {'section_writer','section_reviser'}:
                    return {'paragraphs':[{'text':'这是没有证据支持的确定事实。','kind':'fact','evidence_ids':['forged']}]}
                return await super().complete(role,system,context)
        brief,papers=demo_input();result=await ResearchWorkflow(DemoModel()).run(brief,papers)
        report=await compose_report(result,Forged())
        self.assertEqual(report['status'],'partial')
        self.assertTrue(all(not s['paragraphs'] for s in report['sections']))
