"""Bounded, local search leads. Historical metadata is never scientific evidence."""
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit


TRUST = 'historical_search_lead_not_evidence'


def _text(value, limit):
    if not isinstance(value, str):
        return ''
    return ' '.join(value[:limit * 2].split())[:limit]


def _items(value, limit):
    return value[:limit] if isinstance(value, list) else []


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _tokens(value):
    value = _text(value, 8000).lower()
    words = re.findall(r'[a-z0-9]+', value)
    for segment in re.findall(r'[\u3400-\u9fff]+', value):
        words.extend(segment[i:i + 2] for i in range(max(1, len(segment) - 1)))
    return words


def _size(value):
    return len(json.dumps(value, ensure_ascii=False).encode('utf-8'))


def _url(value):
    value = _text(value, 600)
    try:
        parts = urlsplit(value)
        if parts.scheme in ('http', 'https') and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return ''


class ResearchMemory:
    """Owns only research_memory; never reads bodies or scans runs/documents."""
    MAX_RECORDS = 100
    MAX_RECORD_BYTES = 6000
    MAX_RETRIEVAL_BYTES = 12000
    MAX_RESULTS = 3

    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS research_memory (
                run_id TEXT PRIMARY KEY, saved_at TEXT NOT NULL,
                record_json TEXT NOT NULL)''')

    def remember(self, run_id, result):
        """Upsert a finished real run's metadata; False means no usable lead."""
        if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 512:
            return False
        result = _mapping(result)
        if (result.get('status') not in ('completed', 'degraded')
                or result.get('synthetic_fixture') or result.get('synthetic')
                or result.get('mode') == 'demo'):
            return False
        # Indexed single-row lookup guards demo mode even if absent from result.
        with self.store.connect() as db:
            run = db.execute('SELECT mode FROM runs WHERE id=?', (run_id,)).fetchone()
        if run and run['mode'] == 'demo':
            return False
        papers, seen = [], set()
        for candidate in _items(result.get('papers'), 30):
            paper = _mapping(candidate)
            ident = _text(paper.get('paper_id'), 100)
            title = _text(paper.get('title'), 240)
            if (not ident or not title or paper.get('synthetic_fixture') or paper.get('synthetic')
                    or ident.lower().startswith(('synthetic-', 'demo-'))
                    or 'not a real paper' in title.lower()):
                continue
            doi = _text(paper.get('doi'), 200)
            arxiv = _text(paper.get('arxiv_id'), 100)
            doi = doi if re.fullmatch(r'10\.\d{4,9}/[^\s<>]+', doi) else ''
            arxiv = arxiv if re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z-]+/\d{7})(?:v\d+)?', arxiv) else ''
            source = _url(paper.get('source_url'))
            if not source:
                source = 'https://doi.org/' + doi if doi else 'https://arxiv.org/abs/' + arxiv if arxiv else ''
            if not source or ident in seen:
                continue
            seen.add(ident)
            papers.append({'paper_id': ident, 'title': title, 'source_url': source,
                           'doi': doi, 'arxiv_id': arxiv,
                           'published_at': _text(paper.get('published_at'), 40),
                           'updated_at': _text(paper.get('updated_at'), 40),
                           'access_level': _text(paper.get('access_level'), 20)})
            if len(papers) == 3:
                break
        if not papers:
            return False
        queries = []
        raw_queries = _items(_mapping(result.get('search_plan')).get('queries'), 6)
        raw_queries += _items(result.get('search_queries'), 6)
        for query in raw_queries:
            clean = _text(query, 160)
            if clean and clean not in queries:
                queries.append(clean)
            if len(queries) == 3:
                break
        record = {'schema_version': 1, 'run_id': run_id,
                  'result_schema_version': _text(str(result.get('schema_version', 'unknown')), 30),
                  'saved_at': datetime.now(timezone.utc).isoformat(),
                  'topic': _text(_mapping(result.get('brief')).get('topic'), 240),
                  'search_queries': queries, 'papers': papers,
                  'usage': TRUST, 'use': TRUST, 'trust': TRUST,
                  'provenance': 'finished_run_source_metadata; authenticity_not_independently_verified'}
        # Preserve the established integer result schema contract when possible.
        if type(result.get('schema_version')) is int and 0 <= result['schema_version'] <= 10000:
            record['result_schema_version'] = result['schema_version']
        while _size(record) > self.MAX_RECORD_BYTES and len(papers) > 1:
            papers.pop()
        while _size(record) > self.MAX_RECORD_BYTES and queries:
            queries.pop()
        if _size(record) > self.MAX_RECORD_BYTES:
            return False
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''INSERT INTO research_memory(run_id,saved_at,record_json) VALUES (?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET saved_at=excluded.saved_at,record_json=excluded.record_json''',
                       (run_id, record['saved_at'], json.dumps(record, ensure_ascii=False)))
            db.execute('''DELETE FROM research_memory WHERE run_id NOT IN
                (SELECT run_id FROM research_memory ORDER BY saved_at DESC, rowid DESC LIMIT ?)''',
                       (self.MAX_RECORDS,))
        return True

    def retrieve(self, topic, exclude_run_id='', limit=3):
        """Rank a bounded metadata table using BM25; no match returns []."""
        if type(limit) is not int or limit <= 0:
            return []
        query = set(_tokens(_text(topic, 1000)))
        if not query:
            return []
        with self.store.connect() as db:
            rows = db.execute('''SELECT record_json FROM research_memory WHERE run_id != ?
                ORDER BY saved_at DESC, rowid DESC LIMIT ?''', (exclude_run_id, self.MAX_RECORDS)).fetchall()
        records, counters = [], []
        for row in rows:
            try:
                if len(row[0].encode('utf-8')) > self.MAX_RECORD_BYTES:
                    continue
                record = json.loads(row[0])
                text = ' '.join([record['topic'], *record['search_queries'],
                                 *(p['title'] for p in record['papers'])])
                counts = Counter(_tokens(text))
                if record.get('trust') != TRUST or not counts:
                    continue
            except (TypeError, ValueError, KeyError):
                continue
            records.append(record)
            counters.append(counts)
        if not counters:
            return []
        mean_length = sum(sum(c.values()) for c in counters) / len(counters)
        frequencies = {word: sum(word in c for c in counters) for word in query}
        ranked = []
        for i, counts in enumerate(counters):
            score = 0.0
            length = sum(counts.values())
            for word in query & counts.keys():
                df = frequencies[word]
                idf = math.log(1 + (len(counters) - df + 0.5) / (df + 0.5))
                tf = counts[word]
                score += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / mean_length))
            if score > 0:
                ranked.append((score, i))
        selected = []
        for _, i in sorted(ranked, key=lambda pair: (-pair[0], pair[1])):
            candidate = records[i]
            if _size(selected + [candidate]) <= self.MAX_RETRIEVAL_BYTES:
                selected.append(candidate)
            if len(selected) >= min(limit, self.MAX_RESULTS):
                break
        return selected

    def delete(self, run_id):
        """Remove only this memory record, preserving runs, documents and cache."""
        with self.store.connect() as db:
            return db.execute('DELETE FROM research_memory WHERE run_id=?', (run_id,)).rowcount > 0
