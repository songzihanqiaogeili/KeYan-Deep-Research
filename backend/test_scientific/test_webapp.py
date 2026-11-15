import sys
import tempfile
import time
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from fastapi.testclient import TestClient
from scientific_research.webapp import create_app


class WebAppTests(unittest.TestCase):
    def test_missing_local_ollama_model_is_reported_before_enqueue(self):
        import httpx
        with patch.dict(os.environ,{'SCIENTIFIC_LLM_API_KEY':'ollama',
                'SCIENTIFIC_LLM_MODEL':'qwen3.5:4b','SCIENTIFIC_LLM_BASE_URL':'http://127.0.0.1:11434/v1'}), \
                patch('httpx.AsyncClient.get',new=AsyncMock(return_value=httpx.Response(200,json={'models':[]},request=httpx.Request('GET','http://127.0.0.1:11434/api/tags')))):
            status=self.client.get('/api/status',headers=self.headers).json()
            self.assertFalse(status['model_ready'])
            self.assertEqual(status['model_status'],'model_missing')
            response=self.client.post('/api/runs',json={'mode':'model','brief':{'topic':'x'}},headers=self.headers)
            self.assertEqual(response.status_code,409)
            self.assertIn('qwen3.5:4b',response.json()['detail'])
            self.assertEqual(self.app.state.store.list_runs(),[])

    def test_task_spec_preview_is_authenticated_and_has_no_model_calls(self):
        body={'topic':'必须2026年，优先顶刊'}
        self.assertEqual(self.client.post('/api/requirements/preview',json=body).status_code,401)
        result=self.client.post('/api/requirements/preview',json=body,headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['publication_policy'],'prefer_journal')
        self.assertEqual(result.json()['year_from'],2026)
        self.assertEqual(self.app.state.store.list_runs(),[])

    def test_invalid_task_year_range_is_rejected_before_start(self):
        result=self.client.post('/api/requirements/preview',json={'topic':'2026—2024年论文'},headers=self.headers)
        self.assertEqual(result.status_code,422)
        self.assertEqual(self.app.state.store.list_runs(),[])

    def test_finished_condition_report_requires_new_task_instead_of_repeat_resume(self):
        from scientific_research.demo import DemoModel
        from scientific_research.models import Paper,Page
        paper=Paper(paper_id='p1',title='Fixture',publication_type='journal',published_at='2026-01-02',pages=[Page(number=1,text='Source claim.')])
        doc_id=self.app.state.store.put_document(paper.model_dump())
        with patch.dict(os.environ,{'SCIENTIFIC_LLM_API_KEY':'fixture','SCIENTIFIC_LLM_MODEL':'fixture','SCIENTIFIC_LLM_BASE_URL':'http://example.invalid/v1'}),patch('scientific_research.llm.OpenAIModel',DemoModel):
            response=self.client.post('/api/runs',json={'mode':'model','brief':{'topic':'必须2026年顶刊'},'auto_search':False,'document_ids':[doc_id]},headers=self.headers)
            self.assertEqual(response.status_code,202,response.text)
            ident=response.json()['id']
            for _ in range(100):
                run=self.client.get('/api/runs/'+ident,headers=self.headers).json()
                if run['status'] not in {'queued','running'}: break
                time.sleep(0.02)
            self.assertEqual(run['status'],'degraded')
            self.assertEqual(run['calls'],0)
            self.assertEqual(run['result']['delivery']['requirement_status'],'unverified')
            resumed=self.client.post('/api/runs/'+ident+'/resume',headers=self.headers)
            self.assertEqual(resumed.status_code,409)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(data_dir=Path(self.tmp.name), token='test-token')
        self.ctx = TestClient(self.app)
        self.client = self.ctx.__enter__()
        self.headers = {'Authorization': 'Bearer test-token'}

    def tearDown(self):
        self.ctx.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_api_requires_token_and_rejects_foreign_origin(self):
        self.assertEqual(self.client.get('/api/runs').status_code, 401)
        self.assertEqual(self.client.get('/api/runs', headers={**self.headers, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/runs', headers=self.headers).status_code, 200)

    def test_demo_runs_to_persistent_result_and_export(self):
        response = self.client.post('/api/runs', json={'mode': 'demo'}, headers=self.headers)
        self.assertEqual(response.status_code, 202, response.text)
        ident = response.json()['id']
        for _ in range(100):
            run = self.client.get('/api/runs/' + ident, headers=self.headers).json()
            if run['status'] not in ('queued', 'running'):
                break
            time.sleep(0.05)
        self.assertEqual(run['status'], 'completed', run)
        self.assertTrue(run['result']['synthetic_fixture'])
        paper_id=run['result']['papers'][0]['paper_id']
        reading_url=f'/api/runs/{ident}/papers/{paper_id}'
        self.assertEqual(self.client.get(reading_url).status_code,401)
        reading=self.client.get(reading_url,headers=self.headers)
        self.assertEqual(reading.status_code,200)
        self.assertTrue(reading.json()['pages'])
        self.assertEqual(self.client.get(f'/api/runs/{ident}/papers/missing',headers=self.headers).status_code,404)

        export = self.client.get(f'/api/runs/{ident}/export?format=md', headers=self.headers)
        self.assertIn('合成测试演示', export.text)
        self.assertEqual(self.client.post('/api/session', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(f'/api/runs/{ident}/export?format=md').status_code, 200)
        self.assertEqual(self.client.get('/api/runs').status_code, 401)
        events = self.client.get(f'/api/runs/{ident}/events', headers=self.headers).json()
        self.assertTrue(any(e['type'] == 'paper_read' for e in events))
        self.assertEqual(self.client.post(f'/api/runs/{ident}/resume', headers=self.headers).status_code, 409)

    def test_unknown_document_and_path_rejected(self):
        result = self.client.post('/api/runs', json={'mode': 'model', 'brief': {'topic': 'x'}, 'document_ids': ['../../secret']}, headers=self.headers)
        self.assertIn(result.status_code, (404, 422))

    def test_topic_only_creates_auto_search_task_without_upload(self):
        with patch.dict(os.environ,{'SCIENTIFIC_LLM_API_KEY':'fixture','SCIENTIFIC_LLM_MODEL':'fixture'}), patch.object(self.app.state.runner,'execute',new=AsyncMock()):
            response=self.client.post('/api/runs',json={'mode':'model','brief':{'topic':'研究时空方向，排除 PM2.5'}},headers=self.headers)
            self.assertEqual(response.status_code,202,response.text)
            run=self.app.state.store.get_run(response.json()['id'],include_input=True)
            self.assertTrue(run['input']['auto_search'])
            self.assertEqual(run['input']['papers'],[])

    def test_search_error_is_explicit(self):
        self.app.state.provider.search = AsyncMock(side_effect=ValueError('provider unavailable'))
        response = self.client.post('/api/search', json={'query': 'agent memory', 'limit': 3}, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertIn('arXiv', response.json()['detail'])

    def test_resume_is_rejected_until_cancelled_worker_finishes(self):
        import asyncio
        from scientific_research.demo import DemoModel
        class SlowDemo(DemoModel):
            async def complete(self, role, system, context):
                await asyncio.sleep(0.5)
                return await super().complete(role, system, context)
            async def close(self):
                await asyncio.sleep(0.3)
        with patch('scientific_research.runner.DemoModel', SlowDemo):
            ident = self.client.post('/api/runs', json={'mode':'demo'}, headers=self.headers).json()['id']
            for _ in range(100):
                if self.client.get('/api/runs/' + ident, headers=self.headers).json()['calls']:
                    break
                time.sleep(0.01)
            self.assertEqual(self.client.post(f'/api/runs/{ident}/cancel', headers=self.headers).status_code, 200)
            response = self.client.post(f'/api/runs/{ident}/resume', headers=self.headers)
            self.assertEqual(response.status_code, 409)

    def test_invalid_pdf_is_rejected_without_run(self):
        response = self.client.post('/api/documents/pdf', files={'file': ('bad.pdf', b'not a pdf', 'application/pdf')}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get('/api/runs', headers=self.headers).json(), [])

    def test_static_workbench_and_csp(self):
        self.assertEqual(self.client.get('/healthz').json(),{'service':'scientific-research-workbench','status':'ok'})
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('科研工作台', response.text)
        self.assertIn("default-src 'self'", response.headers['content-security-policy'])
        self.assertEqual(self.client.get('/api/runs', headers={**self.headers, 'Host': 'evil.example'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
