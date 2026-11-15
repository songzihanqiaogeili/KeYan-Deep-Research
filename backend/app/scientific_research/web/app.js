'use strict';
const $ = id => document.getElementById(id);
const state = {token: sessionStorage.getItem('research-token') || '', selected: new Map(), papers: [], run: null, cursor: 0, tab: 'overview', events: [], polling: false};
const labels = {queued:'排队中',running:'研究中',completed:'流程完成',degraded:'部分完成 · 有待核验',failed:'执行失败',cancelled:'已取消',interrupted:'运行中断'};
const eventLabels = {queued:'任务已进入持久化队列',resumed:'任务恢复，保留已完成论文缓存',stage_started:'开始阶段',stage_completed:'阶段完成',paper_reading:'正在阅读论文',paper_read:'论文证据已处理',papers_read:'论文阅读结束',model_call_started:'模型调用',similar_work_search:'查询相似工作',completed:'研究流程完成',degraded:'部分结果已交付',failed:'研究执行失败',cancelled:'任务已取消',interrupted:'任务中断',error:'执行错误'};
Object.assign(eventLabels,{literature_source:'检索来源已确认',planning_search:'规划学术检索',search_plan_ready:'检索计划已生成',literature_search:'正在查找论文',literature_search_failed:'部分检索未完成',screening_papers:'筛选相关论文',fetching_fulltext:'获取论文全文',fulltext_ready:'全文已解析',abstract_fallback:'仅摘要可用',literature_ready:'检索准备完成',literature_reused:'复用检索结果'});
const stageLabels = {read:'文献精读',synthesize:'方法比较',propose:'方向设计',review:'证据审核'};
function element(tag, cls, text) { const node = document.createElement(tag); if(cls) node.className=cls; if(text!==undefined) node.textContent=String(text); return node; }
let toastTimer;
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,6500); }
function setConnection(online){
  state.connectionLost=!online;
  let notice=$('connection-notice');
  if(!notice){notice=element('div','notice');notice.id='connection-notice';const text=element('span','','科研后端当前未连接。请双击启动文件启动服务，或点击重新连接；输入的问题会保留在当前标签页。');const button=element('button','secondary','重新连接');button.onclick=()=>connect().then(()=>toast('后端已重新连接')).catch(e=>toast(e.message));notice.append(text,button);document.querySelector('main').prepend(notice);}
  notice.hidden=online;
  if(!online){$('model-status').textContent='后端未连接';$('model-status').className='badge warn';}
  else if(state.modelLabel){$('model-status').textContent=state.modelLabel;$('model-status').className='badge';}
}
async function api(path, options={}) {
  const headers = {...options.headers, Authorization:`Bearer ${state.token}`};
  if(options.body && !(options.body instanceof FormData)) { headers['Content-Type']='application/json'; options={...options,body:JSON.stringify(options.body)}; }
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),path==='/api/search'?45000:15000);
  let response;
  try {response=await fetch(path,{...options,headers,signal:controller.signal});setConnection(true);}
  catch(error){setConnection(false);throw new Error(error.name==='AbortError'?`科研后端请求超时（${location.origin}），请检查服务或稍后重新连接。`:`无法连接科研后端（${location.origin}）。请启动服务后重新连接；不需要重新配置 Ollama。`);}
  finally{clearTimeout(timer);}
  if(!response.ok) { let detail; try {detail=(await response.json()).detail;} catch {detail='服务返回了无效响应';}
    if(response.status===401 && !$('login-dialog').open) $('login-dialog').showModal();
    throw new Error(typeof detail==='string'?detail:`参数校验失败（${response.status}），请检查输入。`);
  }
  return response;
}
async function json(path,options) { return (await api(path,options)).json(); }
function safeLink(url,label) { try {const parsed=new URL(url); if(!['https:','http:'].includes(parsed.protocol)) return element('span','',label); const a=element('a','',label); a.href=parsed.href; a.target='_blank'; a.rel='noopener noreferrer'; return a;} catch{return element('span','',label);} }
function updateSelection(){ $('selected-count').textContent=`已选 ${state.selected.size} / 10`; }
function renderSources(){
  const root=$('sources'); root.replaceChildren();
  if(!state.papers.length){root.append(element('div','empty-small','暂无参考资料。Agent 可自动检索，也可手动补充论文。'));return;}
  for(const paper of state.papers){
    const card=element('article','paper-card'); const check=element('input'); check.type='checkbox'; check.disabled=!paper.document_id; check.checked=state.selected.has(paper.document_id); check.setAttribute('aria-label',`选择 ${paper.title}`);
    check.addEventListener('change',()=>{if(check.checked){if(state.selected.size>=10){check.checked=false;toast('每个任务最多选择 10 篇论文。');return;} state.selected.set(paper.document_id,paper);}else state.selected.delete(paper.document_id);updateSelection();});
    const body=element('div');body.append(element('h3','',paper.title));
    if(paper.abstract)body.append(element('p','',paper.abstract.slice(0,160)+'…'));
    const meta=element('div','paper-meta');meta.append(element('span','',paper.access_level==='abstract'?'摘要资料':'PDF 全文'));
    if(paper.venue)meta.append(element('span','',paper.venue));if(paper.published_at)meta.append(element('span','',paper.published_at.slice(0,10)));
    if(paper.source_url)meta.append(safeLink(paper.source_url,'原始来源 ↗'));
    body.append(meta);card.append(check,body);root.append(card);
  }
  updateSelection();
}
async function refreshHistory(){
  const runs=await json('/api/runs');const root=$('history');root.replaceChildren();
  if(!runs.length)root.append(element('p','subtle','暂无研究记录'));
  for(const run of runs){const button=element('button',state.run?.id===run.id?'selected':'');button.append(element('strong','',run.brief.topic),element('span','',`${labels[run.status]||run.status} · ${new Date(run.created_at).toLocaleDateString('zh-CN')}`));button.onclick=()=>openRun(run.id).catch(e=>toast(e.message));root.append(button);}
}
async function connect(){
  const config=await json('/api/status');$('model-status').textContent=config.model_ready===false?'模型不可用':config.model_configured?`模型${config.model_ready?'可用':'已配置'} · ${config.model}`:'合成演示可用';$('model-status').className='badge '+(config.model_ready===false?'warn':config.model_configured?'good':'');
  state.modelLabel=$('model-status').textContent;
  state.pipelineDefinition=await json('/api/pipeline');
  await json('/api/session',{method:'POST'});
  $('config-hint').textContent=config.model_ready===false?config.model_message:config.model_configured?'研究会自主检索和阅读，再分章节写作并审核报告。':'尚未配置真实模型。可先运行演示、检索与导入文献；配置方式见项目 SCIENTIFIC_RESEARCH.md。';
  const catalog=await json('/api/venue-catalog');$('catalog-status').textContent=`当前 ${catalog.entries.length} 条刊物规则；仅影响新任务。`;
  await refreshHistory();
}
$('login-form').addEventListener('submit',async event=>{event.preventDefault();state.token=$('access-token').value.trim();try{await connect();sessionStorage.setItem('research-token',state.token);$('login-dialog').close();$('login-error').textContent='';}catch(e){$('login-error').textContent=e.message;}});
$('logout').onclick=()=>{$('access-token').value='';$('login-dialog').showModal();};
$('search').onclick=async()=>{const query=$('search-query').value.trim();if(!query){toast('请输入英文科研关键词，例如 multi agent memory。');return;}$('search').disabled=true;$('search-status').textContent='正在检索学术文献…';try{const result=await json('/api/search',{method:'POST',body:{query,limit:10}});const keep=state.papers.filter(p=>state.selected.has(p.document_id));state.papers=[...keep,...result.papers];renderSources();$('search-status').textContent=`${result.audit.provider==='openalex'?'OpenAlex':'arXiv'} 返回 ${result.papers.length} 篇 · 摘要资料`;if(!result.papers.length)toast('本次未找到结果。可以缩短关键词，或上传种子论文。');}catch(e){toast(e.message);$('search-status').textContent='检索未完成，可上传论文继续';}finally{$('search').disabled=false;}};
$('search-query').addEventListener('keydown',e=>{if(e.key==='Enter')$('search').click();});
$('pdf-input').onchange=async()=>{const files=[...$('pdf-input').files];if(files.length+state.selected.size>10){toast('每个任务最多选择 10 篇论文。');return;}try{for(const file of files){if(file.size>25*1024*1024)throw new Error(`${file.name} 超过 25 MB。`);$('search-status').textContent=`正在解析 ${file.name}`;const data=new FormData();data.append('file',file);const paper=await json('/api/documents/pdf',{method:'POST',body:data});state.papers.unshift(paper);state.selected.set(paper.document_id,paper);renderSources();}$('search-status').textContent='PDF 已导入，原文位置按物理页记录';}catch(e){toast(e.message);}finally{$('pdf-input').value='';}};
$('clear-selection').onclick=()=>{state.selected.clear();renderSources();};
async function createRun(mode){
  let body={mode,brief:{topic:'合成趋势演示',research_mode:$('research-mode').value}};
  if(mode==='model'){const topic=$('topic').value.trim();if($('search-entry').value==='paper'&&(!state.selected.size||state.selected.size>3)){toast('以文找文请先上传或选择 1–3 篇种子论文。');return;}if(!topic&&$('search-entry').value!=='paper'){toast('请先填写研究问题。');return;}if(!$('auto-search').checked&&!state.selected.size){toast('关闭自动检索时，请选择参考文献。');return;}body={mode,brief:readBrief(),document_ids:[...state.selected.keys()],auto_search:$('search-entry').value==='paper'||$('auto-search').checked,novelty:$('novelty').checked};}
  const button=$(mode==='demo'?'run-demo':'run-real');button.disabled=true;try{const run=await json('/api/runs',{method:'POST',body});await openRun(run.id);$('run-panel').scrollIntoView({behavior:'smooth',block:'start'});}catch(e){toast(e.message);}finally{button.disabled=false;}
}
$('run-real').onclick=()=>createRun('model');$('run-demo').onclick=()=>createRun('demo');
async function openRun(id){state.eventGeneration=(state.eventGeneration||0)+1;state.cursor=0;state.events=[];state.run={id};state.tab='overview';$('events').replaceChildren();$('run-panel').hidden=false;const run=await json('/api/runs/'+id);if(state.run?.id!==id)return;state.run=run;renderRun();await loadEvents(id);await refreshHistory();if(run.result)$('run-panel').scrollIntoView({behavior:'smooth',block:'start'});}
function renderRun(){
  const run=state.run;if(!run?.brief)return;
  const active=['queued','running'].includes(run.status);
  $('run-title').textContent=run.result?(run.brief.research_mode==='trend'?'方向趋势调研报告':'科研选题报告'):run.brief.topic;
  $('run-status').textContent=(run.result?.delivery?.recommendation_status==='not_ready'&&!run.result?.issues?.some(i=>i.code==='research_stopped_partial'))?'条件核验结束 · 暂不推荐':labels[run.status]||run.status;
  $('run-taskbook').hidden=!run.task_spec;
  if(run.task_spec)renderTaskSpec($('run-taskbook-content'),run.task_spec);
  if(run.result?.delivery?.recommendation_status!=='not_ready'&&run.result?.report?.status==='partial'&&run.result.report.sections?.some(s=>s.paragraphs?.length))$('run-status').textContent='正文已生成 · 审核待修订';
  if(run.result?.report?.format==='branch_review_v1')$('run-status').textContent=run.result.report.status==='ready'?'分支解读已生成 · 待核对':'逐篇解读部分完成';
  $('run-status').className='badge '+(run.status==='completed'?'good':run.status==='degraded'?'warn':'');
  $('demo-banner').hidden=!(run.mode==='demo'||run.result?.synthetic_fixture);
  $('resume-run').textContent=run.result?.report?.status==='partial'?'继续完成报告':run.result?'重新分析':'恢复任务';
  $('cancel-run').hidden=!active;$('resume-run').hidden=!['interrupted','cancelled','degraded','failed'].includes(run.status)||(run.result?.delivery?.recommendation_status==='not_ready'&&!run.result?.issues?.some(i=>i.code==='research_stopped_partial'));
  $('download-md').hidden=!run.result;$('download-json').hidden=!run.result;
  const preview=active&&run.report_preview;
  $('result-area').hidden=!(run.result||preview);$('result-placeholder').hidden=!!(run.result||preview);
  $('result-placeholder').textContent=active?'Agent 正在研究并写作，工具结果与完成章节会自动保存。':run.status==='interrupted'?'任务已中断，恢复后继续未完成的工作。':'尚未形成报告，请查看研究过程中的具体原因。';
  renderPipelineDiagnostics();
  const metrics=$('metrics');metrics.replaceChildren();metrics.append(element('span','',`累计模型调用 ${run.calls} / ${run.brief.max_calls}`),element('span','',`恢复次数 ${run.resume_count}`));
  if(run.result){
    document.querySelector('.event-details').open=false;
    metrics.append(element('span','',`定位证据 ${run.result.claims.length} 条`),element('span','',`缓存命中 ${run.result.metrics.cached_papers||0} 篇`));
    const usage=run.result.metrics.token_usage;if(usage)metrics.append(element('span','',usage.measured_calls?`已测 token ${usage.total_tokens} · ${usage.unmeasured_calls} 次未返回用量`:'Token 未测量（模型未返回 usage）'));
    if(run.result.retrieval)metrics.append(element('span','',run.result.retrieval.passages.mode==='hybrid'?'证据检索：BM25 + 向量':'证据检索：BM25'));
    if(!state.papers.length&&run.result.candidate_papers?.length){state.papers=run.result.candidate_papers;renderSources();$('search-status').textContent=`Agent 检索到 ${state.papers.length} 篇候选（本次记录）`;}
  }
  if(preview)renderWritingPreview($('result-content'),preview);else if(run.result)renderResult();
}
async function loadEvents(id){
 const generation=state.eventGeneration||0,key=id+':'+generation;
 if(state.eventLoad?.key===key)return state.eventLoad.promise;
 const job=(async()=>{
  while(true){
   const events=await json(`/api/runs/${id}/events?after=${state.cursor}`);
   if(state.run?.id!==id||(state.eventGeneration||0)!==generation)return;
   for(const event of events){state.cursor=event.sequence;state.events.push(event);const detail=event.stage?stageLabels[event.stage]:event.message||event.title||event.query||event.paper_id||event.role||event.code||'';$('events').append(element('li','',`${new Date(event.time).toLocaleTimeString('zh-CN')} · ${eventLabels[event.type]||event.type} ${detail}${event.cached?'（缓存复用）':''}`));if($('events').children.length>150)$('events').firstChild.remove();if(['planning_search','literature_search','screening_papers','fetching_fulltext'].includes(event.type))document.querySelector('[data-stage=discover]').className='current';if(['literature_ready','literature_reused'].includes(event.type))document.querySelector('[data-stage=discover]').className='done';if(event.stage){const node=document.querySelector(`[data-stage="${event.stage}"]`);if(node)node.className=event.type.endsWith('completed')?'done':'current';}}
   if(events.length<200)break;
  }
  $('event-count').textContent=`· ${state.events.length} 条事件`;renderPipelineDiagnostics();
 })();
 state.eventLoad={key,promise:job};
 try{await job;}finally{if(state.eventLoad?.promise===job)state.eventLoad=null;}
}
async function poll(){if(state.polling||!state.run?.id)return;state.polling=true;const id=state.run.id;try{if(['queued','running'].includes(state.run.status)){const run=await json('/api/runs/'+id);if(state.run?.id!==id)return;state.run=run;renderRun();await loadEvents(id);if(!['queued','running'].includes(run.status)){await refreshHistory();if(run.result){state.tab='overview';renderResult();$('run-panel').scrollIntoView({behavior:'smooth',block:'start'});}}}}catch(e){toast(e.message);}finally{state.polling=false;}}
setInterval(poll,1200);
$('cancel-run').onclick=async()=>{try{await json(`/api/runs/${state.run.id}/cancel`,{method:'POST'});await openRun(state.run.id);}catch(e){toast(e.message);}};
$('resume-run').onclick=async()=>{try{await json(`/api/runs/${state.run.id}/resume`,{method:'POST'});await openRun(state.run.id);}catch(e){toast(e.message);}};
function download(format){const a=element('a');a.href=`/api/runs/${state.run.id}/export?format=${format}`;a.download=`research-${state.run.id}.${format}`;document.body.append(a);a.click();a.remove();}
$('download-md').onclick=()=>download('md');$('download-json').onclick=()=>download('json');
function tags(ids){const root=element('div','evidence-tags');for(const id of ids||[]){const claim=state.run.result.claims.find(c=>c.evidence_id===id);const button=element('button','evidence-tag',claim?`${claim.paper_id.slice(0,20)} · ${claim.access_level==='abstract'?'摘要':`p.${claim.page}`}`:id.slice(0,12));button.onclick=()=>showEvidence(id);root.append(button);}return root;}
function showEvidence(id){const result=state.run.result;const claim=result.claims.find(c=>c.evidence_id===id);if(!claim)return;const paper=result.papers.find(p=>p.paper_id===claim.paper_id);const root=$('evidence-detail');root.replaceChildren();root.append(element('h3','',paper?.title||claim.paper_id),element('p','evidence-caption',`${claim.access_level==='abstract'?'摘要片段（不是 PDF 页码）':`PDF 物理页 ${claim.page}`} · ${claim.kind==='system_inference'?'系统推断，待核验':claim.kind==='author_limitation'?'作者陈述的局限':'作者主张'} · 引文已定位，语义仍需检查`),element('p','evidence-detail-text',claim.text),element('blockquote','',claim.quote));if(paper?.source_url)root.append(safeLink(paper.source_url,'打开论文来源 ↗'));root.append(element('p','evidence-caption',`证据 ID：${claim.evidence_id}\n文档哈希：${claim.document_hash}`));$('evidence-dialog').showModal();}
$('close-evidence').onclick=()=>$('evidence-dialog').close();
function findings(root,result){for(const [name,items] of [['研究发现',result.findings],['候选研究缺口',result.gaps]]){root.append(element('h3','',name));if(!items?.length)root.append(element('p','hint','本次没有形成足够证据支持的条目。'));for(const item of items||[]){const card=element('article','finding-card');card.append(element('span','finding-label',name),element('p','',item.text),tags(item.evidence_ids));root.append(card);}}}
function matrix(root,result){const wrap=element('div','table-wrap'),table=element('table'),head=element('tr');for(const name of ['论文 / 日期','原文支持的主张','作者陈述的局限','资料范围'])head.append(element('th','',name));const thead=element('thead');thead.append(head);table.append(thead);const body=element('tbody');for(const paper of result.papers){const row=element('tr');row.append(element('td','',`${paper.title}\n${paper.published_at?.slice(0,10)||'发表日期未核验'}`));for(const kind of ['author_claim','author_limitation']){const cell=element('td');const claims=result.claims.filter(c=>c.paper_id===paper.paper_id&&c.kind===kind);for(const claim of claims){cell.append(element('p','',claim.text),tags([claim.evidence_id]));}if(!claims.length)cell.append(element('span','subtle',kind==='author_limitation'&&paper.access_level==='abstract'?'仅摘要，不能核验全文局限':'未提取到可定位证据'));row.append(cell);}row.append(element('td','',paper.access_level==='abstract'?'摘要资料':'上传全文'));body.append(row);}table.append(body);wrap.append(table);root.append(wrap);}
function directions(root,result){result={...result,directions:usableDirections(result)};if(!result.directions.length)root.append(element('p','hint','本次未形成有证据支持的方向候选。请检查未解决问题。'));const names={not_searched:'尚未查新',candidates_found:'发现候选相似工作 · 需人工比较',searched_no_results:'本次查询无结果 · 不代表创新',search_failed:'相似工作检索失败'};for(const [index,d] of result.directions.entries()){const card=element('article','direction-card');card.append(element('span','badge',`方向 ${String(index+1).padStart(2,'0')} · ${names[d.novelty_check_status]||'待核验'}`),element('h3','',d.question));const dl=element('dl');for(const [label,value] of [['研究假设',d.hypothesis],['最小实验',d.minimal_experiment],['对照基线',d.baselines.join('；')],['评价指标',d.metrics.join('；')],['资源估计',d.compute_requirements],['主要风险',d.risks.join('；')],['否定条件',d.falsification_criteria]])dl.append(element('dt','',label),element('dd','',value));card.append(dl,tags(d.evidence_ids));if(d.similar_work?.length){const block=element('div','scope-block');block.append(element('h3','', '关键词查询返回的候选工作'));for(const p of d.similar_work){const paragraph=element('p');paragraph.append(safeLink(p.source_url,p.title));block.append(paragraph);}card.append(block);}root.append(card);}}
function evidence(root,result){for(const claim of result.claims){const card=element('article','finding-card');card.append(element('span','finding-label',`${claim.paper_id} · ${claim.access_level==='abstract'?'摘要片段':`物理页 ${claim.page}`}`),element('p','',claim.text),element('blockquote','',claim.quote),tags([claim.evidence_id]));root.append(card);}}
function scopeDetails(root,result){const block=element('section','scope-block');block.append(element('h3','','资料边界与未解决问题'));const list=element('ul');for(const text of result.limitations||[])list.append(element('li','',text));for(const item of result.issues||[])list.append(element('li','',`${item.code} · ${item.target||''} ${item.detail||''}`));block.append(list);root.append(block);if(result.search_plan){const plan=element('section','scope-block');plan.append(element('h3','','Agent 执行的研究检索计划'),element('pre','',JSON.stringify(result.search_plan,null,2)));root.append(plan);}root.append(element('h3','','已知文献时间线'));const dated=result.papers.filter(p=>p.published_at).sort((a,b)=>a.published_at.localeCompare(b.published_at));if(!dated.length)root.append(element('p','hint','资料未提供可核验的发表日期，本次不生成发展时间线。'));for(const paper of dated){const line=element('div','timeline-row');line.append(element('strong','',paper.published_at.slice(0,10)),element('p','',paper.title));root.append(line);}root.append(element('p','hint','以上只反映本次选中文献的时间分布，不能外推整个领域的发展速度。'));for(const audit of result.search_audit||[]){const section=element('section','scope-block');section.append(element('h3','','执行的检索记录'),element('pre','',JSON.stringify(audit,null,2)));root.append(section);}}
function renderResult(){const root=$('result-content'),result=state.run.result;root.replaceChildren();document.querySelectorAll('[data-tab]').forEach(button=>button.classList.toggle('active',button.dataset.tab===state.tab));({overview,findings,matrix,directions,evidence,scope,arguments:renderArguments}[state.tab]||overview)(root,result);if(state.tab==='overview'){if(result.delivery)renderDelivery(root,result);if(result.trend_coverage)renderTrendCoverage(root,result.trend_coverage);}}
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{state.tab=button.dataset.tab;if(state.run?.result)renderResult();});
$('refresh-history').onclick=()=>refreshHistory().catch(e=>toast(e.message));
$('new-task').onclick=()=>{state.run=null;$('run-panel').hidden=true;$('topic').focus();refreshHistory().catch(()=>{});};
const fragment=new URLSearchParams(location.hash.slice(1));if(fragment.has('access_token')){state.token=fragment.get('access_token');sessionStorage.setItem('research-token',state.token);history.replaceState(null,'',location.pathname);}
if(state.token)connect().catch(e=>{toast(e.message);if(!state.connectionLost)$('login-dialog').showModal();});else $('login-dialog').showModal();

