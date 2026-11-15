"""Authenticated loopback research workbench, independent of legacy services."""
import asyncio
import hmac
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request, UploadFile, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from .models import Brief, StrictModel, VenueRule
from .store import Store
from .literature import LiteratureProvider
from .runner import Runner
from .documents import load_pdf
from .demo import demo_input
from .export import markdown
from .middleware import BodyLimit
from .readiness import model_status
from .requirements import build_spec

WEB = Path(__file__).with_name('web')


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=10, ge=1, le=30)


class CatalogRequest(StrictModel):
    entries: list[VenueRule] = Field(default_factory=list,max_length=200)


class RunRequest(StrictModel):
    mode: Literal['demo', 'model'] = 'model'
    brief: Brief | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    novelty: bool = False
    auto_search: bool = True


def create_app(*, data_dir: Path | None = None, token: str | None = None):
    directory = Path(data_dir or os.environ.get('SCIENTIFIC_DATA_DIR') or (Path(__file__).resolve().parents[2] / 'data' / 'scientific'))
    directory.mkdir(parents=True, exist_ok=True)
    store, provider = Store(directory / 'research.sqlite'), LiteratureProvider()
    runner = Runner(store, provider)
    access_token = token or os.environ.get('SCIENTIFIC_LOCAL_TOKEN') or secrets.token_urlsafe(24)

    @asynccontextmanager
    async def lifespan(app):
        await runner.start()
        try:
            yield
        finally:
            await runner.stop()

    app = FastAPI(title='科研工作台', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.provider, app.state.runner = store, provider, runner
    app.state.access_token = access_token

    @app.middleware('http')
    async def protect(request: Request, call_next):
        host = request.url.hostname
        if host not in {'127.0.0.1', 'localhost', '::1', 'testserver'}:
            return JSONResponse({'detail': 'Untrusted Host'}, status_code=400)
        origin = request.headers.get('origin')
        if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
            return JSONResponse({'detail': 'Cross-site request rejected'}, status_code=403)
        if request.url.path.startswith('/api/'):
            supplied = request.headers.get('authorization', '')
            if not supplied and request.method == 'GET' and request.url.path.endswith('/export'):
                supplied = 'Bearer ' + request.cookies.get('research_download', '')
            if not hmac.compare_digest(supplied.encode(), ('Bearer ' + access_token).encode()):
                return JSONResponse({'detail': 'Local access token required'}, status_code=401)
            length = request.headers.get('content-length')
            if length:
                try:
                    if int(length) > 26 * 1024 * 1024:
                        return JSONResponse({'detail': 'Request exceeds 26 MiB'}, status_code=413)
                except ValueError:
                    return JSONResponse({'detail': 'Invalid content length'}, status_code=400)
        response = await call_next(request)
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def get_run(ident):
        run = store.get_run(ident)
        if not run:
            raise HTTPException(404, 'Research run not found')
        return run

    @app.get('/healthz')
    async def health():
        return {'service':'scientific-research-workbench','status':'ok'}

    @app.get('/api/status')
    async def status():
        return {**await model_status(),'local_only':True,'version':'0.4.0',
                'embedding_model':os.environ.get('SCIENTIFIC_EMBEDDING_MODEL','') or None,
                'langsmith_configured':bool(os.environ.get('LANGSMITH_API_KEY')),
                'langsmith_enabled':os.environ.get('SCIENTIFIC_LANGSMITH_ENABLED','false').lower() in {'1','true','yes'}}

    @app.get('/api/pipeline')
    async def pipeline_definition():
        from .pipeline import build_research_graph,STAGES
        async def no_op(state):return {}
        graph=build_research_graph({s:no_op for s in STAGES})
        return {'stages':list(STAGES),'mermaid':graph.get_graph().draw_mermaid(),
                'analysis_subgraph':['read','synthesize','propose','review'],
                'max_reference_repairs':1,'resume_policy':'reinvoke_with_artifact_reuse'}

    @app.get('/api/research-memory')
    async def research_memory(query: str=Query('',max_length=4000)):
        from .research_memory import ResearchMemory
        return {'leads':ResearchMemory(store).retrieve(query),'scope':'historical_search_leads_not_evidence'}

    @app.delete('/api/research-memory/{ident}')
    async def remove_research_memory(ident: str):
        from .research_memory import ResearchMemory
        return {'deleted':bool(ResearchMemory(store).delete(ident)),'history_deleted':False}

    @app.post('/api/session')
    async def download_session():
        response = JSONResponse({'download_session': True})
        response.set_cookie('research_download', access_token, httponly=True, samesite='strict', path='/api/runs', max_age=43200)
        return response

    @app.post('/api/search')
    async def search(body: SearchRequest):
        try:
            result = await provider.search(body.query, limit=body.limit)
        except Exception:
            raise HTTPException(503, 'arXiv 与 OpenAlex 检索均未完成，请检查网络或代理后重试。')
        items = []
        for paper in result['papers']:
            doc_id = store.put_document(paper, audit=result['audit'])
            items.append({**{k: v for k, v in paper.items() if k != 'pages'},
                          'document_id': doc_id, 'abstract': paper['pages'][0]['text']})
        return {'papers': items, 'audit': result['audit']}

    @app.post('/api/documents/pdf')
    async def upload(file: UploadFile):
        import tempfile
        try:
            with tempfile.TemporaryDirectory(dir=directory) as tmp:
                path = Path(tmp) / 'input.pdf'
                total = 0
                with path.open('wb') as target:
                    while chunk := await file.read(1024 * 1024):
                        total += len(chunk)
                        if total > 25 * 1024 * 1024:
                            raise HTTPException(413, 'PDF exceeds 25 MiB')
                        target.write(chunk)
                if not path.read_bytes()[:5] == b'%PDF-':
                    raise ValueError('Invalid PDF signature')
                title = Path((file.filename or 'paper').replace('\\', '/')).stem[:1000] or 'paper'
                paper = await asyncio.to_thread(load_pdf, path, title=title)
            ident = store.put_document(paper.model_dump())
            return {**paper.model_dump(exclude={'pages'}), 'document_id': ident, 'page_count': len(paper.pages)}
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, 'PDF 无法解析。请使用可复制文字的 PDF；扫描件需要先 OCR。')
        finally:
            await file.close()

    def with_catalog(brief):
        if 'venue_catalog' not in brief.model_fields_set:
            saved=store.cache_get('venue-catalog-v1') or {'entries':[]}
            brief=Brief.model_validate({**brief.model_dump(),'venue_catalog':saved['entries']})
        return brief

    @app.get('/api/venue-catalog')
    async def venue_catalog():
        return store.cache_get('venue-catalog-v1') or {'entries':[]}

    @app.put('/api/venue-catalog')
    async def save_venue_catalog(body: CatalogRequest):
        store.cache_put('venue-catalog-v1',body.model_dump())
        return body.model_dump()

    @app.post('/api/requirements/preview')
    async def preview_requirements(body: Brief):
        try: return build_spec(with_catalog(body)).model_dump()
        except ValueError as exc: raise HTTPException(422,str(exc))

    @app.post('/api/runs', status_code=202)
    async def create_run(body: RunRequest):
        audits = []
        if body.mode=='model' and body.brief and body.brief.search_mode=='paper' and (not body.auto_search or not 1<=len(body.document_ids)<=3):
            raise HTTPException(422,'以文找文需要选择 1–3 篇种子论文并开启自动检索。')
        if body.brief:
            try: build_spec(body.brief)
            except ValueError as exc: raise HTTPException(422,str(exc))
        if body.mode == 'demo':
            if body.document_ids or body.novelty:
                raise HTTPException(422, 'Demo only uses synthetic documents and never performs online novelty search')
            brief, papers = demo_input()
            brief=brief.model_copy(update={'write_report':True,'research_mode':body.brief.research_mode if body.brief else 'focused'})
        else:
            if not body.brief or (not body.auto_search and not body.document_ids):
                raise HTTPException(422, '请填写研究问题；关闭自动检索时才需要选择参考文献。')
            papers = []
            for ident in body.document_ids:
                paper = store.get_document(ident)
                if not paper:
                    raise HTTPException(404, 'Document not found')
                papers.append(paper)
                audit = store.document_audit(ident)
                if audit and audit not in audits:
                    audits.append(audit)
            if body.brief.search_mode=='paper' and (not body.auto_search or not 1<=len(body.document_ids)<=3):
                raise HTTPException(422,'以文找文需要选择 1–3 篇种子论文并开启自动检索。')
            if not os.environ.get('SCIENTIFIC_LLM_API_KEY') or not os.environ.get('SCIENTIFIC_LLM_MODEL'):
                raise HTTPException(409, '真实分析尚未配置模型。请设置独立环境变量后重启，或先运行合成演示。')
            availability=await model_status()
            if availability['model_ready'] is False:
                raise HTTPException(409,availability['model_message'])
            defaults={key:True for key in ('agent_loop','write_report') if key not in body.brief.model_fields_set}
            brief = with_catalog(body.brief).model_copy(update=defaults)
        try:
            return store.create_run(brief.model_dump(), [p.model_dump() if hasattr(p, 'model_dump') else p for p in papers], mode=body.mode, novelty=body.novelty, audit=audits,auto_search=body.auto_search and body.mode!='demo')
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get('/api/runs')
    async def list_runs():
        return store.list_runs()

    @app.get('/api/runs/{ident}')
    async def run_detail(ident: str):
        value=get_run(ident)
        if value['status'] in {'queued','running'}:
            progress=store.get_run(ident,include_input=True)['input'].get('report_progress') or {}
            if progress.get('drafts'):
                value['report_preview']={'status':'writing','sections':list(progress['drafts'].values())}
        return value

    @app.post('/api/runs/{ident}/cancel')
    async def cancel(ident: str):
        run = get_run(ident)
        if run['status'] not in {'queued', 'running'}:
            raise HTTPException(409, 'Only queued or running tasks can be cancelled')
        runner.cancel(ident)
        return get_run(ident)

    @app.post('/api/runs/{ident}/resume', status_code=202)
    async def resume(ident: str):
        run = get_run(ident)
        if runner.active_id == ident and runner.active_task and not runner.active_task.done():
            raise HTTPException(409, '任务仍在结束或取消中，请稍后恢复。')
        if run.get('result',{} ) and run['result'].get('delivery',{}).get('recommendation_status')=='not_ready' and not any(i['code']=='research_stopped_partial' for i in run['result'].get('issues',[])):
            raise HTTPException(409,'任务已交付条件核验结果，请调整条件或补充资料后新建研究。')
        if run['calls'] >= run['brief']['max_calls']:
            raise HTTPException(409, '累计模型调用预算已耗尽，恢复不会重置预算。')
        if run['mode']=='model':
            availability=await model_status()
            if availability['model_ready'] is False:
                raise HTTPException(409,availability['model_message'])
        stored=store.get_run(ident,include_input=True)['input']['brief']
        if run['mode']=='model' and any(k not in stored for k in ('agent_loop','write_report')):
            upgraded=Brief.model_validate({**stored,**{k:True for k in ('agent_loop','write_report') if k not in stored}})
            store.patch_input(ident,{'brief':upgraded.model_dump()})
        try:
            store.resume(ident)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return get_run(ident)

    @app.get('/api/runs/{ident}/passages')
    async def passages(ident: str, paper_id: str, query: str = ''):
        from .models import Paper
        from .retrieval import retrieve_passages
        if len(query)>500:raise HTTPException(422,'Query exceeds 500 characters')
        get_run(ident)
        payload=store.get_run(ident,include_input=True)['input']
        material=next((p for p in payload['papers'] if p['paper_id']==paper_id),None)
        if material is None:raise HTTPException(404,'Paper not in this task')
        return {'passages':retrieve_passages(Paper.model_validate(material),query),'method':'bm25_passage_retrieval','semantic_support_verified':False}

    @app.get('/api/runs/{ident}/papers/{paper_id}')
    async def read_paper(ident: str, paper_id: str):
        run=get_run(ident)
        if not run.get('result') or paper_id not in {p['paper_id'] for p in run['result']['papers']}:
            raise HTTPException(404, 'Selected paper not found')
        payload=store.get_run(ident,include_input=True)['input']
        for paper in payload.get('papers',[]):
            if paper['paper_id']==paper_id:
                return paper
        raise HTTPException(404, 'Saved paper text unavailable')

    @app.get('/api/runs/{ident}/events')
    async def events(ident: str, after: int = 0):
        get_run(ident)
        return store.events(ident, after=max(0, after))

    @app.get('/api/runs/{ident}/stream')
    async def stream(ident: str, request: Request, after: int = 0):
        get_run(ident)
        async def generate():
            cursor = max(0, after)
            while not await request.is_disconnected():
                batch = store.events(ident, after=cursor)
                for event in batch:
                    cursor = event['sequence']
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if get_run(ident)['status'] not in {'queued', 'running'} and len(batch) < 200:
                    break
                yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(generate(), media_type='text/event-stream')

    @app.get('/api/runs/{ident}/export')
    async def export(ident: str, format: Literal['json', 'md'] = 'json'):
        result = get_run(ident)['result']
        if not result:
            raise HTTPException(409, 'No result available yet')
        text = markdown(result) if format == 'md' else json.dumps(result, ensure_ascii=False, indent=2)
        return Response(text, media_type='text/markdown' if format == 'md' else 'application/json',
                        headers={'Content-Disposition': f'attachment; filename="research-{result["run_id"]}.{format}"'})

    @app.get('/')
    async def index():
        return FileResponse(WEB / 'index.html', media_type='text/html', headers={'Cache-Control':'no-cache'})

    app.mount('/static', StaticFiles(directory=WEB, check_dir=False), name='static')
    app.add_middleware(BodyLimit)
    return app
