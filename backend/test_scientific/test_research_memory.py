import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.store import Store
from scientific_research.research_memory import ResearchMemory


def result(topic='graph retrieval'):
    return {'status': 'completed', 'schema_version': 1, 'brief': {'topic': topic},
            'papers': [{'paper_id': 'paper-1', 'title': topic + ' study',
                        'source_url': 'https://arxiv.org/abs/2601.12345v2',
                        'arxiv_id': '2601.12345v2', 'updated_at': '2026-02-01',
                        'pages': [{'text': 'PRIVATE FULL TEXT'}]}],
            'search_plan': {'queries': [topic]},
            'findings': [{'text': 'GENERATED UNSUPPORTED CLAIM'}]}


class ResearchMemoryTests(unittest.TestCase):
    def setUp(self):
        work = Path(os.environ.get('RESEARCH_TEST_WORK', str(Path(__file__).resolve().parents[2] / 'work')))
        work.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=work)
        self.store = Store(Path(self.tmp.name) / 'memory.sqlite')
        self.memory = ResearchMemory(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_provenance_without_claims_or_document_body(self):
        self.assertTrue(self.memory.remember('real', result()))
        record = self.memory.retrieve('graph')[0]
        self.assertEqual(record['use'], 'historical_search_lead_not_evidence')
        self.assertEqual(record['trust'], record['use'])
        self.assertEqual(record['papers'][0]['updated_at'], '2026-02-01')
        self.assertEqual(record['result_schema_version'], 1)
        self.assertNotIn('PRIVATE FULL TEXT', json.dumps(record))
        self.assertNotIn('GENERATED UNSUPPORTED CLAIM', json.dumps(record))

    def test_synthetic_demo_failed_and_zero_sources_are_excluded(self):
        for patch in [{'synthetic_fixture': True}, {'mode': 'demo'},
                      {'status': 'failed'}, {'status': 'running'}, {'papers': []},
                      {'papers': [{'paper_id': 'madeup', 'title': 'invented'}]}]:
            self.assertFalse(self.memory.remember('excluded', {**result(), **patch}))
        fake = result()
        fake['papers'][0]['paper_id'] = 'synthetic-a'
        self.assertFalse(self.memory.remember('fixture', fake))
        with self.store.connect() as db:
            db.execute('INSERT INTO runs(id,created_at,updated_at,status,mode,input_json) VALUES (?,?,?,?,?,?)',
                       ('demo-run', '', '', 'completed', 'demo', '{}'))
        self.assertFalse(self.memory.remember('demo-run', result()))
        self.assertEqual(self.memory.retrieve('graph'), [])

    def test_idempotency_restart_and_exclusion(self):
        self.memory.remember('one', result())
        self.memory.remember('one', result('quantum graph retrieval'))
        restarted = ResearchMemory(self.store)
        self.assertEqual(len(restarted.retrieve('graph')), 1)
        self.assertEqual(restarted.retrieve('graph', exclude_run_id='one'), [])

    def test_bounded_relevant_recall_and_cjk(self):
        self.memory.remember('irrelevant', result('ocean biology'))
        self.memory.remember('relevant', result('graph retrieval'))
        self.memory.remember('chinese', result('知识图谱检索'))
        self.assertEqual(self.memory.retrieve('graph retrieval')[0]['run_id'], 'relevant')
        self.assertEqual(self.memory.retrieve('图谱')[0]['run_id'], 'chinese')
        self.assertEqual(self.memory.retrieve('unrelated'), [])
        huge = result('graph ' + '长' * 10000)
        huge['papers'] = [copy.deepcopy(huge['papers'][0]) for _ in range(500)]
        huge['search_plan']['queries'] = ['graph ' + '长' * 10000] * 500
        for i in range(8):
            self.memory.remember(f'huge-{i}', huge)
        records = self.memory.retrieve('graph', limit=99999)
        self.assertLessEqual(len(records), 3)
        self.assertLessEqual(len(json.dumps(records, ensure_ascii=False).encode()),
                             self.memory.MAX_RETRIEVAL_BYTES)
        self.assertEqual(self.memory.retrieve('graph', limit=0), [])

    def test_parameterized_inputs_and_memory_delete_preserve_history(self):
        attack = "x'); DROP TABLE runs;--"
        with self.store.connect() as db:
            db.execute('INSERT INTO runs(id,created_at,updated_at,status,mode,input_json) VALUES (?,?,?,?,?,?)',
                       (attack, '', '', 'completed', 'model', '{}'))
        self.assertTrue(self.memory.remember(attack, result(attack)))
        self.assertEqual(self.memory.retrieve(attack)[0]['run_id'], attack)
        self.assertTrue(self.memory.delete(attack))
        self.assertFalse(self.memory.delete(attack))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0], 1)
        self.assertEqual(self.memory.retrieve(attack), [])

    def test_table_cap_does_not_touch_other_tables(self):
        for i in range(105):
            self.memory.remember(str(i), result())
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM research_memory').fetchone()[0], 100)
        self.assertEqual(self.memory.retrieve('graph', exclude_run_id='104', limit=1)[0]['run_id'], '103')


if __name__ == '__main__':
    unittest.main()

