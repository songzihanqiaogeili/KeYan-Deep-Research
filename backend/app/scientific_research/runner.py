"""Single local worker, persistent queue, explicit interruption and resume."""
import asyncio
import os
import copy
import time
from pathlib import Path
from .models import Brief, Paper
from .workflow import ResearchWorkflow
from .demo import DemoModel
from .documents import merge_materials
from .quality import excluded_topics
from .skills import load_skill
from .tracing import digest
from .requirements import build_spec, assess_delivery


class DirectoryLock:
    def __init__(self, path: Path):
        self.path, self.file = path, None

    def acquire(self):
        try:
            self.file = self.path.open('a+b')
            if self.path.stat().st_size == 0:
                self.file.write(b'0')
                self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self.file:
                self.file.close()
            self.file = None
            raise RuntimeError('This data directory already has a running research worker')

    def release(self):
        if self.file:
            self.file.close()
            self.file = None


class Runner:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.active_id = self.active_task = self.worker = None
        self.stopping = False
        self.lock = DirectoryLock(store.path.with_suffix('.lock'))

    async def start(self):
        self.lock.acquire()
        self.store.mark_interrupted()
        self.worker = asyncio.create_task(self.loop())

    async def stop(self):
        self.stopping = True
        if self.active_task:
            self.active_task.cancel()
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        self.lock.release()

    async def loop(self):
        while True:
            run = self.store.claim_next()
            if not run:
                await asyncio.sleep(0.2)
                continue
            self.active_id = run['id']
            self.active_task = asyncio.create_task(self.execute(run))
            try:
                await self.active_task
            except asyncio.CancelledError:
                if self.stopping:
                    raise
            finally:
                self.active_id = self.active_task = None

    def cancel(self, ident):
        self.store.cancel(ident)
        if self.active_id == ident and self.active_task:
            self.active_task.cancel()

    async def execute(self, run):
        ident, model = run['id'], None
        observer=None
        embedder=None
        started = asyncio.get_running_loop().time()
        try:
            if run['mode'] == 'demo':
                model = DemoModel()
            else:
                from .llm import OpenAIModel
                model = OpenAIModel()
            payload = run['input']

            def on_event(event):
                if event['type'] == 'model_call_started':
                    self.store.increment_calls(ident)
                if event['type'] == 'search_plan_ready':
                    self.store.save_search_plan(ident, event['plan'])
                self.store.event(ident, event)

            from .observability import Observer,ObservedModel
            observer=Observer.from_env(ident,on_event=on_event)
            model=ObservedModel(model,observer)
            from .embeddings import OllamaEmbeddings
            embedder=OllamaEmbeddings.from_env() if not getattr(model,'fixture',False) else None
            brief=Brief.model_validate(payload['brief'])
            brief=brief.model_copy(update={'excluded_topics':excluded_topics(brief)})
            from .research_memory import ResearchMemory
            from .context_engine import ScopedModel
            try:memory=ResearchMemory(self.store)
            except Exception as exc:
                memory=None;on_event({'type':'memory_unavailable','error_type':type(exc).__name__})
            leads=payload.get('memory_snapshot')
            if leads is None:
                try:leads=memory.retrieve(brief.topic,exclude_run_id=ident) if run['mode']=='model' and memory else []
                except Exception as exc:
                    leads=[];on_event({'type':'memory_unavailable','error_type':type(exc).__name__})
                self.store.patch_input(ident,{'memory_snapshot':leads})
            model=ScopedModel(model,leads=leads,on_event=on_event)
            on_event({'type':'memory_recalled','count':len(leads),'scope':'historical_search_leads_only'})
            def reserve_call(role):
                count=self.store.get_run(ident)['calls']
                if count>=brief.max_calls:
                    raise RuntimeError('call_budget_exhausted')
                on_event({'type':'model_call_started','role':role,'calls':count+1})
            result=None;materials=[];retriever=None;evidence_index=None
            from .pipeline import build_research_graph,audit_report_references,suppress_automatic_tracing
            async def discover(state):
                nonlocal payload
                if payload.get('auto_search') and not payload.get('discovery_complete'):
                    from .discovery import discover
                    remaining=brief.timeout_seconds-(asyncio.get_running_loop().time()-started)
                    if brief.research_mode=='trend' or brief.search_mode=='paper':
                        from .trend import collect_trend
                        from .rag import SeedRanker
                        pending=collect_trend(brief,model,self.provider,seeds=payload.get('seed_papers',payload['papers']),
                            saved_state=payload.get('trend_progress'),on_checkpoint=lambda state:self.store.patch_input(ident,{'trend_progress':state}),
                            on_event=on_event,reserve_call=reserve_call,ranker=SeedRanker(embedder) if embedder else None)
                    elif brief.agent_loop:
                        from .agent_loop import research
                        pending=research(brief,model,self.provider,seeds=payload.get('seed_papers',payload['papers']),
                            saved_state=payload.get('agent_progress'),saved_plan=payload.get('pending_search_plan'),
                            on_checkpoint=lambda state:self.store.patch_input(ident,{'agent_progress':state}),
                            on_event=on_event,reserve_call=reserve_call)
                    else:
                        pending=discover(brief,model,self.provider,on_event=on_event,reserve_call=reserve_call,saved_plan=payload.get('pending_search_plan'))
                    found=await asyncio.wait_for(pending,timeout=max(0.01,remaining))
                    self.store.save_discovery(ident,found)
                    payload=self.store.get_run(ident,include_input=True)['input']
                elif payload.get('discovery_complete'):
                    self.store.event(ident,{'type':'literature_reused','message':'复用已完成的检索和全文获取结果'})

                return {'counts':{'papers':len(payload['papers'])},'artifact_refs':{'input':ident}}
            async def index(state):
                nonlocal materials,retriever
                from .rag import TaskIndex,passage_records
                materials=merge_materials([Paper.model_validate(p) for p in payload['papers']])
                retriever=TaskIndex(passage_records(materials),embedder=embedder,
                                    deadline=time.monotonic()+max(0,brief.timeout_seconds-(asyncio.get_running_loop().time()-started)))
                await retriever.build()
                on_event({'type':'retrieval_index_ready','mode':retriever.mode,
                          'fallback_reason':retriever.fallback_reason,**retriever.metrics})
                return {'counts':{'documents':len(materials),'chunks':len(retriever.records)}}
            async def analyze(state):
                nonlocal result
                remaining=brief.timeout_seconds-(asyncio.get_running_loop().time()-started)
                if remaining<=0:
                    raise asyncio.TimeoutError()
                effective_brief=brief.model_copy(update={'timeout_seconds':max(1,int(remaining))})

                analysis_key=digest({'contract':'trend-contract-v2','brief':brief.model_dump(),'papers':payload['papers'],'retriever':retriever.identity,
                    'model':getattr(model,'identity',type(model).__qualname__),
                    'skills':[load_skill(r) for r in ('reader','synthesizer','proposer','reviewer')]})
                initial_retrieval_identity=retriever.identity
                saved_analysis=payload.get('analysis_snapshot') or {}
                previous=saved_analysis.get('result',{})
                retry_codes={'run_timeout','reader_failed','synthesis_failed','proposal_failed','review_failed',
                             'no_located_evidence','no_supported_synthesis','no_supported_directions',
                             'unlocated_quote','invalid_claim','invalid_model_output','invalid_paper_note',
                             'invalid_or_unknown_evidence','requirement_conflict','context_budget_exhausted'}
                reusable=previous.get('claims') and not any(i['code'] in retry_codes for i in previous.get('issues',[]))
                if brief.write_report and saved_analysis.get('key')==analysis_key and reusable:
                    result=copy.deepcopy(saved_analysis['result'])
                    on_event({'type':'analysis_reused','message':'复用已完成的证据提取和分析，继续报告写作'})
                else:
                    result = await ResearchWorkflow(model).run(
                        effective_brief, materials,
                        cache=self.store, on_event=on_event, initial_calls=self.store.get_run(ident)['calls'],retriever=retriever)
                    if brief.write_report:
                        safe_key=analysis_key if retriever.identity==initial_retrieval_identity else 'invalidated_retrieval_mode:'+analysis_key
                        self.store.patch_input(ident,{'analysis_snapshot':{'key':safe_key,'result':result}})
                return {'counts':{'claims':len(result['claims'])},'artifact_refs':{'analysis':ident+':analysis_snapshot'}}
            async def assess(state):
                result['run_id'] = ident
                result['brief']=brief.model_dump()
                result['search_audit'] = payload.get('search_audit', [])
                result['search_plan']=payload.get('search_plan')
                result['candidate_papers']=payload.get('candidate_papers',[])
                result['seed_documents']=payload.get('seed_documents',[])
                result['seed_ranking']=payload.get('seed_ranking',{})
                result['loop_metrics']=payload.get('loop_metrics',{})
                spec=build_spec(brief)
                corpus=payload.get('agent_progress',{}).get('papers') or payload.get('candidate_papers',[])+payload['papers']
                chosen_ids={p['paper_id'] for p in result['papers']}
                chosen=[p for p in payload['papers'] if p['paper_id'] in chosen_ids]
                if brief.research_mode=='trend':
                    from .trend import trend_coverage
                    result['trend_coverage']=trend_coverage(result['candidate_papers'] or chosen,result['papers'],result['search_audit'])
                result['task_spec']=spec.model_dump()
                result['delivery']=assess_delivery(spec,chosen,corpus)
                if not chosen and any(i['code']=='requirements_not_satisfied' for i in payload.get('discovery_issues',[])):
                    result['status']='degraded'
                result['delivery']['execution_status']='failed' if result['status']=='failed' else 'completed'
                on_event({'type':'requirements_checked','message':result['delivery']['summary']})
                result['issues'].extend(payload.get('discovery_issues',[]))
                if result['issues'] and result['status']=='completed':
                    result['status']='degraded'
                result['limitations'][0] = ('研究范围限于本次导入/选中的文献；学术索引元数据与摘要不构成完整领域综述。'
                                            if result['search_audit'] else '研究范围限于本次导入文献，未进行在线文献扩展。')
                if payload.get('auto_search'):
                    result['limitations'].append('自动检索来自 arXiv/OpenAlex，收录或期刊名称不证明顶会/顶刊资格，录用与级别需要核验。')
                result['limitations'].append(
                    f"任务内索引保存 {len(retriever.records)} 个片段窗口（估计可用 {retriever.metrics['available_records']} 个）；"
                    "全文采用定向片段阅读，不能据此声称完整核验实验、公式和表格。")
                if payload.get('novelty') and run['mode'] != 'demo':
                    result['limitations'].append('已尝试 arXiv 关键词相似工作查询，结果需要人工比较；无结果不代表方向创新。')
                    deadline = started + payload['brief']['timeout_seconds']
                    for direction in result['directions']:
                        self.store.event(ident, {'type': 'similar_work_search', 'question': direction['question']})
                        query = direction.get('search_query') or direction['question'][:300]
                        try:
                            remaining = deadline - asyncio.get_running_loop().time()
                            if remaining <= 0:
                                raise asyncio.TimeoutError()
                            found = await asyncio.wait_for(self.provider.search(query, limit=5), timeout=min(30, remaining))
                            direction['similar_work'] = [{k: p[k] for k in ('title', 'source_url', 'arxiv_id', 'published_at')} for p in found['papers']]
                            direction['novelty_check_status'] = 'candidates_found' if found['papers'] else 'searched_no_results'
                            direction['search_audit'] = found['audit']
                            result['search_audit'].append(found['audit'])
                        except Exception:
                            direction['novelty_check_status'] = 'search_failed'
                            direction['similar_work'] = []
                            result['issues'].append({'code': 'similar_work_search_failed', 'target': direction['question'], 'detail': 'Public arXiv search unavailable; novelty is not assessed.'})
                        if direction['novelty_check_status'] == 'candidates_found':
                            result['issues'].append({'code': 'similar_work_requires_human_review', 'target': direction['question'], 'detail': 'Keyword candidates do not establish semantic equivalence or novelty.'})
                    if result['issues'] and result['status'] == 'completed':
                        result['status'] = 'degraded'
                return {'counts':{'qualified':result['delivery']['qualified_count']}}
            async def write(state):
                nonlocal evidence_index
                from .rag import TaskIndex,claim_records
                if not brief.write_report:return {'counts':{'report_requested':0}}
                if evidence_index is None:
                    evidence_index=TaskIndex(claim_records(result),embedder=embedder,
                        deadline=time.monotonic()+max(0,brief.timeout_seconds-(asyncio.get_running_loop().time()-started)))
                    await evidence_index.build()
                if brief.write_report:
                    from .reporting import compose_report
                    progress=self.store.get_run(ident,include_input=True)['input'].get('report_progress')
                    remaining=brief.timeout_seconds-(asyncio.get_running_loop().time()-started)
                    result['report']=await compose_report(result,model,saved_state=progress,
                        deadline=time.monotonic()+max(0,remaining),on_event=on_event,reserve_call=reserve_call,
                        on_checkpoint=lambda state:self.store.patch_input(ident,{'report_progress':state}),
                        evidence_index=evidence_index)
                    result['metrics']['model_calls']=self.store.get_run(ident)['calls']
                    if result['report']['status']!='ready':
                        result['issues'].append({'code':'report_partial','target':'report','detail':'报告部分章节或审核尚未完成，已保存进度。'})
                        if result['status']=='completed': result['status']='degraded'
                return {'artifact_refs':{'report':ident+':report_progress'}}
            async def audit(state):
                problems=audit_report_references(result)
                result['reference_audit']={'scope':'reference_integrity_only','semantic_support_verified':False,'issues':problems}
                if problems and not state.get('audit_attempts'):
                    progress=copy.deepcopy(self.store.get_run(ident,include_input=True)['input'].get('report_progress') or {})
                    progress['complete']=None
                    for problem in problems:progress.get('drafts',{}).pop(problem['target'],None)
                    known={c['evidence_id'] for c in result['claims']}
                    for pid,profile in list(progress.get('profiles',{}).items()):
                        if any(set(field.get('evidence_ids',[]))-known for field in profile.values() if isinstance(field,dict)):progress['profiles'].pop(pid)
                    self.store.patch_input(ident,{'report_progress':progress})
                    return {'audit_action':'repair','counts':{'reference_errors':len(problems)}}
                if problems:
                    result['issues'].extend(problems)
                    result['status']='degraded'
                    result['report']['status']='partial'
                    result['report'].setdefault('issues',[]).extend(problems)
                    progress=copy.deepcopy(self.store.get_run(ident,include_input=True)['input'].get('report_progress') or {})
                    progress['complete']=copy.deepcopy(result['report'])
                    self.store.patch_input(ident,{'report_progress':progress})
                return {'audit_action':'deliver','counts':{'reference_errors':len(problems)}}
            async def finalize(state):
                if (result.get('report') or {}).get('format')=='branch_review_v1':
                    report=result['report']
                    result['reading_recommendations']=report['reading_ids']
                    result['paper_notes']=[{'paper_id':p['paper_id'],'title_zh':p['branch']+'：'+p['title'],'why_read':(p.get('contribution') or p['problem'])['text'],'relevance':p['reading_value']['text'],'limitation':'当前为来源文本解读，语义与实验效果未独立核验。','evidence_ids':p['reading_value']['evidence_ids']} for p in report['paper_matrix'] if p.get('reading_value')]
                else:
                    result['reading_recommendations']=[n['paper_id'] for n in result.get('paper_notes',[]) if any(c['paper_id']==n['paper_id'] for c in result['claims'])][:brief.target_papers]
                from .trend import argument_ledger
                result['argument_ledger']=argument_ledger(result)
                result['metrics']['token_usage']=self.store.usage_summary(ident)
                result['retrieval']={'passages':{**retriever.metrics,'mode':retriever.mode,'fallback_reason':retriever.fallback_reason},
                                     'evidence':{**evidence_index.metrics,'mode':evidence_index.mode,'fallback_reason':evidence_index.fallback_reason} if evidence_index else {'records':0,'mode':'not_requested'},
                                     'embeddings':embedder.metrics if embedder else None,
                                     'scope':'task_local_index_not_global_literature_search'}
                result['observability']={'langsmith_enabled':observer.sink is not None,'remote_trace_error':observer.sink_failed,'content_policy':'hashes_counts_usage_only'}
                from .report_diagnostics import diagnose_report
                result['report_diagnostics']=diagnose_report(result)
                result['memory']={'recalled_count':len(leads),'use':'search_hints_not_evidence','saved':False}
                if run['mode']=='model' and memory:
                    try:
                        result['memory']['saved']=bool(memory.remember(ident,result))
                    except Exception as exc:
                        on_event({'type':'memory_write_failed','error_type':type(exc).__name__})
                self.store.finish(ident, result, status=result['status'])
                return {'artifact_refs':{'result':ident}}
            def pipeline_event(event):
                if self.store.get_run(ident)['status']=='cancelled':raise asyncio.CancelledError()
                on_event(event)
                if event['type']=='pipeline_stage_completed':self.store.patch_input(ident,{'pipeline_progress':{'stage':event['stage'],'counts':event['counts'],'resume_policy':'reinvoke_with_artifact_reuse'}})
            graph=build_research_graph({name:handler for name,handler in [('discover',discover),('index',index),('analyze',analyze),('assess',assess),('write',write),('audit',audit),('finalize',finalize)]},on_event=pipeline_event,observer=observer)
            with suppress_automatic_tracing():
                await asyncio.wait_for(observer.call('research',lambda:graph.ainvoke({'run_id':ident},config={'recursion_limit':16}),inputs={'run_id':ident,'search_mode':brief.search_mode}),timeout=brief.timeout_seconds)
        except asyncio.CancelledError:
            status = 'interrupted' if self.stopping else 'cancelled'
            self.store.finish(ident, run.get('result'), status=status)
            raise
        except Exception as exc:
            messages={'search_planning_failed':'检索规划失败：模型未返回有效检索计划，请检查模型响应和预算。',
                      'TimeoutError':'研究达到总时限；已保存成功阶段和调用次数，可恢复任务继续。',
                      'no_papers_found':'检索已执行，但没有找到候选论文；可调整问题范围或关键词后创建新任务。',
                      'literature_sources_unavailable':'在线论文检索未成功，任务未获得可阅读资料；请检查网络后恢复任务。',
                      'selection_has_no_valid_papers':'未筛选出符合研究问题的真实论文，不生成虚构资料。',
                      'selection_output_invalid':'筛选模型返回格式或编号无效，修正重试后仍失败；查看筛选事件。恢复将复用检索计划，累计预算不重置。',
                      'no_matching_papers':'检索和有限补检完成，但没有筛出满足原要求的论文。查看候选及淘汰理由；若允许往年或预印本，请修改要求另建任务。',
                      'research_incomplete':'研究循环未获得可用的已读材料，工具结果已保存。请查看过程中的来源或动作错误。',
                      'call_budget_exhausted':'累计模型调用预算已耗尽，规划和筛选同样计入预算。'}
            code=str(exc) if str(exc) in messages else type(exc).__name__
            self.store.event(ident, {'type': 'error', 'code': code, 'message': messages.get(code,'研究执行未完成，已完成的论文缓存会保留。')})
            self.store.finish(ident, run.get('result'), status='failed')
        finally:
            if model and hasattr(model, 'close'):
                await model.close()
            if observer:await observer.close()
            if embedder:await embedder.close()
