import asyncio,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))

class ObservationTests(unittest.IsolatedAsyncioTestCase):
 async def test_actual_sources_have_separate_observed_boundaries(self):
  from scientific_research.observability import Observer
  from scientific_research.providers import ArxivProvider
  from scientific_research.literature import OpenAlexProvider
  from unittest.mock import AsyncMock
  events=[];o=Observer('sources',on_event=events.append)
  arxiv=ArxivProvider();arxiv._fetch=AsyncMock(side_effect=RuntimeError('injected'))
  # Source guards may reject before I/O; the source operation must still be observed.
  async def actions():
   for name,fn in [('arxiv',lambda:arxiv.search('graph')),('fulltext',lambda:arxiv.fulltext(None)),('openalex',lambda:OpenAlexProvider().search(''))]:
    try:await fn()
    except Exception:pass
  await o.call('discover',actions)
  names={e['name'] for e in events}
  self.assertTrue({'arxiv.search','arxiv.fulltext','openalex.search'}.issubset(names))
 async def test_nested_spans_are_summary_only_and_usage_is_actual(self):
  from scientific_research.observability import Observer,ObservedModel
  from contextvars import ContextVar
  class Sink:
   def __init__(self):self.rows=[]
   def start(self,name,kind,inputs,parent,metadata):
    row={'name':name,'inputs':inputs,'parent':parent,'metadata':metadata};self.rows.append(row);return len(self.rows)
   def end(self,token,outputs,error,usage):self.rows[token-1].update(outputs=outputs,error=error,usage=usage)
  class M:
   identity='fixture';usage_context=ContextVar('usage',default=None)
   async def complete(self,*a):self.usage_context.set({'prompt_tokens':7,'completion_tokens':3,'total_tokens':10});return {'text':'SECRET PDF output'}
  sink=Sink();events=[];o=Observer('r',sink=sink,on_event=events.append);model=ObservedModel(M(),o)
  await o.call('analyze',lambda:model.complete('reader','SECRET SYSTEM',{'pdf':'SECRET PDF text'}),inputs={'papers':['SECRET PDF text']})
  self.assertNotIn('SECRET',json.dumps(sink.rows));self.assertEqual(sink.rows[1]['parent'],1)
  self.assertEqual(sink.rows[1]['usage']['total_tokens'],10)
  self.assertEqual([e for e in events if e['type']=='model_observation'][0]['usage']['prompt_tokens'],7)
 async def test_sink_failure_cannot_fail_work_and_disabled_never_constructs_sink(self):
  from scientific_research.observability import Observer
  from unittest.mock import patch
  class Bad:
   def start(self,*a):raise RuntimeError('SECRET')
  async def work():return 42
  self.assertEqual(await Observer('r',sink=Bad()).call('work',work),42)
  with patch.dict('os.environ',{'SCIENTIFIC_LANGSMITH_ENABLED':'false','LANGSMITH_API_KEY':'SECRET'}),patch('scientific_research.observability.LangSmithSink') as factory:
   self.assertIsNone(Observer.from_env('r').sink);factory.assert_not_called()
 async def test_cancel_propagates_and_closes_span(self):
  from scientific_research.observability import Observer
  events=[]
  async def work():raise asyncio.CancelledError()
  with self.assertRaises(asyncio.CancelledError):await Observer('r',on_event=events.append).call('cancelled',work)
  self.assertEqual(events[-1]['outcome'],'cancelled')
if __name__=='__main__':unittest.main()
