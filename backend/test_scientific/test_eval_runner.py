import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.eval_runner import run_suite, usage_summary


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def test_partial_usage_is_not_presented_as_complete_total(self):
        usage = usage_summary([{'total_tokens': 10}, None])
        self.assertFalse(usage['complete'])
        self.assertIsNone(usage['total_tokens'])
        self.assertEqual(usage['observed_total_tokens'], 10)

    async def test_frozen_baseline_is_labeled_resumable_and_will_not_mix_splits(self):
        work = Path(__file__).resolve().parents[1] / 'eval' / 'scientific' / 'work'
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            out = Path(tmp) / 'baseline'
            first = await run_suite(out, split='dev', model_kind='fixture')
            self.assertEqual(first['cases'], 10)
            self.assertEqual(first['model_kind'], 'fixture')
            self.assertIsNone(first['semantic_support_rate'])
            case = out / 'dev-basic' / 'result.json'
            before = case.stat().st_mtime_ns
            second = await run_suite(out, split='dev', model_kind='fixture', resume=True)
            self.assertEqual(second['cases'], 10)
            self.assertEqual(case.stat().st_mtime_ns, before)
            with self.assertRaises(ValueError):
                await run_suite(out, split='test', model_kind='fixture', resume=True)
            self.assertTrue((out / 'dev-basic' / 'trace.jsonl').is_file())
            self.assertTrue((out / 'dev-basic' / 'annotation-template.json').is_file())
            input_path = out / 'dev-basic' / 'input.json'
            input_path.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'input integrity'):
                await run_suite(out, split='dev', model_kind='fixture', resume=True)

