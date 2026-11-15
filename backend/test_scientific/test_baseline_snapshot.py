import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.baseline_snapshot import capture
from scientific_research.demo import demo_input, DemoModel
from scientific_research.store import Store
from scientific_research.workflow import ResearchWorkflow


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_preserves_history_and_does_not_invent_old_call_traces(self):
        work = Path(__file__).resolve().parents[1] / 'eval' / 'scientific' / 'work'
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            root = Path(tmp)
            store = Store(root / 'research.sqlite')
            brief, papers = demo_input()
            row = store.create_run(brief.model_dump(), [p.model_dump() for p in papers], mode='model')
            result = await ResearchWorkflow(DemoModel()).run(brief, papers)
            store.finish(row['id'], result, status=result['status'])
            before = store.get_run(row['id'])
            protocol, score = capture(store.path, root / 'capture', run_id=row['id'])
            self.assertFalse(protocol['trace_available'])
            self.assertEqual(protocol['model_calls_made_during_capture'], 0)
            self.assertEqual(store.get_run(row['id']), before)
            self.assertIsNone(score['task_success'])
            with self.assertRaises(ValueError):
                capture(store.path, root / 'capture', run_id=row['id'])
