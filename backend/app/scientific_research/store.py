"""Local single-user persistent queue. All SQL parameters are bound values."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    status TEXT NOT NULL, mode TEXT NOT NULL, input_json TEXT NOT NULL,
                    result_json TEXT, calls INTEGER NOT NULL DEFAULT 0, resume_count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, paper_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS document_audits (id TEXT PRIMARY KEY, audit_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
                    time TEXT NOT NULL, event_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_run ON events(run_id, seq);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def put_document(self, paper: dict, *, audit=None) -> str:
        from .models import Paper
        paper = Paper.model_validate(paper).model_dump()
        ident = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO documents VALUES (?,?)', (ident, json.dumps(paper, ensure_ascii=False)))
            if audit:
                db.execute('INSERT INTO document_audits VALUES (?,?)', (ident, json.dumps(audit, ensure_ascii=False)))
        return ident

    def document_audit(self, ident):
        with self.connect() as db:
            row = db.execute('SELECT audit_json FROM document_audits WHERE id=?', (ident,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_document(self, ident):
        with self.connect() as db:
            row = db.execute('SELECT paper_json FROM documents WHERE id=?', (ident,)).fetchone()
        return json.loads(row[0]) if row else None

    def create_run(self, brief, papers, *, mode, novelty=False, audit=None, auto_search=False):
        from .models import Brief
        from .requirements import build_spec
        spec=build_spec(Brief.model_validate(brief)).model_dump()
        brief={**brief,'as_of_date':spec['as_of_date']}
        ident, stamp = uuid.uuid4().hex, now()
        payload = json.dumps({'brief': brief, 'task_spec':spec, 'papers': papers, 'seed_papers':papers, 'novelty': novelty, 'search_audit': audit or [],'auto_search':auto_search}, ensure_ascii=False)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0] >= 20:
                raise ValueError('Local queue is full (20 tasks)')
            db.execute('INSERT INTO runs(id,created_at,updated_at,status,mode,input_json) VALUES (?,?,?,?,?,?)',
                       (ident, stamp, stamp, 'queued', mode, payload))
        self.event(ident, {'type': 'queued'})
        return self.get_run(ident)

    def _row(self, row, include_input=False):
        if not row:
            return None
        value = dict(row)
        payload = json.loads(value.pop('input_json'))
        value['brief'] = payload['brief']
        value['task_spec']=payload.get('task_spec')
        value['result'] = json.loads(value.pop('result_json')) if value['result_json'] else None
        value.pop('result_json', None)
        if include_input:
            value['input'] = payload
        return value

    def get_run(self, ident, *, include_input=False):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (ident,)).fetchone()
        return self._row(row, include_input)

    def list_runs(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT 100').fetchall()
        return [{k: v for k, v in self._row(row).items() if k != 'result'} for row in rows]

    def claim_next(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id FROM runs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE runs SET status='running', updated_at=? WHERE id=?", (now(), row[0]))
        return self.get_run(row[0], include_input=True)

    def finish(self, ident, result, *, status):
        with self.connect() as db:
            db.execute('UPDATE runs SET status=?,result_json=?,updated_at=? WHERE id=?',
                       (status, json.dumps(result, ensure_ascii=False) if result else None, now(), ident))
        self.event(ident, {'type': status})

    def mark_interrupted(self):
        with self.connect() as db:
            db.execute("UPDATE runs SET status='interrupted',updated_at=? WHERE status='running' OR (status='queued' AND mode='model')", (now(),))

    def resume(self, ident):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running')").fetchone()[0] >= 20:
                raise ValueError('Local queue is full (20 tasks)')
            changed = db.execute("UPDATE runs SET status='queued', resume_count=resume_count+1,updated_at=? WHERE id=? AND status IN ('interrupted','cancelled','degraded','failed')", (now(), ident)).rowcount
        if not changed:
            raise ValueError('Only interrupted, cancelled, degraded or failed tasks can resume')
        self.event(ident, {'type': 'resumed'})

    def cancel(self, ident):
        with self.connect() as db:
            db.execute("UPDATE runs SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','running')", (now(), ident))
        self.event(ident, {'type': 'cancelled'})

    def increment_calls(self, ident):
        with self.connect() as db:
            db.execute('UPDATE runs SET calls=calls+1 WHERE id=?', (ident,))

    def patch_input(self, ident, changes):
        if not set(changes).issubset({'brief','agent_progress','trend_progress','analysis_snapshot','report_progress','pipeline_progress','memory_snapshot'}):
            raise ValueError('Unsupported progress field')
        if len(json.dumps(changes,ensure_ascii=False))>8*1024*1024:
            raise ValueError('Progress checkpoint exceeds 8 MiB')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT input_json FROM runs WHERE id=?',(ident,)).fetchone()
            if not row: raise ValueError('Run not found')
            payload=json.loads(row[0]);payload.update(changes)
            db.execute('UPDATE runs SET input_json=?,updated_at=? WHERE id=?',
                (json.dumps(payload,ensure_ascii=False),now(),ident))

    def save_search_plan(self, ident, plan):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT input_json FROM runs WHERE id=?',(ident,)).fetchone()
            if not row:
                raise ValueError('Run not found')
            payload=json.loads(row[0])
            payload['pending_search_plan']=plan
            db.execute('UPDATE runs SET input_json=?,updated_at=? WHERE id=?',
                       (json.dumps(payload,ensure_ascii=False),now(),ident))

    def save_discovery(self, ident, discovery):
        from .models import Paper
        from .documents import merge_materials
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT input_json FROM runs WHERE id=?',(ident,)).fetchone()
            if not row:
                raise ValueError('Run not found')
            payload=json.loads(row[0])
            inputs=discovery['papers'] if discovery.get('replace_materials') else payload['papers']+discovery['papers']
            material=merge_materials([Paper.model_validate(p) for p in inputs])
            payload['papers']=[p.model_dump() for p in material]
            payload['search_audit']=payload.get('search_audit',[])+discovery['search_audit']
            payload.update({'search_plan':discovery['search_plan'],'discovery_issues':discovery['issues'],
                              'candidate_papers':discovery['candidate_papers'],'seed_documents':discovery.get('seed_documents',[]),
                              'seed_ranking':discovery.get('seed_ranking',{}),
                              'loop_metrics':discovery.get('loop_metrics',{}),
                              'discovery_complete':not any(i['code']=='research_stopped_partial' for i in discovery['issues'])})
            db.execute('UPDATE runs SET input_json=?,updated_at=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),now(),ident))

    def event(self, ident, value):
        with self.connect() as db:
            db.execute('INSERT INTO events(run_id,time,event_json) VALUES (?,?,?)', (ident, now(), json.dumps(value, ensure_ascii=False)))

    def events(self, ident, *, after=0):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 200', (ident, after)).fetchall()
        return [{**json.loads(row['event_json']), 'sequence': row['seq'], 'time': row['time']} for row in rows]

    def usage_summary(self, ident):
        from .observability import usage_totals
        with self.connect() as db:
            rows=db.execute('SELECT event_json FROM events WHERE run_id=? ORDER BY seq',(ident,)).fetchall()
        return usage_totals(json.loads(row[0]) for row in rows)

    def cache_get(self, key):
        with self.connect() as db:
            row = db.execute('SELECT value_json FROM cache WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_put(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))
