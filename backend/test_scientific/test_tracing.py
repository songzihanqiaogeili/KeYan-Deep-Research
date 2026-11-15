import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.tracing import TraceRecorder, TracedModel, replay_inputs


class TraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_trace_redacts_credentials_and_saves_replayable_context(self):
        class Model:
            fixture = True
            async def complete(self, role, system, context):
                return {'answer': 'done'}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            trace = TraceRecorder(path, run_id='test')
            model = TracedModel(Model(), trace)
            result = await model.complete('reader', 'system', {'topic': 'test', 'api_key': 'secret-123'})
            self.assertEqual(result, {'answer': 'done'})
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('secret-123', text)
            inputs = replay_inputs(path)
            self.assertEqual(inputs[0]['context']['topic'], 'test')
            self.assertEqual(inputs[0]['context']['api_key'], '[REDACTED]')

    async def test_failed_model_call_is_recorded_without_claiming_root_cause(self):
        class Broken:
            async def complete(self, *args):
                raise TimeoutError('timeout')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            model = TracedModel(Broken(), TraceRecorder(path, run_id='test'))
            with self.assertRaises(TimeoutError):
                await model.complete('selector', 'system', {})
            events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(events[-1]['outcome'], 'error')
            self.assertEqual(events[-1]['error_type'], 'TimeoutError')

    def test_oversized_snapshot_is_marked_nonreplayable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            trace = TraceRecorder(path, run_id='test', max_snapshot_bytes=128)
            trace.record('model_start', {'context': {'text': 'x' * 500}})
            self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['replayable'])
            with self.assertRaises(ValueError):
                replay_inputs(path)

    async def test_failed_completion_keeps_already_consumed_usage(self):
        from contextvars import ContextVar
        class Truncated:
            usage_context = ContextVar('test_usage', default=None)
            async def complete(self, *args):
                self.usage_context.set({'total_tokens': 99})
                raise ValueError('model output truncated')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            model = TracedModel(Truncated(), TraceRecorder(path, run_id='test'))
            with self.assertRaises(ValueError):
                await model.complete('selector', 'system', {})
            events = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(events[-1]['usage']['total_tokens'], 99)

    def test_trace_limit_always_leaves_a_detectable_terminal_marker(self):
        from scientific_research.tracing import diagnose_trace, read_trace
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            trace = TraceRecorder(path, run_id='test', max_trace_bytes=2048)
            for _ in range(20):
                trace.record('model_start', {'role': 'reader', 'system': 'system', 'context': {'text': 'x' * 200}})
            self.assertLessEqual(path.stat().st_size, 2048)
            self.assertEqual(read_trace(path)[-1]['type'], 'trace_limit')
            self.assertTrue(diagnose_trace(path)['trace_truncated'])
            with self.assertRaises(ValueError):
                replay_inputs(path)

    async def test_omitted_output_still_has_diagnostics_and_independent_usage(self):
        from contextvars import ContextVar
        from scientific_research.tracing import diagnose_trace
        class Large:
            usage_context = ContextVar('large_test_usage', default=None)
            async def complete(self, *args):
                self.usage_context.set({'total_tokens': 100})
                return {'text': 'x' * 1000}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            model = TracedModel(Large(), TraceRecorder(path, run_id='test', max_snapshot_bytes=128))
            await model.complete('reader', 'system', {})
            self.assertEqual(model.usage_records[0]['total_tokens'], 100)
            diagnosis = diagnose_trace(path)
            self.assertTrue(diagnosis['trace_truncated'])
            self.assertEqual(diagnosis['roles']['reader']['calls'], 1)