// Preserve the research question across refresh/reconnection in this browser tab.
const draftIds=['topic','constraints','search-query','budget','concurrency','auto-search','novelty','publication-policy','year-from','year-to','target-papers','research-mode','search-entry'];
try {const draft=JSON.parse(sessionStorage.getItem('research-draft')||'{}');for(const id of draftIds){const node=$(id);if(node&&Object.hasOwn(draft,id)){if(node.type==='checkbox')node.checked=!!draft[id];else node.value=String(draft[id]);}}}catch{}
function saveDraft(){const draft={};for(const id of draftIds){const node=$(id);if(node)draft[id]=node.type==='checkbox'?node.checked:node.value;}sessionStorage.setItem('research-draft',JSON.stringify(draft));}
for(const id of draftIds){const node=$(id);if(node){node.addEventListener('input',saveDraft);node.addEventListener('change',saveDraft);}}

Object.assign(eventLabels,{screening_candidates:'本批候选',selection_retry:'修正筛选格式',selection_invalid:'筛选格式无效',selection_diagnostic:'筛选依据',search_refinement:'补充检索'});

// Reports precede execution details; exporting remains optional.
$('run-panel').insertBefore($('result-area'),$('progress'));
$('close-paper').onclick=()=>$('paper-dialog').close();
function relatedItems(result,paper){
  const ids=new Set(result.claims.filter(c=>c.paper_id===paper.paper_id).map(c=>c.evidence_id));
  return {findings:(result.findings||[]).filter(f=>f.evidence_ids.some(id=>ids.has(id))),
          directions:(result.directions||[]).filter(d=>d.evidence_ids.some(id=>ids.has(id)))};
}

