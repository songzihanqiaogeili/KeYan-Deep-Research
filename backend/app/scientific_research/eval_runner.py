"""Frozen-material baseline CLI. No live model calls unless --model configured.

python -m scientific_research.eval_runner --output <directory> --split dev
"""
import argparse
import asyncio
import hashlib
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from .evaldata import DATA, load_cases, load_materials
from .evaluation import annotation_hash, evaluate_result, summarize
from .evalmodel import BaselineFixtureModel
from .export import markdown
from .tracing import TraceRecorder, TracedModel, digest, read_trace, replay_inputs, diagnose_trace
from .workflow import ResearchWorkflow


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.eval-', suffix='.tmp', delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def code_fingerprint():
    root = Path(__file__).parent
    paths = sorted([*root.glob('*.py'), *root.glob('skills/*/SKILL.md')])
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def annotation_template(result, questions):
    return {'result_hash': annotation_hash(result), 'annotator': '', 'claim_checks': [],
            'question_checks': {}, 'readability': None, 'actionability': None, 'task_success': None,
            'instructions': 'Only label inspected items. claim_checks assess extracted-claim entailment, not whole-report scientific value.',
            'unlabeled_evidence_ids': [c['evidence_id'] for c in result.get('claims', [])],
            'required_questions': list(questions),
            'rubric': {'readability': '0 unreadable; 1 confusing; 2 partly clear; 3 clear; 4 concise and coherent',
                       'actionability': '0 absent; 1 vague; 2 incomplete; 3 executable first test; 4 test plus baselines and falsification'}}


def usage_summary(records):
    measured = [u for u in records if u is not None and type(u.get('total_tokens')) is int and u['total_tokens'] >= 0]
    complete = len(measured) == len(records)
    observed = sum(u['total_tokens'] for u in measured)
    return {'calls': len(records), 'measured_calls': len(measured), 'complete': complete,
            'total_tokens': observed if complete else None,
            'observed_total_tokens': observed if measured or not records else None}


