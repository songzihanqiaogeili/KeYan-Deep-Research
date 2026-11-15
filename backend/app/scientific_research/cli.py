"""CLI entry: python -m scientific_research.cli --demo --output <directory>."""
import argparse
import asyncio
import json
from pathlib import Path
from .models import Brief, Paper
from .documents import load_pdf
from .workflow import ResearchWorkflow
from .export import markdown


async def execute(args):
    if args.demo:
        from .demo import DemoModel, demo_input
        brief, papers = demo_input()
        model = DemoModel()
    else:
        if args.input:
            if args.input.stat().st_size > 8 * 1024 * 1024:
                raise ValueError('Input JSON exceeds 8 MiB')
            payload = json.loads(args.input.read_text(encoding='utf-8'))
            brief = Brief.model_validate(payload['brief'])
            papers = [Paper.model_validate(p) for p in payload.get('papers', [])]
        else:
            if not args.topic:
                raise ValueError('--topic is required with --pdf')
            brief, papers = Brief(topic=args.topic), []
        papers.extend(load_pdf(path) for path in args.pdf)
        if not papers:
            raise ValueError('Provide at least one text paper or PDF')
        from .llm import OpenAIModel
        model = OpenAIModel()
    try:
        result = await ResearchWorkflow(model).run(brief, papers)
    finally:
        if hasattr(model, 'close'):
            await model.close()
    args.output.mkdir(parents=True, exist_ok=True)
    # UUID names avoid accidentally overwriting a previous research run.
    stem = args.output / result['run_id']
    stem.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    stem.with_suffix('.md').write_text(markdown(result), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'synthetic_fixture': result['synthetic_fixture'],
                      'json': str(stem.with_suffix('.json')), 'markdown': str(stem.with_suffix('.md'))}, ensure_ascii=False))
    return 0 if result['status'] == 'completed' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--demo', action='store_true', help='Synthetic offline fixture; no model or search API calls')
    group.add_argument('--input', type=Path, help='JSON with brief and paper page text')
    group.add_argument('--topic', help='Research topic when importing PDFs')
    parser.add_argument('--pdf', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.demo and args.pdf:
        parser.error('--demo cannot include real PDFs')
    try:
        raise SystemExit(asyncio.run(execute(args)))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'Error: {exc}\n')


if __name__ == '__main__':
    main()