function reportExclusions(result){
  const brief=result.brief||state.run.brief||{};
  const terms=[...(brief.excluded_topics||[])];
  const text=(brief.topic||'')+' '+(brief.constraints||'');
  if(/pm\s*2[.]?\s*5/i.test(text)&&/排除|不做|不要|换.{0,6}方向|不行|exclude/i.test(text))terms.push('PM2.5');
  if((result.search_plan?.selection_criteria||[]).some(c=>/exclude.*pm2[.]5|排除.*pm2[.]5/i.test(c)))terms.push('PM2.5');
  return [...new Set(terms)];
}
function usableDirections(result){
  const terms=reportExclusions(result);
  return (result.directions||[]).filter(d=>{
    const text=[d.question,d.hypothesis,d.minimal_experiment,...(d.baselines||[])].join(' ').replace(/\s/g,'').toLowerCase();
    return !terms.some(term=>text.includes(term.replace(/\s/g,'').toLowerCase()))&&/[\u4e00-\u9fff]/.test(d.question);
  });
}
function reportSection(number,title){const section=element('section','report-section');const h=element('h3','section-title');h.append(element('span','section-number',number),document.createTextNode(title));section.append(h);return section;}
function overview(root,result){
  if(result.report){renderNarrativeReport(root,result);return;}
  const usable=usableDirections(result),removed=(result.directions||[]).length-usable.length;
  const notes=result.paper_notes||[];
  const reviewIssues=(result.issues||[]).filter(i=>!['abstract_only','publication_year_unverified'].includes(i.code));
  const hero=element('section','report-summary');hero.append(element('span','report-kicker','研究结论'),element('h2','',usable.length?'已形成选题候选，仍需核验论文资格':'本次尚未形成符合要求的选题建议'));
  hero.append(element('p','',usable.length?`形成 ${usable.length} 个可查看的中文方向候选；本次文献的顶刊资格尚未核实。`:'已找到参考论文，但现有方向不满足排除要求或尚未生成中文解读，暂不作为最终推荐。'));
  const stats=element('div','report-stats');for(const [value,label] of [[result.papers.length,'篇参考论文'],[usable.length,'个可用候选'],[result.papers.filter(p=>p.access_level==='fulltext').length,'篇已获全文']]){const item=element('div');item.append(element('strong','',value),element('span','',label));stats.append(item);}hero.append(stats);root.append(hero);
  const requirement=element('details','report-requirements');requirement.append(element('summary','','查看本次研究要求'),element('p','',result.brief?.topic||state.run.brief.topic));if(result.brief?.constraints)requirement.append(element('p','',result.brief.constraints));root.append(requirement);
  const conclusion=reportSection('01','先看结论');
  if(reviewIssues.length)conclusion.append(element('p','report-warning',`证据审核仍有 ${reviewIssues.length} 项待解决问题。以下是待验证的研究假设，不能视为已成立的方法或最终选题。`));
  if(removed)conclusion.append(element('p','report-warning',`${removed} 个旧方向因涉及排除主题或缺少中文说明，已从推荐区移除。原始记录仍保留。`));
  if(!usable.length){conclusion.append(element('p','','下一步需要按原要求重新分析已有论文，不能直接把旧方向换个标题后作为推荐。'));
    const retry=element('button','primary','按原要求重新分析');retry.disabled=['running','queued'].includes(state.run.status);retry.onclick=()=>$('resume-run').click();conclusion.append(retry,element('p','small-note','复用已有文献，重新调用当前配置的模型；沿用累计调用预算。'));
  }else{for(const [index,d] of usable.entries()){const line=element('div','recommended-direction');line.append(element('span','',String(index+1).padStart(2,'0')),element('p','',d.question));conclusion.append(line);}const button=element('button','secondary','查看选题方案与最小实验');button.onclick=()=>{state.tab='directions';renderResult();};conclusion.append(button);}
  root.append(conclusion);
  const reading=reportSection('02','论文阅读清单');reading.append(element('p','section-description','这两篇论文提供什么参考、与你的目标有什么关系，分别说明。论文资格尚未确认，不代表已满足“顶刊”要求。'));
  for(const [index,paper] of result.papers.entries()){
    const note=notes.find(n=>n.paper_id===paper.paper_id);
    const card=element('article','recommendation-card');
    const heading=element('div','paper-card-heading');heading.append(element('span','paper-order',String(index+1).padStart(2,'0')),element('span','badge',paper.access_level==='abstract'?'摘要可读':'全文文本可读'));card.append(heading);
    card.append(element('h3','',note?.title_zh||'参考论文 '+(index+1)),element('p','original-title',paper.title));
    const meta=element('p','compact-meta',`${paper.venue||'来源未提供'} · ${paper.published_at?.slice(0,10)||'日期未核实'}`);card.append(meta);
    if(note){for(const [label,value] of [['为什么读',note.why_read],['与你的目标的关系',note.relevance],['目前不能确认什么',paper.access_level==='abstract'?'当前仅取得摘要，尚未核验全文方法、数学推导、实验效果及数据代码可用性。':note.limitation]]){const row=element('div','note-row');row.append(element('h4','',label),element('p','',value));card.append(row);}card.append(tags(note.evidence_ids));}
    else{card.append(element('p','missing-analysis','旧结果没有保存可用的中文推荐理由；先保留为参考文献，重新分析后补全。'));}
    const actions=element('div','button-row'),read=element('button','secondary','在线阅读');read.onclick=()=>openPaper(paper);actions.append(read);if(paper.source_url)actions.append(safeLink(paper.source_url,'论文原文 ↗'));card.append(actions);
    const details=element('details','bibliography');details.append(element('summary','','作者、DOI 与级别核验'));const facts=element('dl','paper-facts');for(const [label,value] of [['作者',(paper.authors||[]).join('、')||'未提供'],['DOI',paper.doi||'未提供'],['级别','未核实。尚无指定年度的权威分区或顶刊名单依据。']])facts.append(element('dt','',label),element('dd','',value));details.append(facts);card.append(details);reading.append(card);
  }root.append(reading);
  const limits=reportSection('03','这份报告能支持什么');limits.append(element('p','',result.papers.some(p=>p.access_level==='abstract')?'当前包含摘要资料，可以用来初筛研究问题，不能据此确认全文实验效果或可复现性。':'已取得论文文本，证据语义、实验复现性和期刊级别仍需核验。'),element('p','','尚未确认：顶刊资格、数据与代码是否可用、是否存在相同研究工作。'));root.append(limits);
}
function renderWritingPreview(root,report){
  root.replaceChildren(element('div','notice','正在分节写作，以下为尚未完成审核的草稿；任务结束后会自动切换到正式报告。'));
  for(const section of report.sections||[]){const block=element('section','article-section');block.append(element('h3','',section.title));for(const p of section.paragraphs||[])block.append(element('p','article-paragraph',p.text));root.append(block);}
}
function renderNarrativeReport(root,result){
  const report=result.report,header=element('header','article-header');
  if(result.seed_documents?.length){const seeds=element('details','report-requirements');seeds.append(element('summary','','研究起点：'+result.seed_documents.map(p=>p.title).join('；')),element('p','hint','通过种子论文文本扩展相关工作；关联理由不等于已核验的引用关系。'));for(const p of result.seed_documents)seeds.append(element('p','',p.title),element('blockquote','',p.excerpt||''));root.append(seeds);}
  const conditionOnly=result.delivery?.recommendation_status==='not_ready'&&!result.papers.length;
  const written=(report.sections||[]).filter(s=>s.paragraphs?.length&&s.status==='written').length;
  const progressText=report.format==='branch_review_v1'?'逐篇来源引用已检查 · 解读语义待核对':`${written} / ${(report.sections||[]).length} 章已生成 · ${report.status==='ready'?'系统写作与审核已结束':report.review_completed?'审核仍有待修订意见':'审核尚未完成'}`;
  header.append(element('span','report-kicker','RESEARCH REPORT'),element('h2','',report.title),element('p','article-meta',conditionOnly?'已完成候选条件核验 · 尚无通过条件的推荐资料':`基于 ${result.papers.length} 篇文献 · ${progressText} · 期刊级别尚待核实`));
  root.append(header);
  if(!conditionOnly&&report.status!=='ready')root.append(element('div','notice','研究草稿：模型审核尚有待核验意见，不能作为最终选题推荐。已保留正文，可对照证据阅读或继续修订。'));
  const pending=(report.review_findings||[]).filter(f=>f.severity==='blocking');
  if(pending.length){const list=element('details','report-requirements');list.append(element('summary','',`模型审核提出 ${pending.length} 项待核验意见（可能有误）`));for(const f of pending)list.append(element('p','',f.detail));root.append(list);}
  for(const [index,section] of (report.sections||[]).entries()){
    const block=element('section','article-section');block.id='report-section-'+section.section_id;
    block.append(element('h3','section-title',`${String(index+1).padStart(2,'0')}  ${section.title}`));
    if(!section.paragraphs?.length)block.append(element('p','hint',section.message||'本节尚未完成。'));
    if(section.section_id==='comparison'&&report.paper_matrix?.length){
      const wrap=element('div','table-wrap'),table=element('table'),head=element('tr');for(const title of ['研究分支 / 论文','问题','方法','作者报告的贡献',...(result.seed_documents?.length?['与种子论文关联']:[])])head.append(element('th','',title));const thead=element('thead');thead.append(head);table.append(thead);const body=element('tbody');
      for(const item of report.paper_matrix){const row=element('tr');row.append(element('td','',item.branch+' · '+item.title));for(const field of ['problem','method','contribution']){const cell=element('td');cell.append(element('p','',item[field]?.text||'本次来源未提供可定位信息'),tags(item[field]?.evidence_ids||[]));row.append(cell);}if(result.seed_documents?.length){const source=(result.candidate_papers||[]).find(p=>p.paper_id===item.paper_id);row.append(element('td','',source?.relation_to_seed||'关联尚未核对'));}body.append(row);}table.append(body);wrap.append(table);block.append(wrap);
    }
    for(const paragraph of (section.section_id==='comparison'&&report.paper_matrix?.length?[]:section.paragraphs||[])){
      const text=element('p','article-paragraph');
      if(paragraph.kind==='proposal')text.append(element('span','paragraph-kind','待验证建议'));
      if(paragraph.kind==='limitation')text.classList.add('paragraph-limitation');
      text.append(document.createTextNode(paragraph.text));
      const refs=element('span','inline-citations');
      for(const id of paragraph.evidence_ids||[]){const number=result.claims.findIndex(c=>c.evidence_id===id)+1;const button=element('button','citation-number',`[${number||'?'}]`);button.title='查看这项判断的原文证据';button.onclick=()=>showEvidence(id);refs.append(button);}text.append(refs);block.append(text);
    }root.append(block);
  }
  const papers=element('section','article-section');papers.append(element('h3','section-title','参考论文与在线阅读'));
  const readingPapers=result.reading_recommendations?.length?result.reading_recommendations.map(id=>result.papers.find(p=>p.paper_id===id)).filter(Boolean):result.papers;
  for(const paper of readingPapers){const note=(result.paper_notes||[]).find(n=>n.paper_id===paper.paper_id),card=element('article','reference-card');card.append(element('h4','',note?.title_zh||paper.title));if(note)card.append(element('p','original-title',paper.title));card.append(element('p','compact-meta',`${paper.venue||'来源未提供'} · ${paper.published_at?.slice(0,10)||'日期未核实'} · ${paper.access_level==='abstract'?'仅摘要':'已获全文文本'}`));if(note){card.append(element('h4','','为什么读'),element('p','',note.why_read),element('p','',note.relevance),element('p','hint',note.limitation));}const rule=(result.delivery?.screening||[]).find(r=>r.paper_id===paper.paper_id)?.checks?.find(c=>c.criterion==='journal_rank');if(rule)card.append(element('p','hint',rule.message));const actions=element('div','button-row'),read=element('button','secondary','在线阅读');read.onclick=()=>openPaper(paper);actions.append(read);if(paper.source_url)actions.append(safeLink(paper.source_url,'论文来源 ↗'));card.append(actions);papers.append(card);}if(result.papers.length)root.append(papers);
  const limits=element('details','report-requirements');limits.append(element('summary','','研究要求与报告边界'),element('p','',result.brief.topic),element('p','',report.scope));if(result.papers.some(p=>p.access_level==='abstract'))limits.append(element('p','','当前含摘要资料，未核验全文实验、推导和数据代码可用性。'));root.append(limits);
}
Object.assign(stageLabels,{write:'分节写作与审核'});
Object.assign(eventLabels,{agent_action:'Agent 选择动作',agent_observation:'工具观察',analysis_reused:'复用研究分析',report_outline:'组织报告提纲',report_section_started:'章节写作',report_section_ready:'章节保存',report_section_reused:'章节复用',report_review:'审核报告',report_revising:'局部修订'});
async function openPaper(paper){
  const root=$('paper-reading');root.replaceChildren(element('h3','',paper.title),element('p','hint','正在读取本任务保存的论文文本…'));
  $('paper-dialog').showModal();
  const runId=state.run.id;
  try{
    const saved=await json(`/api/runs/${runId}/papers/${encodeURIComponent(paper.paper_id)}`);
    if(state.run?.id!==runId||!$('paper-dialog').open)return;
    root.replaceChildren(element('h3','',paper.title),element('p','notice',saved.access_level==='abstract'?'仅摘要阅读：当前没有获取全文。下方为实际取得的摘要文本和已提取证据。':'全文文本阅读：以下为实际解析的 PDF 页文本，版式、图表与公式请核对原论文。'));
    if(paper.source_url)root.append(safeLink(paper.source_url,'打开出版方 / 原文来源 ↗'));
    const searchBox=element('div','search-row'),query=element('input'),find=element('button','secondary','查找相关段落'),hits=element('div');query.placeholder='在已保存材料中查找，如 benchmark limitations';query.setAttribute('aria-label','论文内段落查询');searchBox.append(query,find);root.append(searchBox,hits);
    find.onclick=async()=>{try{const data=await json(`/api/runs/${runId}/passages?paper_id=${encodeURIComponent(paper.paper_id)}&query=${encodeURIComponent(query.value)}`);hits.replaceChildren(element('p','hint','关键词段落召回，仅查本任务保存材料；排序不证明语义支持。'));for(const row of data.passages)hits.append(element('p','compact-meta',row.access_level==='abstract'?'摘要片段':`物理页 ${row.page}`),element('blockquote','',row.quote));}catch(e){toast(e.message);}};
    const related=relatedItems(state.run.result,paper);root.append(element('h4','','研究解读'));
    const note=(state.run.result.paper_notes||[]).find(n=>n.paper_id===paper.paper_id);if(note)root.append(element('p','',note.why_read),element('p','',note.relevance));
    if(!related.findings.length)root.append(element('p','hint','尚无可追溯的研究解读。'));
    for(const finding of related.findings)root.append(element('p','',finding.text),tags(finding.evidence_ids));
    root.append(element('h4','',saved.access_level==='abstract'?'原始摘要':'解析原文'));
    for(const page of saved.pages){const section=element('section','reading-page');if(saved.access_level!=='abstract')section.append(element('h4','',`PDF 物理页 ${page.number}`));section.append(element('p','reading-text',page.text));root.append(section);}
  }catch(e){root.replaceChildren(element('h3','',paper.title),element('p','error-text','保存文本暂不可用：'+e.message));if(paper.source_url)root.append(safeLink(paper.source_url,'打开论文来源 ↗'));}
}


