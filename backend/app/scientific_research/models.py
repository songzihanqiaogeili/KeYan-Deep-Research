"""Validated domain contracts; model output never creates trusted provenance."""
from typing import Literal, Annotated
from datetime import date
from pydantic import BaseModel, ConfigDict, Field, model_validator

Question = Annotated[str, Field(min_length=1, max_length=2000)]
Label = Annotated[str, Field(min_length=1, max_length=500)]
EvidenceID = Annotated[str, Field(min_length=1, max_length=100)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, frozen=True)


class VenueRule(StrictModel):
    venue: str = Field(min_length=1,max_length=1000)
    issns: list[str] = Field(default_factory=list,max_length=10)
    system: str = Field(min_length=1,max_length=100)
    version: str = Field(min_length=1,max_length=100)
    label: str = Field(min_length=1,max_length=100)
    source_url: str = Field(min_length=1,max_length=2000,pattern=r'^https?://')
    qualifies: bool = False


class Brief(StrictModel):
    as_of_date: str | None = Field(default=None,pattern=r'^\d{4}-\d{2}-\d{2}$')
    search_mode: Literal['topic','paper'] = 'topic'
    research_mode: Literal['focused','trend'] = 'focused'
    venue_catalog: list[VenueRule] = Field(default_factory=list,max_length=200)
    topic: str = Field(min_length=1, max_length=4000)
    questions: list[Question] = Field(default_factory=list, max_length=10)
    constraints: str = Field(default='', max_length=4000)
    excluded_topics: list[Label] = Field(default_factory=list,max_length=20)
    agent_loop: bool = False
    write_report: bool = False
    publication_policy: Literal['auto','any','prefer_journal','journal_only','verified_top_only'] = 'auto'
    year_from: int | None = Field(default=None,ge=1900,le=2100)
    year_to: int | None = Field(default=None,ge=1900,le=2100)
    target_papers: int = Field(default=2,ge=1,le=3)
    max_agent_steps: int = Field(default=10,ge=1,le=15)
    max_concurrency: int = Field(default=3, ge=1, le=3)
    max_papers: int = Field(default=10, ge=1, le=10)
    max_calls: int = Field(default=60, ge=1, le=60)
    max_directions: int = Field(default=3, ge=1, le=3)
    timeout_seconds: int = Field(default=900, ge=1, le=900)


    @model_validator(mode='after')
    def validate_year_bounds(self):
        if self.as_of_date and date.fromisoformat(self.as_of_date)>date.today():
            raise ValueError('as_of_date must not exceed today')
        if self.year_from is not None and self.year_to is not None and self.year_from>self.year_to:
            raise ValueError('year_from must not exceed year_to')
        return self


class Page(StrictModel):
    number: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=200000)


class Paper(StrictModel):
    paper_id: str = Field(min_length=1, max_length=100, pattern=r'^[\w.-]+$')
    title: str = Field(min_length=1, max_length=1000)
    doi: str | None = Field(default=None, max_length=300)
    arxiv_id: str | None = Field(default=None, max_length=100)
    source_url: str = Field(default='', max_length=2000)
    venue: str = Field(default='',max_length=1000)
    issns: list[str] = Field(default_factory=list,max_length=10)
    publication_type: Literal['journal','preprint','conference','unknown'] = 'unknown'
    authors: list[Label] = Field(default_factory=list, max_length=100)
    published_at: str | None = Field(default=None, max_length=40)
    updated_at: str | None = Field(default=None, max_length=40)
    access_level: Literal['abstract', 'fulltext'] = 'fulltext'
    pages: list[Page] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def validate_document(self):
        if len({p.number for p in self.pages}) != len(self.pages):
            raise ValueError('duplicate physical page number')
        if sum(len(p.text) for p in self.pages) > 200000:
            raise ValueError('document exceeds 200000 characters')
        return self


class ExtractedClaim(StrictModel):
    text: str = Field(min_length=1, max_length=3000)
    kind: Literal['author_claim', 'author_limitation', 'system_inference']
    quote: str = Field(min_length=1, max_length=4000)
    page: int = Field(ge=1)


class Finding(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[EvidenceID] = Field(min_length=1, max_length=100)


class Direction(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    search_query: str | None = Field(default=None, min_length=1, max_length=300)
    hypothesis: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[EvidenceID] = Field(min_length=1, max_length=100)
    minimal_experiment: str = Field(min_length=1, max_length=4000)
    baselines: list[Label] = Field(min_length=1, max_length=20)
    metrics: list[Label] = Field(min_length=1, max_length=20)
    risks: list[Label] = Field(min_length=1, max_length=20)
    falsification_criteria: str = Field(min_length=1, max_length=2000)
    compute_requirements: str = Field(min_length=1, max_length=2000)


class PaperNote(StrictModel):
    paper_id: str = Field(min_length=1,max_length=100)
    title_zh: str = Field(min_length=1,max_length=300)
    why_read: str = Field(min_length=1,max_length=1200)
    relevance: str = Field(min_length=1,max_length=1200)
    limitation: str = Field(min_length=1,max_length=1200)
    evidence_ids: list[EvidenceID] = Field(min_length=1,max_length=20)
