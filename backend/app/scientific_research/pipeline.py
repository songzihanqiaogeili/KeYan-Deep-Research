"""The real top-level graph; artifacts live in the existing task store."""
import inspect,time
from contextlib import nullcontext
from typing import TypedDict
from langgraph.graph import StateGraph,START,END

STAGES=('discover','index','analyze','assess','write','audit','finalize')
class PipelineState(TypedDict,total=False):
 run_id:str
 stage:str
 counts:dict
 artifact_refs:dict
 audit_action:str
 audit_attempts:int

def audit_report_references(result):
 known={c['evidence_id'] for c in result.get('claims',[])};issues=[]
 for section in (result.get('report') or {}).get('sections',[]):
  for para in section.get('paragraphs',[]):
   ids=para.get('evidence_ids',[])
   if any(i not in known for i in ids):issues.append({'code':'report_unknown_reference','target':section['section_id'],'detail':'段落引用未包含在本次原文证据中。'})
   if para.get('kind') in {'fact','inference','proposal'} and not ids:issues.append({'code':'report_missing_reference','target':section['section_id'],'detail':'事实、推断或建议缺少原文引用。'})
 return issues

def build_research_graph(handlers,*,on_event=None,observer=None):
 if set(handlers)!=set(STAGES):raise ValueError('Every pipeline stage must have one handler')
 async def emit(event):
  if on_event:
   value=on_event(event)
   if inspect.isawaitable(value):await value
 graph=StateGraph(PipelineState)
 for name in STAGES:
  async def node(state,name=name):
   started=time.monotonic();await emit({'type':'pipeline_stage_started','stage':name})
   async def execute():return await handlers[name](state)
   update=await observer.call(name,execute,inputs=state) if observer else await execute()
   update=update or {}
   if name=='audit' and update.get('audit_action')=='repair':
    if state.get('audit_attempts',0)<1:update['audit_attempts']=1
    else:update['audit_action']='deliver'
   await emit({'type':'pipeline_stage_completed','stage':name,'duration_ms':round((time.monotonic()-started)*1000,2),'counts':update.get('counts',{})})
   return {**update,'stage':name}
  graph.add_node(name,node)
 graph.add_edge(START,'discover')
 for a,b in zip(STAGES[:5],STAGES[1:6]):graph.add_edge(a,b)
 graph.add_conditional_edges('audit',lambda s:'write' if s.get('audit_action')=='repair' and s.get('audit_attempts',0)<=1 else 'finalize',{'write':'write','finalize':'finalize'})
 graph.add_edge('finalize',END)
 return graph.compile()

def suppress_automatic_tracing():
 # Native graph states include original excerpts in the analysis subgraph.
 # Only our explicitly summarized RunTree spans may leave the process.
 try:
  from langsmith import tracing_context
  return tracing_context(enabled=False)
 except ImportError:return nullcontext()