function readBrief(){
  const year=id=>$(id).value.trim()===''?null:Number($(id).value);
  return {search_mode:$('search-entry').value,research_mode:$('research-mode').value,max_papers:$('research-mode').value==='trend'?6:10,topic:$('topic').value.trim()||($('search-entry').value==='paper'?'分析种子论文的问题、方法和局限，寻找相关研究、对比工作与可继续研究的切口。':''),constraints:$('constraints').value.trim(),publication_policy:$('publication-policy').value,year_from:year('year-from'),year_to:year('year-to'),target_papers:Number($('target-papers').value),max_calls:Number($('budget').value),max_concurrency:Number($('concurrency').value)};
}
const publicationLabels={any:'不限发表形式',prefer_journal:'优先期刊，级别待核验',journal_only:'仅期刊索引记录，录用待核验',verified_top_only:'必须核验顶刊资格'};
function renderTaskSpec(root,spec){
  root.replaceChildren();const box=element('section','task-book');box.append(element('h3','','本次任务书'));
  const range=spec.year_from||spec.year_to?`${spec.year_from||'不限'} — ${spec.year_to||'不限'}（硬条件）`:spec.preferred_years?.length?spec.preferred_years.join('、')+'（偏好）':'未指定硬性年份';
  const facts=element('dl','task-facts');facts.append(element('dt','','研究入口'),element('dd','',spec.search_mode==='paper'?'以文找文':'以题找文'));
  for(const [label,text] of [['年份',range],['发表条件',publicationLabels[spec.publication_policy]||spec.publication_policy],['参考数量',`${spec.target_papers} 篇；不足时如实说明`],['排除主题',spec.excluded_topics?.join('、')||'未指定'],['资源条件',spec.resource_constraints?'已记录，尚未验证可行性':'未指定']]){facts.append(element('dt','',label),element('dd','',text));}
  box.append(facts);for(const note of spec.interpretation_notes||[])box.append(element('p','hint',note));root.append(box);
}
$('preview-task').onclick=async()=>{
  if(!$('topic').value.trim()&&$('search-entry').value!=='paper'){toast('请先填写研究问题。');return;}
  $('preview-task').disabled=true;
  try{const spec=await json('/api/requirements/preview',{method:'POST',body:readBrief()});renderTaskSpec($('task-preview'),spec);$('task-preview').hidden=false;}
  catch(e){toast(e.message);}finally{$('preview-task').disabled=false;}
};
function renderDelivery(root,result){
  const delivery=result.delivery,box=element('section','delivery-summary');box.append(element('h3','','条件完成情况'),element('p','',delivery.summary));
  const scopes={none:'未获得可推荐资料',abstract:'仅取得摘要',fulltext:'已取得全文文本',mixed:'摘要与全文混合'};
  box.append(element('p','scope-line',`分析资料 ${delivery.qualified_count} 篇 · 重点阅读目标 ${delivery.requested_count} 篇 · ${scopes[delivery.evidence_scope]||delivery.evidence_scope}`));
  if(delivery.resource_status==='unverified')box.append(element('p','hint','资源与周期约束已记录，可执行性尚未核验。'));
  for(const text of delivery.preferences_pending||[])box.append(element('p','hint',text));
  if(delivery.recommendation_status==='not_ready')box.append(element('p','hint','请调整条件或补充可核对资料后新建研究；本次不生成推荐。'));
  const audit=element('button','secondary','查看候选筛选记录');audit.onclick=()=>{state.tab='scope';renderResult();$('result-area').scrollIntoView({behavior:'smooth',block:'start'});};box.append(audit);root.append(box);

}
Object.assign(eventLabels,{requirements_checked:'任务条件已核对'});

