"""Application-enforced role capabilities, independent of prompt instructions."""
from types import MappingProxyType
from collections.abc import Mapping

FIELDS = {
    'controller': frozenset({'brief','search_plan','candidates','observations','tools','remaining_steps','target_papers'}),
    'outliner': frozenset({'as_of_date','brief','findings','directions','paper_notes','evidence'}),
    'section_writer': frozenset({'as_of_date','brief','section','evidence','findings','directions','paper_notes','other_sections'}),
    'section_reviser': frozenset({'as_of_date','brief','section','evidence','findings','directions','paper_notes','other_sections','draft','feedback'}),
    'report_reviewer': frozenset({'as_of_date','brief','sections','evidence','limitations'}),
    'planner': frozenset({'brief','as_of_date'}),
    'selector': frozenset({'brief','search_plan','candidates','validation_error'}),
    'reader': frozenset({'brief', 'paper'}),
    'synthesizer': frozenset({'brief', 'paper_metadata', 'claims'}),
    'proposer': frozenset({'brief', 'paper_metadata', 'claims', 'findings', 'gaps', 'validation_feedback'}),
    'reviewer': frozenset({'brief', 'paper_metadata', 'claims', 'findings', 'gaps', 'directions'}),
}
for _seed_role in ('planner','selector','controller'):
    FIELDS[_seed_role]=FIELDS[_seed_role] | {'seed_papers'}
for _memory_role in ('planner','controller'):
    FIELDS[_memory_role]=FIELDS[_memory_role] | {'research_leads'}
FIELDS['paper_profiler']=frozenset({'brief','paper','evidence','validation_error'})
for _role in FIELDS:
    FIELDS[_role]=FIELDS[_role] | {'task_spec','trend_coverage'}

TOOLS = {
    'controller': frozenset({'search_papers','get_paper_metadata','fetch_fulltext','read_passages'}),
    'retriever': frozenset({'search_papers','fetch_fulltext'}),
    'reader': frozenset({'read_paper'}),
    'synthesizer': frozenset({'get_evidence'}),
    'proposer': frozenset({'get_evidence'}),
    'reviewer': frozenset({'get_evidence'}),
}


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(v) for v in value]
    return value


def context_for(role, state):
    if role not in FIELDS:
        raise PermissionError(f'Unknown role: {role}')
    return freeze({k: v for k, v in state.items() if k in FIELDS[role]})


def require_tool(role, name):
    if name not in TOOLS.get(role, ()):
        raise PermissionError(f'{role} cannot use {name}')
