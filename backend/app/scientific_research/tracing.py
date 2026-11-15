"""Bounded, redacted model-call snapshots for inspection and explicit replay.

This records observable calls, not private chain-of-thought or proven root causes.
"""
import hashlib
import inspect
import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def redact(value):
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if re.search(r'api[_-]?key|authorization|password|secret|access[_-]?token', str(k), re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'(?i)Bearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [REDACTED]', value)
        return re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', value)
    return value


class TraceRecorder:
    def __init__(self, path, *, run_id, max_snapshot_bytes=128 * 1024, max_trace_bytes=8 * 1024 * 1024):
        if len(run_id) > 128 or max_trace_bytes < 2048 or max_snapshot_bytes < 1:
            raise ValueError('Trace requires a short run ID and at least 2 KiB for metadata')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError('Trace already exists; choose another run or resume completed cases')
        self.run_id = run_id
        self.max_snapshot_bytes, self.max_trace_bytes = max_snapshot_bytes, max_trace_bytes
        self.lock = threading.Lock()
        self.sequence, self.bytes_written, self.previous = 0, 0, ''
        self.truncated = False

    def record(self, kind, payload, *, parent_id=None):
        with self.lock:
            self.sequence += 1
            step_id = f'{self.run_id}:{self.sequence}'
            if self.truncated:
                return step_id
            safe = redact(payload)
            size = len(canonical(safe).encode('utf-8'))
            replayable = size <= self.max_snapshot_bytes
            if not replayable:
                metadata = {k: safe[k] for k in ('role', 'outcome', 'error_type', 'duration_ms', 'usage')
                            if k in safe and len(canonical(safe[k]).encode('utf-8')) < 2048}
                safe = {'omitted': 'snapshot_limit', 'bytes': size, 'sha256': digest(safe), **metadata}
            event = {'step_id': step_id, 'parent_id': parent_id, 'type': kind,
                     'time': datetime.now(timezone.utc).isoformat(), 'replayable': replayable,
                     'previous_hash': self.previous, **safe}
            event['event_hash'] = digest(event)
            line = canonical(event) + '\n'
            # Always reserve room for an explicit terminal marker. A valid prefix
            # must never silently masquerade as a complete replayable trace.
            if self.bytes_written + len(line.encode('utf-8')) + 768 > self.max_trace_bytes:
                event = {'step_id': step_id, 'type': 'trace_limit', 'replayable': False,
                         'previous_hash': self.previous}
                event['event_hash'] = digest(event)
                line = canonical(event) + '\n'
                self.truncated = True
            if self.bytes_written + len(line.encode('utf-8')) <= self.max_trace_bytes:
                with self.path.open('a', encoding='utf-8') as stream:
                    stream.write(line)
                self.bytes_written += len(line.encode('utf-8'))
                self.previous = event['event_hash']
            return step_id


class TracedModel:
    def __init__(self, model, trace):
        self.model, self.trace = model, trace
        self.fixture = bool(getattr(model, 'fixture', False))
        self.identity = getattr(model, 'identity', type(model).__qualname__)
        self.usage_records = []

    async def complete(self, role, system, context):
        parent = self.trace.record('model_start', {'role': role, 'system': system,
                                                  'context': context, 'model_identity': self.identity})
        start = time.monotonic()
        try:
            result = await self.model.complete(role, system, context)
        except BaseException as exc:
            usage_context = getattr(self.model, 'usage_context', None)
            usage = usage_context.get() if usage_context else None
            self.usage_records.append(dict(usage) if usage else None)
            self.trace.record('model_end', {'role': role, 'outcome': 'error', 'error_type': type(exc).__name__,
                                          'usage': usage,
                                          'duration_ms': round((time.monotonic() - start) * 1000, 2)}, parent_id=parent)
            raise
        usage_context = getattr(self.model, 'usage_context', None)
        usage = usage_context.get() if usage_context else None
        self.usage_records.append(dict(usage) if usage else None)
        self.trace.record('model_end', {'role': role, 'outcome': 'ok', 'output': result,
                                      'duration_ms': round((time.monotonic() - start) * 1000, 2),
                                      'usage': usage}, parent_id=parent)
        return result

    async def close(self):
        close = getattr(self.model, 'close', None)
        if close:
            result = close()
            if inspect.isawaitable(result):
                await result


def read_trace(path):
    events, previous = [], ''
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            value = json.loads(line)
            expected = value.pop('event_hash')
            if value.get('previous_hash') != previous or digest(value) != expected:
                raise ValueError('Trace integrity check failed')
            previous = expected
            events.append({**value, 'event_hash': expected})
    return events


def replay_inputs(path):
    events = read_trace(path)
    if any(not event.get('replayable') for event in events):
        raise ValueError('Trace contains omitted snapshots; exact replay is unavailable')
    return [{'step_id': e['step_id'], 'role': e['role'], 'system': e['system'], 'context': e['context']}
            for e in events if e['type'] == 'model_start']


def diagnose_trace(path):
    """Observable failure locations are diagnostic signals, not causal attribution."""
    events = read_trace(path)
    roles = {}
    for event in events:
        if event['type'] != 'model_end':
            continue
        stats = roles.setdefault(event.get('role', 'unknown'), {'calls': 0, 'errors': 0, 'summed_call_duration_ms': 0})
        stats['calls'] += 1
        stats['errors'] += event.get('outcome') == 'error'
        stats['summed_call_duration_ms'] += event.get('duration_ms', 0)
    return {'roles': roles, 'trace_truncated': any(not e.get('replayable') for e in events),
            'attribution': 'failure_locations_only; no controlled intervention performed',
            'duration_note': 'Summed model-call durations overlap under concurrency; not end-to-end latency.'}