function renderTrendCoverage(root,c){
  const box=element('section','scope-block trend-coverage');box.append(element('h3','','本次调研覆盖'),element('p','',`候选 ${c.candidate_count} 条 · 分析 ${c.analyzed_count} 篇 · 全文 ${c.fulltext_count} 篇 · 失败查询 ${c.failed_queries} 次`),element('p','hint',c.scope));
  const years=element('p','compact-meta',Object.entries(c.candidate_years||{}).map(([y,n])=>`${y==='unknown'?'年份未核实':y+' 年'}：${n} 条`).join('；'));box.append(years);root.append(box);
}
function renderArguments(root,result){
  root.append(element('h3','','论点—证据清单'),element('p','hint','引文定位通过不等于推断成立。以下逐条保留表述性质与原文，便于检查。'));
  for(const row of result.argument_ledger||[]){const card=element('article','evidence-card');card.append(element('span','badge',`${row.kind} · ${row.section_id||'研究分析'}`),element('p','',row.text),element('p','hint',row.support_status==='quote_located_semantics_unverified'?'原文已定位，语义支持待核验':row.support_status==='invalid_reference'?'存在无效引用':'未引用证据'),tags(row.evidence_ids));root.append(card);}
  if(!result.argument_ledger?.length)root.append(element('p','hint','本次没有可追溯论点，或旧记录未保存此清单。'));
}
$('catalog-file').onchange=async()=>{
  const file=$('catalog-file').files[0];if(!file)return;
  try{if(file.size>512*1024)throw Error('名单文件最多 512 KB');const body=JSON.parse(await file.text());const result=await json('/api/venue-catalog',{method:'PUT',body});$('catalog-status').textContent=`已保存 ${result.entries.length} 条规则，仅影响新任务；来源真实性待核实。`;toast('刊物名单已保存');}catch(e){toast('名单未保存：'+e.message);}finally{$('catalog-file').value='';}
};

