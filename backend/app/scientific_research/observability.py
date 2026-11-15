"""Metadata-only local spans and explicitly opted-in LangSmith traces."""
import asyncio,functools,inspect,json,math,os,time,uuid
from contextvars import ContextVar
from .tracing import digest

_current=ContextVar('scientific_observer',default=None)

def summary(value):
 text=json.dumps(value,ensure_ascii=False,default=str)
 return {'sha256':digest(text),'characters':len(text),'items':len(value) if isinstance(value,(dict,list,tuple)) else 1}

class LangSmithSink:
 def __init__(self):
  from langsmith import Client,RunTree
  self.tree_type=RunTree
  self.client=Client(api_key=os.environ.get('LANGSMITH_API_KEY'),api_url=os.environ.get('LANGSMITH_ENDPOINT'),timeout_ms=1500,auto_batch_tracing=True,omit_traced_runtime_info=True,run_ops_buffer_size=100,run_ops_buffer_timeout_ms=1000)
  self.project=os.environ.get('LANGSMITH_PROJECT','scientific-research')
 def start(self,name,kind,inputs,parent,metadata):
  tree=parent.create_child(name,run_type=kind,inputs=inputs,extra={'metadata':metadata}) if parent else self.tree_type(name=name,run_type=kind,inputs=inputs,project_name=self.project,ls_client=self.client,extra={'metadata':metadata})
  tree.post();return tree
 def end(self,token,outputs,error,usage):
  if usage:
   outputs={**outputs,'usage_metadata':{'input_tokens':usage.get('prompt_tokens',0),'output_tokens':usage.get('completion_tokens',0),'total_tokens':usage.get('total_tokens',0)}}
  token.end(outputs=outputs,error=error);token.patch()
 def close(self):self.client.flush();self.client.close()

class Observer:
 def __init__(self,run_id,*,sink=None,on_event=None):
  self.run_id=run_id;self.sink=sink;self.on_event=on_event
  self.parent=ContextVar('scientific_span_'+run_id,default=(None,None));self.sink_failed=False
 @classmethod
 def from_env(cls,run_id,*,on_event=None):
  observer=cls(run_id,on_event=on_event)
  if os.environ.get('SCIENTIFIC_LANGSMITH_ENABLED','false').lower() in {'true','1','yes'} and os.environ.get('LANGSMITH_API_KEY'):
   try:observer.sink=LangSmithSink()
   except Exception:observer.sink_failed=True
  return observer
 async def emit(self,event):
  if self.on_event:
   pending=self.on_event(event)
   if inspect.isawaitable(pending):await pending
 async def call(self,name,fn,*,inputs=None,kind='chain',metadata=None,usage=None):
  span_id=uuid.uuid4().hex;parent_id,parent_tree=self.parent.get();tree=None;started=time.monotonic()
  safe_in=summary(inputs);safe_out={};outcome='ok';error=None;actual_usage=None
  if self.sink and not self.sink_failed:
   try:tree=self.sink.start(name,kind,safe_in,parent_tree,metadata or {})
   except Exception:self.sink_failed=True
  context=self.parent.set((span_id,tree));active=_current.set(self)
  try:
   result=await fn();safe_out=summary(result);return result
  except BaseException as exc:
   outcome='cancelled' if isinstance(exc,asyncio.CancelledError) else 'error';error=type(exc).__name__;raise
  finally:
   if usage:
    try:raw=usage()
    except Exception:raw=None
    if isinstance(raw,dict):actual_usage={k:int(v) for k,v in raw.items() if k in {'prompt_tokens','completion_tokens','total_tokens'} and not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v) and v>=0}
   _current.reset(active);self.parent.reset(context)
   if tree is not None and not self.sink_failed:
    try:self.sink.end(tree,safe_out,error,actual_usage)
    except Exception:self.sink_failed=True
   await self.emit({'type':'model_observation' if kind=='llm' else 'operation_observation','span_id':span_id,'parent_id':parent_id,'name':name,'outcome':outcome,'error_type':error,'duration_ms':round((time.monotonic()-started)*1000,2),'input_summary':safe_in,'output_summary':safe_out,'usage':actual_usage,'remote_trace_error':self.sink_failed})
 async def close(self):
  if self.sink and hasattr(self.sink,'close'):
   try:await asyncio.wait_for(asyncio.to_thread(self.sink.close),3)
   except Exception:pass

class ObservedModel:
 def __init__(self,model,observer):
  self.raw=model;self.observer=observer
  self.identity=getattr(model,'identity',type(model).__qualname__)
 def __getattr__(self,name):return getattr(self.raw,name)
 async def complete(self,role,system,context):
  usage_context=getattr(self.raw,'usage_context',None)
  if usage_context:usage_context.set(None)
  return await self.observer.call(role,lambda:self.raw.complete(role,system,context),inputs={'system':system,'context':context},kind='llm',metadata={'ls_provider':'ollama' if getattr(self.raw,'ollama_qwen',False) else 'custom','ls_model_name':getattr(self.raw,'model','fixture')},usage=lambda:usage_context.get() if usage_context else None)
 async def close(self):
  if hasattr(self.raw,'close'):await self.raw.close()

def current_observer():return _current.get()

def observed(name,kind='tool'):
 def decorate(fn):
  @functools.wraps(fn)
  async def wrapped(*args,**kwargs):
   observer=current_observer()
   if observer:return await observer.call(name,lambda:fn(*args,**kwargs),inputs={'arguments':args[1:],'options':kwargs},kind=kind)
   return await fn(*args,**kwargs)
  return wrapped
 return decorate

def usage_totals(events):
 totals={'prompt_tokens':0,'completion_tokens':0,'total_tokens':0,'measured_calls':0,'unmeasured_calls':0};seen=set()
 for e in events:
  if e.get('type')!='model_observation' or e.get('span_id') in seen:continue
  seen.add(e['span_id']);usage=e.get('usage')
  if not usage or any(usage.get(k) is None for k in ('prompt_tokens','completion_tokens','total_tokens')):totals['unmeasured_calls']+=1;continue
  totals['measured_calls']+=1
  for k in ('prompt_tokens','completion_tokens','total_tokens'):totals[k]+=usage[k]
 return totals
