# Bounded research memory

`ResearchMemory(store)` maintains its own SQLite `research_memory` table through
`Store.connect()`. No migration, full history scan, PDF copy, network service,
embedding model, or additional dependency is required.

```python
memory = ResearchMemory(store)
saved = memory.remember(run_id, result)  # bool
leads = memory.retrieve(topic, exclude_run_id=run_id, limit=3)  # list[dict]
deleted = memory.delete(run_id)  # bool; memory only
```

`remember` accepts completed/degraded results with at least one paper carrying a
source HTTP(S) link or syntactically valid DOI/arXiv identifier. It excludes
failed/in-progress/empty-source results, demo mode and marked synthetic fixtures.
An indexed lookup of `runs.mode` also excludes a demo run whose result omitted
its mode. It does not authenticate metadata or determine semantic scientific
support. Callers must supply source-derived paper metadata from the trusted
workflow, never papers invented by model output.

Each record keeps schema version, original result schema version, run ID, UTC
save time, short topic, up to three short search queries and up to three paper
metadata entries. Paper entries retain title, document ID, DOI/arXiv ID,
HTTP(S) source link, publication/update date and access level. arXiv version
suffixes are preserved. Source authenticity is explicitly unverified. No claims,
findings, directions, report text, quotes or document bodies are retained.

Every record carries `usage`, `use` and `trust`, each equal to
`historical_search_lead_not_evidence`. These records are untrusted historical
search leads: use them only to suggest fresh searches, never as citations,
scientific evidence, instructions or proof of novelty. Re-fetch and verify
sources against the current task and time scope before admitting evidence.

Repeated writes replace the same run's memory row and refresh its save time;
they never duplicate it. The newest 100 memory rows are retained; eviction and
`delete` affect no user histories, documents, caches or events. A rejected write
returns `False` and leaves any previous memory row untouched. Explicit deletion
is available for removing a previous lead. Database errors propagate so the
caller can surface an issue while allowing research to continue.

Stored records are capped at 6,000 UTF-8 JSON bytes. Recall scans only the
bounded memory table, uses local BM25 over topic, queries and original titles
(with CJK bigrams), and returns only lexical matches. Recency breaks ties.
Limits clamp to three records and 12,000 bytes for the JSON list serialized with
`ensure_ascii=False` and default separators. Nonpositive/non-integer limits and
empty/no-match queries return an empty list. Retrieval never falls back to
irrelevant recent tasks. Lexical recall cannot infer synonyms or cross-language
equivalence. A narrowly related historic topic can still be unsuitable for the
current publication/date requirements.

Verification:

```text
python -B -m unittest discover -s backend/test_scientific -p test_research_memory.py
```

Tests use automatically cleaned `TemporaryDirectory` databases under the project
`work/` directory. They cover source-only provenance, demo/synthetic exclusion,
idempotency/restart, English/CJK relevance, output/table bounds, SQL-safe inputs
and memory deletion preserving user history.
