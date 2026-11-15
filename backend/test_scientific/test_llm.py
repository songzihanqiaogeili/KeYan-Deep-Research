import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.llm import OpenAIModel

class LocalModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_ollama_qwen_disables_thinking(self):
        model=OpenAIModel.__new__(OpenAIModel);model.model='qwen3.5:4b';model.ollama_qwen=True
        create=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{"selected_ids": ["P1"]}'))]))
        model.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        result=await model.complete('selector','system',{})
        self.assertEqual(result['selected_ids'],['P1'])
        self.assertEqual(create.call_args.kwargs['reasoning_effort'],'none')

    async def test_other_models_do_not_receive_ollama_option(self):
        model=OpenAIModel.__new__(OpenAIModel);model.model='other';model.ollama_qwen=False
        create=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(content='{}'))]))
        model.client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        await model.complete('selector','system',{})
        self.assertNotIn('reasoning_effort',create.call_args.kwargs)
