import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.demo import demo_input,DemoModel
from scientific_research.workflow import ResearchWorkflow

class BranchReportTests(unittest.IsolatedAsyncioTestCase):
 async def result(self):
  b,ps=demo_input();b=b.model_copy(update={'research_mode':'trend'})
  return await ResearchWorkflow(DemoModel()).run(b,ps)
 async def test_isolated_profiles_and_resume(self):
  from scientific_research.branch_report import compose_branch_report
  class M:
   identity='profile-fixture'
   calls=0
   async def complete(self,role,system,ctx):
    self.calls+=1
    assert len({e['paper_id'] for e in ctx['evidence']})==1
    e=ctx['evidence'][0]['evidence_id']
    f=lambda t:{'text':t,'evidence_ids':[e]}
    return {'branch':'图表示' if self.calls==1 else '交通预测','relevance':'direct','problem':f('具体研究任务'),'method':f('具体研究方法'),'contribution':f('作者报告的贡献'),'reading_value':f('可以借鉴的具体内容')}
  r=await self.result();m=M();saved=[]
  a=await compose_branch_report(r,m,on_checkpoint=saved.append)
  self.assertEqual(len(a['paper_matrix']),2)
  self.assertEqual(a['format'],'branch_review_v1')
  self.assertNotEqual(a['sections'][0]['paragraphs'],a['sections'][1]['paragraphs'])
  count=m.calls
  self.assertEqual(await compose_branch_report(r,m,saved_state=saved[-1]),a)
  self.assertEqual(m.calls,count)
 async def test_foreign_citations_are_rejected(self):
  from scientific_research.branch_report import compose_branch_report
  class M:
   async def complete(self,*a):
    f={'text':'没有根据的解读','evidence_ids':['FAKE']}
    return {'branch':'图神经网络','relevance':'direct','problem':f,'method':f,'contribution':f,'reading_value':f}
  r=await self.result();a=await compose_branch_report(r,M())
  self.assertEqual(a['status'],'partial');self.assertFalse(a['paper_matrix'])
  self.assertTrue(all(p['kind']=='limitation' for s in a['sections'] for p in s['paragraphs']))
 async def test_missing_method_keeps_supported_problem(self):
  from scientific_research.branch_report import compose_branch_report
  class M:
   async def complete(self,role,sys,ctx):
    f={'text':'作者报告的具体研究问题','evidence_ids':[ctx['evidence'][0]['evidence_id']]}
    return {'branch':'图表示','relevance':'direct','problem':f,'method':None,'contribution':f,'reading_value':f}
  r=await self.result();a=await compose_branch_report(r,M())
  self.assertEqual(len(a['paper_matrix']),2)
  self.assertIsNone(a['paper_matrix'][0]['method'])
 async def test_excluded_followup_is_not_published(self):
  from scientific_research.branch_report import compose_branch_report
  class M:
   async def complete(self,role,sys,ctx):
    f={'text':'原论文的研究内容','evidence_ids':[ctx['evidence'][0]['evidence_id']]}
    return {'branch':'图表示','relevance':'direct','problem':f,'method':f,'contribution':f,'reading_value':f,'next_question':{'text':'如何预测PM2.5','evidence_ids':f['evidence_ids']}}
  r=await self.result();r['brief']['excluded_topics']=['PM2.5'];a=await compose_branch_report(r,M())
  self.assertFalse(any('PM2.5' in p['text'] for s in a['sections'] for p in s['paragraphs']))
  self.assertTrue(any(i['code']=='profile_proposal_conflict' for i in a['issues']))
if __name__=='__main__':unittest.main()
