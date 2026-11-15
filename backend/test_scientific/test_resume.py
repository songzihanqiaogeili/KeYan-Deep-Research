import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.workflow import ResearchWorkflow
from scientific_research.store import Store
from scientific_research.demo import DemoModel, demo_input


class CountingModel(DemoModel):
    identity = 'test-model-v1'
    def __init__(self):
        self.reads = 0
    async def complete(self, role, system, context):
        if role == 'reader':
            self.reads += 1
        return await super().complete(role, system, context)


class ResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_papers_reused_and_progress_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, model = Store(Path(tmp) / 'db'), CountingModel()
            brief, papers = demo_input()
            events = []
            workflow = ResearchWorkflow(model)
            await workflow.run(brief, papers, cache=store, on_event=events.append)
            second = await workflow.run(brief, papers, cache=store, on_event=events.append)
            self.assertEqual(model.reads, 2)
            self.assertEqual(second['metrics']['cached_papers'], 2)
            self.assertTrue(any(e['type'] == 'paper_read' for e in events))

    async def test_different_topic_or_model_does_not_reuse_reader_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, model = Store(Path(tmp) / 'db'), CountingModel()
            brief, papers = demo_input()
            await ResearchWorkflow(model).run(brief, papers, cache=store)
            await ResearchWorkflow(model).run(brief.model_copy(update={'topic': 'different'}), papers, cache=store)
            model.identity = 'test-model-v2'
            await ResearchWorkflow(model).run(brief, papers, cache=store)
            self.assertEqual(model.reads, 6)

    async def test_resume_does_not_reset_model_call_budget(self):
        brief, papers = demo_input()
        model = CountingModel()
        result = await ResearchWorkflow(model).run(brief.model_copy(update={'max_calls': 2}), papers, initial_calls=2)
        self.assertEqual(model.reads, 0)
        self.assertEqual(result['metrics']['model_calls'], 2)
        self.assertEqual(result['status'], 'failed')