function scope(root,result){if(result.delivery)renderCandidateScreening(root,result);scopeDetails(root,result);}

function renderCandidateScreening(root,result){const delivery=result.delivery;
  const records=element('details','screening-records');records.append(element('summary','',`查看 ${delivery.screening.length} 篇候选的条件核验与淘汰原因`));
  const chosen=new Set(result.papers.map(p=>p.paper_id));
  for(const row of delivery.screening){const item=element('article','screening-row');item.append(element('h4','',row.title),element('span','badge',row.status==='eligible'?(chosen.has(row.paper_id)?'通过硬条件 · 已选参考':'通过硬条件 · 未选入'):row.status==='rejected'?'未满足硬条件':'硬条件待核验'),element('p','',row.reasons.join('；')));const candidate=(result.candidate_papers||[]).find(p=>p.paper_id===row.paper_id);if(candidate?.relevance_reason)item.append(element('p','hint','相关性筛选：'+candidate.relevance_reason));records.append(item);}
  root.append(records);
}

function updateSearchEntry(){const paper=$('search-entry').value==='paper';$('auto-search').disabled=paper;if(paper)$('auto-search').checked=true;$('entry-hint').textContent=paper?'先上传或选择 1–3 篇种子论文；研究目标可留空，也可指定想找的方法、改进或对比工作。':'输入问题后，自动检索并梳理相关研究。';$('topic').placeholder=paper?'可选：例如寻找该论文在3D空间关系建模上的改进与对比方法':'例如：图神经网络如何用于3D场景图中的空间关系建模？';}
$('search-entry').addEventListener('change',updateSearchEntry);updateSearchEntry();

