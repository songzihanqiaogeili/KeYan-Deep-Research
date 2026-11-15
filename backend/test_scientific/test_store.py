import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.store import Store
from scientific_research.demo import demo_input


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'research.sqlite')

    def tearDown(self):
        self.tmp.cleanup()

    def create(self):
        brief, papers = demo_input()
        return self.store.create_run(brief.model_dump(), [p.model_dump() for p in papers], mode='demo')

    def test_claim_is_atomic_and_events_ordered(self):
        run = self.create()
        self.assertEqual(self.store.claim_next()['id'], run['id'])
        self.assertIsNone(self.store.claim_next())
        self.store.event(run['id'], {'type': 'one'})
        self.store.event(run['id'], {'type': 'two'})
        events = self.store.events(run['id'], after=0)
        self.assertEqual([e['sequence'] for e in events], sorted(e['sequence'] for e in events))

    def test_interrupted_tasks_require_explicit_resume(self):
        run = self.create()
        self.store.claim_next()
        self.store.mark_interrupted()
        self.assertEqual(self.store.get_run(run['id'])['status'], 'interrupted')
        self.assertIsNone(self.store.claim_next())
        self.store.resume(run['id'])
        self.assertEqual(self.store.claim_next()['id'], run['id'])

    def test_startup_does_not_automatically_run_queued_paid_tasks(self):
        brief, papers = demo_input()
        run = self.store.create_run(brief.model_dump(), [p.model_dump() for p in papers], mode='model')
        self.store.mark_interrupted()
        self.assertEqual(self.store.get_run(run['id'])['status'], 'interrupted')
        self.assertIsNone(self.store.claim_next())

    def test_cache_round_trip_and_key_isolation(self):
        self.store.cache_put('one', {'claims': [{'text': 'x'}], 'issues': []})
        self.assertEqual(self.store.cache_get('one')['claims'][0]['text'], 'x')
        self.assertIsNone(self.store.cache_get('two'))

    def test_discovered_fulltext_replaces_same_seed_abstract(self):
        from scientific_research.models import Paper,Page
        brief,_=demo_input()
        abstract=Paper(paper_id='arxiv-same',title='Paper',arxiv_id='2601.12345',access_level='abstract',pages=[Page(number=1,text='Abstract')])
        full=abstract.model_copy(update={'access_level':'fulltext','pages':[Page(number=1,text='Full paper body')]})
        run=self.store.create_run(brief.model_dump(),[abstract.model_dump()],mode='model',auto_search=True)
        self.store.save_discovery(run['id'],{'papers':[full.model_dump()],'search_plan':{},'search_audit':[],'candidate_papers':[],'issues':[]})
        papers=self.store.get_run(run['id'],include_input=True)['input']['papers']
        self.assertEqual(len(papers),1)
        self.assertEqual(papers[0]['access_level'],'fulltext')

    def test_document_id_is_not_a_file_path(self):
        _, papers = demo_input()
        pid = self.store.put_document(papers[0].model_dump())
        self.assertEqual(self.store.get_document(pid)['title'], papers[0].title)
        self.assertIsNone(self.store.get_document('../../secret'))

    def test_cannot_resume_completed_or_cancelled_queued_task(self):
        run = self.create()
        self.store.cancel(run['id'])
        self.assertEqual(self.store.get_run(run['id'])['status'], 'cancelled')
        self.assertIsNone(self.store.claim_next())
        self.store.resume(run['id'])
        self.store.finish(run['id'], {'status': 'completed'}, status='completed')
        with self.assertRaises(ValueError):
            self.store.resume(run['id'])

    def test_pending_plan_survives_failure_and_resume(self):
        run=self.create(); ident=run['id']
        original=self.store.get_run(ident,include_input=True)['input']['brief']
        plan={'queries':['spatial learning'],'selection_criteria':[],'year_from':2026,'year_to':2026}
        self.store.save_search_plan(ident,plan)
        self.store.finish(ident,None,status='failed')
        self.store.resume(ident)
        payload=self.store.get_run(ident,include_input=True)['input']
        self.assertEqual(payload['pending_search_plan'],plan)
        self.assertEqual(payload['brief'],original)