async def run_suite(output, *, split='dev', model_kind='fixture', resume=False, annotations=None):
    if split not in {'dev', 'test', 'all'} or model_kind not in {'fixture', 'configured'}:
        raise ValueError('Invalid split or model kind')
    cases = [case for case in load_cases() if split == 'all' or case.split == split]
    config_identity = 'scientific-eval-fixture-v1'
    model_settings = None
    if model_kind == 'configured':
        from .llm import OpenAIModel
        probe = OpenAIModel()
        config_identity = probe.identity
        model_settings = {'timeout_seconds': probe.timeout_seconds, 'ollama_qwen': probe.ollama_qwen}
        await probe.close()
    protocol = {'schema_version': 1, 'baseline': 'current-fixed-workflow', 'model_kind': model_kind,
                'model_identity': config_identity, 'split': split, 'code_hash': code_fingerprint(),
                'model_settings': model_settings,
                'cases_hash': digest([c.model_dump() for c in cases]),
                'corpus_hash': hashlib.sha256((DATA / 'corpus.json').read_bytes()).hexdigest(),
                'source_kind': 'synthetic', 'simulation_enabled': model_kind == 'fixture',
                'note': 'Engineering scenarios only. No automatic scientific-quality or causal-attribution claims.'}
    output = Path(output)
    manifest = output / 'manifest.json'
    if output.is_symlink():
        raise ValueError('Output cannot be a symbolic link')
    if manifest.exists():
        if not resume or json.loads(manifest.read_text(encoding='utf-8')) != protocol:
            raise ValueError('Existing run has different protocol or --resume was not provided; choose a new output')
    elif output.exists() and any(output.iterdir()):
        raise ValueError('Refusing to mix evaluation results with an unrelated directory')
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(manifest, protocol)
    scores, durations, usage_rows = [], [], []
    for case in cases:
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file()) > 64 * 1024 * 1024:
            raise ValueError('Run exceeds 64 MiB; inspect existing results before continuing')
        directory = output / case.case_id
        directory.mkdir(exist_ok=True)
        result_path, complete = directory / 'result.json', directory / 'complete.json'
        materials = load_materials(case)
        if resume and complete.is_file():
            stamp = json.loads(complete.read_text(encoding='utf-8'))
            result = json.loads(result_path.read_text(encoding='utf-8'))
            if digest(result) != stamp['result_digest']:
                raise ValueError('Saved result integrity check failed')
            saved_input = json.loads((directory / 'input.json').read_text(encoding='utf-8'))
            if digest(saved_input) != stamp['input_digest']:
                raise ValueError('Saved input integrity check failed')
            trace_name = stamp.get('trace_file', 'trace.jsonl')
            if Path(trace_name).name != trace_name:
                raise ValueError('Invalid trace reference')
            read_trace(directory / trace_name)
            if hashlib.sha256((directory / trace_name).read_bytes()).hexdigest() != stamp['trace_digest']:
                raise ValueError('Saved trace is incomplete or changed')
            duration_ms, usage = stamp['duration_ms'], stamp.get('usage')
        else:
            # Partial attempts are retained under the same case; do not delete a trace implicitly.
            attempts = [p for p in directory.glob('trace*.jsonl') if p.is_file()]
            if len(attempts) >= 3:
                raise ValueError('Three partial attempts already exist; inspect them before creating another run')
            trace_path = directory / ('trace.jsonl' if not attempts else f'trace-attempt-{len(attempts)+1}.jsonl')
            trace = TraceRecorder(trace_path, run_id=case.case_id, max_trace_bytes=1024 * 1024)
            trace.record('run_start', {'case_id': case.case_id, 'input_hash': digest(case.model_dump()),
                                       'source_kind': case.source_kind, 'max_calls': case.brief.max_calls})
            if model_kind == 'fixture':
                model = BaselineFixtureModel(case.simulation)
            else:
                from .llm import OpenAIModel
                model = OpenAIModel()
            wrapped = TracedModel(model, trace)
            atomic_json(directory / 'input.json', {'case': case.model_dump(),
                                                  'papers': [p.model_dump() for p in materials]})
            start = time.monotonic()
            try:
                result = await ResearchWorkflow(wrapped).run(case.brief, materials,
                    on_event=lambda event: trace.record('workflow_event', {'event': event}))
            finally:
                await wrapped.close()
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            trace.record('run_end', {'status': result['status'], 'duration_ms': duration_ms})
            result['evaluation'] = {'case_id': case.case_id, 'source_kind': case.source_kind,
                                    'model_kind': model_kind, 'simulation': case.simulation if model_kind == 'fixture' else None}
            # A real model on fake source text is still synthetic research material.
            result['synthetic_fixture'] = True
            result['limitations'].append('Synthetic evaluation materials; never cite these as real academic papers.')
            read_trace(trace_path)
            # Cost accounting is independent of bounded/redacted trace snapshots.
            usage = usage_summary(wrapped.usage_records)
            atomic_json(result_path, result)
            (directory / 'report.md').write_text(markdown(result), encoding='utf-8')
            atomic_json(directory / 'annotation-template.json', annotation_template(result, case.required_questions))
            atomic_json(complete, {'result_digest': digest(result), 'duration_ms': duration_ms,
                                  'input_digest': digest(json.loads((directory / 'input.json').read_text(encoding='utf-8'))),
                                  'usage': usage, 'trace_file': trace_path.name,
                                  'trace_digest': hashlib.sha256(trace_path.read_bytes()).hexdigest()})
        annotation_path = Path(annotations) / f'{case.case_id}.json' if annotations else None
        annotation = json.loads(annotation_path.read_text(encoding='utf-8')) if annotation_path and annotation_path.is_file() else None
        score = evaluate_result(result, materials, case.brief, annotation=annotation,
                                required_questions=case.required_questions)
        score.update(case_id=case.case_id, split=case.split, category=case.category, duration_ms=duration_ms)
        atomic_json(directory / 'score.json', score)
        trace_name = json.loads(complete.read_text(encoding='utf-8'))['trace_file']
        atomic_json(directory / 'diagnostics.json', diagnose_trace(directory / trace_name))
        scores.append(score)
        durations.append(duration_ms)
        usage_rows.append(usage)
        summary = {**summarize(scores), 'model_kind': model_kind, 'source_kind': 'synthetic',
                   'split': split, 'baseline': protocol['baseline'], 'scores': scores,
                   'duration_ms_median': statistics.median(durations),
                   'duration_ms_range': [min(durations), max(durations)],
                   'measured_usage_cases': sum(bool(u and u['measured_calls']) for u in usage_rows),
                   'usage_complete': all(u and u['complete'] for u in usage_rows),
                   'total_tokens': sum(u['total_tokens'] for u in usage_rows) if all(u and u['complete'] for u in usage_rows) else None,
                   'observed_total_tokens': sum(u['observed_total_tokens'] or 0 for u in usage_rows if u)
                                           if any(u and u['observed_total_tokens'] is not None for u in usage_rows) else None,
                   'causal_attribution': 'not_established; use controlled stage-replacement experiments'}
        atomic_json(output / 'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--split', choices=['dev', 'test', 'all'], default='dev')
    parser.add_argument('--model', choices=['fixture', 'configured'], default='fixture')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--inspect-trace', type=Path, help='Read redacted call inputs only; never calls a model')
    parser.add_argument('--diagnose-trace', type=Path, help='Summarize failure locations, never claim causal attribution')
    args = parser.parse_args()
    try:
        if args.diagnose_trace:
            print(json.dumps(diagnose_trace(args.diagnose_trace), ensure_ascii=False, indent=2))
        elif args.inspect_trace:
            print(json.dumps(replay_inputs(args.inspect_trace), ensure_ascii=False, indent=2))
        elif args.dry_run:
            cases = [c for c in load_cases() if args.split == 'all' or c.split == args.split]
            print(json.dumps({'cases': [c.case_id for c in cases], 'source_kind': 'synthetic',
                              'model_calls': 0, 'configured_mode_would_call_model': args.model == 'configured'}))
        else:
            if not args.output:
                parser.error('--output is required')
            summary = asyncio.run(run_suite(args.output, split=args.split, model_kind=args.model,
                                            resume=args.resume, annotations=args.annotations))
            print(json.dumps({k: v for k, v in summary.items() if k != 'scores'}, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Evaluation error: {exc}\n')


if __name__ == '__main__':
    main()