const pipelineLabels={discover:'文献发现',index:'原文索引',analyze:'取证与分析',assess:'范围核验',write:'报告写作',audit:'引用审核',finalize:'结果交付'};
Object.assign(stageLabels,pipelineLabels);
Object.assign(eventLabels,{pipeline_stage_started:'主图阶段开始',pipeline_stage_completed:'主图阶段完成',operation_observation:'操作记录',model_observation:'模型用量记录',retrieval_index_ready:'原文索引已建立',retrieval_selected:'召回阅读片段',retrieval_no_match:'片段覆盖不足',section_evidence_retrieved:'写作证据已召回',seed_candidates_ranked:'种子相关候选排序'});
function renderPipelineDiagnostics(){
 if(!state.run)return;
 let root=$('pipeline-diagnostics');
 if(!root){root=element('details','pipeline-diagnostics');root.id='pipeline-diagnostics';root.append(element('summary','','查看完整工作流与运行诊断'));const nav=element('div','pipeline-nodes');nav.id='pipeline-nodes';const info=element('pre','pipeline-info');info.id='pipeline-info';const definition=element('details');definition.append(element('summary','','查看主图定义（Mermaid）'));const code=element('pre');code.id='pipeline-definition';definition.append(code);root.append(element('p','hint','点击阶段查看耗时、调用用量与产物计数。引用检查通过仍需核对语义。'),nav,info,definition);$('progress').before(root);}
 const nav=$('pipeline-nodes');nav.replaceChildren();const stages=state.pipelineDefinition?.stages||Object.keys(pipelineLabels);
 state.pipelineStage=state.pipelineStage||'discover';
 for(const name of stages){const latest=[...state.events].reverse().find(e=>e.stage===name&&e.type.startsWith('pipeline_stage_'));const button=element('button','pipeline-node '+(latest?.type==='pipeline_stage_completed'?'done':latest?'current':'')+(state.pipelineStage===name?' selected':''),pipelineLabels[name]);button.type='button';button.onclick=()=>{state.pipelineStage=name;renderPipelineDiagnostics();};nav.append(button);}
 const stage=state.pipelineStage,events=state.events;const span=[...events].reverse().find(e=>e.type==='operation_observation'&&e.name===stage);const related=new Set(span?[span.span_id]:[]);for(let i=0;i<12;i++){const size=related.size;for(const e of events)if(related.has(e.parent_id))related.add(e.span_id);if(size===related.size)break;}
 const calls=events.filter(e=>e.type==='model_observation'&&related.has(e.span_id));const measured=calls.filter(e=>e.usage?.total_tokens!=null);const completed=[...events].reverse().find(e=>e.type==='pipeline_stage_completed'&&e.stage===stage);
 $('pipeline-info').textContent=JSON.stringify({阶段:pipelineLabels[stage],状态:completed?'阶段已结束':span?'已记录':'等待执行或正在运行',耗时毫秒:span?.duration_ms??null,模型调用:calls.length,已测Token:measured.length?measured.reduce((n,e)=>n+e.usage.total_tokens,0):null,未测量调用:calls.length-measured.length,产物计数:completed?.counts||{},异常:span?.error_type||null},null,2);
 $('pipeline-definition').textContent=state.pipelineDefinition?.mermaid||'尚未加载主图定义';
}
