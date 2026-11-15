"""Load only trusted, repository-owned skills; never paths from papers."""
from pathlib import Path

ROOT = Path(__file__).with_name('skills')
SKILLS = {'reader': 'paper-reading', 'synthesizer': 'method-comparison', 'proposer': 'research-proposal', 'reviewer': 'evidence-review'}
SKILLS['paper_profiler']='paper-profile'
SKILLS.update({'planner':'literature-planning','selector':'literature-screening'})
SKILLS.update({'controller':'research-controller','outliner':'report-outline','section_writer':'report-writing',
               'section_reviser':'report-writing','report_reviewer':'report-review'})


def load_skill(role: str) -> str:
    if role not in SKILLS:
        raise PermissionError(f'No skill allowed for {role}')
    return (ROOT / SKILLS[role] / 'SKILL.md').read_text(encoding='utf-8')
