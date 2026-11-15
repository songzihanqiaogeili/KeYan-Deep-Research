"""Capture an existing report without rerunning it or changing research history."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .eval_runner import atomic_json, annotation_template
from .evaluation import evaluate_result
from .models import Brief, Paper
from .tracing import digest


def capture(database, output, *, run_id=None):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose an empty output directory')
    database = Path(database).resolve(strict=True)
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        if run_id:
            row = db.execute('SELECT * FROM runs WHERE id=? AND result_json IS NOT NULL', (run_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM runs WHERE mode='model' AND result_json IS NOT NULL ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            raise ValueError('No completed report snapshot found')
        result, payload = json.loads(row['result_json']), json.loads(row['input_json'])
    finally:
        db.close()
    brief = Brief.model_validate(payload['brief'])
    papers = [Paper.model_validate(p) for p in payload['papers']]
    questions = ['direction', 'paper_value', 'first_experiment', 'limitations']
    score = evaluate_result(result, papers, brief, required_questions=questions)
    protocol = {'kind': 'historical_snapshot', 'run_id': row['id'],
                'captured_at': datetime.now(timezone.utc).isoformat(),
                'source_kind': 'frozen_local_material_not_independently_verified',
                'result_digest': digest(result), 'model_calls_made_during_capture': 0,
                'trace_available': False,
                'limitation': 'Original model/prompt environment is not reconstructed. Not a controlled performance baseline.'}
    atomic_json(output / 'capture.json', protocol)
    atomic_json(output / 'input.json', {'brief': brief.model_dump(), 'papers': [p.model_dump() for p in papers]})
    atomic_json(output / 'result.json', result)
    atomic_json(output / 'score.json', score)
    atomic_json(output / 'annotation-template.json', annotation_template(result, questions))
    return protocol, score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-id')
    args = parser.parse_args()
    try:
        protocol, score = capture(args.database, args.output, run_id=args.run_id)
        print(json.dumps({'capture': protocol, 'score': score}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f'Capture error: {exc}\n')


if __name__ == '__main__':
    main()
