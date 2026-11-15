"""Small frozen engineering scenarios; synthetic sources are never real papers."""
import json
from pathlib import Path
from pydantic import Field
from .models import Brief, Paper, StrictModel

DATA = Path(__file__).resolve().parents[2] / 'eval' / 'scientific'


class EvalCase(StrictModel):
    case_id: str = Field(pattern=r'^[a-z0-9-]+$')
    split: str = Field(pattern=r'^(dev|test)$')
    category: str
    source_kind: str = Field(pattern=r'^synthetic$')
    brief: Brief
    materials: list[str]
    required_questions: list[str] = Field(default_factory=lambda: ['direction', 'paper_value', 'first_experiment', 'limitations'])
    simulation: str = Field(default='normal', pattern=r'^(normal|bad_quote|foreign_reference|excluded_direction|timeout|english_analysis)$')


def load_cases(path=None):
    path = Path(path) if path else DATA / 'cases.json'
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('Evaluation case file exceeds 1 MiB')
    cases = [EvalCase.model_validate(row) for row in json.loads(path.read_text(encoding='utf-8-sig'))]
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError('Duplicate evaluation case IDs')
    return cases


def load_materials(case):
    corpus = json.loads((DATA / 'corpus.json').read_text(encoding='utf-8'))
    return [Paper.model_validate(corpus[name]) for name in case.materials]
