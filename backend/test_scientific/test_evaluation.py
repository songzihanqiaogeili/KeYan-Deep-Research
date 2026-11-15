import asyncio
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.demo import DemoModel, demo_input
from scientific_research.workflow import ResearchWorkflow
from scientific_research.evaluation import evaluate_result, summarize
from scientific_research.evaldata import load_cases


class EvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_location_and_reference_checks_are_not_semantic_scores(self):
        brief, papers = demo_input()
        result = await ResearchWorkflow(DemoModel()).run(brief, papers)
        score = evaluate_result(result, papers, brief)
        self.assertEqual(score['quote_location']['rate'], 1)
        self.assertEqual(score['evidence_reference']['rate'], 1)
        self.assertIsNone(score['semantic_support']['rate'])
        self.assertEqual(score['semantic_support']['status'], 'needs_annotation')
        changed = copy.deepcopy(result)
        changed['claims'][0]['quote'] = 'This text never appeared in the source.'
        changed['findings'][0]['evidence_ids'] = ['missing']
        score = evaluate_result(changed, papers, brief)
        self.assertLess(score['quote_location']['rate'], 1)
        self.assertLess(score['evidence_reference']['rate'], 1)
        self.assertIn('evidence_integrity', score['diagnostic_signals'])

    async def test_abstention_cannot_be_reported_as_task_success(self):
        brief, papers = demo_input()
        brief = brief.model_copy(update={'excluded_topics': ['PM2.5']})
        result = await ResearchWorkflow(DemoModel()).run(brief, papers)
        result['directions'] = []
        score = evaluate_result(result, papers, brief)
        self.assertTrue(score['hard_constraints']['passed'])
        self.assertFalse(score['has_direction'])
        self.assertIsNone(score['task_success'])
        result['directions'] = [{'question': 'PM2.5 prediction', 'minimal_experiment': '', 'evidence_ids': []}]
        score = evaluate_result(result, papers, brief)
        self.assertFalse(score['hard_constraints']['passed'])

    async def test_annotations_must_cover_current_result_and_valid_ids(self):
        brief, papers = demo_input()
        result = await ResearchWorkflow(DemoModel()).run(brief, papers)
        with self.assertRaises(ValueError):
            evaluate_result(result, papers, brief, annotation={'result_hash': 'old', 'claim_checks': []})
        from scientific_research.evaluation import annotation_hash
        annotation = {'result_hash': annotation_hash(result)}
        result['limitations'].append('A new material limitation changes report quality.')
        with self.assertRaises(ValueError):
            evaluate_result(result, papers, brief, annotation=annotation)

    async def test_human_labels_have_explicit_denominators(self):
        from scientific_research.evaluation import annotation_hash
        brief, papers = demo_input()
        result = await ResearchWorkflow(DemoModel()).run(brief, papers)
        annotation = {'result_hash': annotation_hash(result), 'claim_checks': [
            {'evidence_id': result['claims'][0]['evidence_id'], 'supported': False}],
            'question_checks': {'question-a': True}, 'readability': 2, 'task_success': False}
        score = evaluate_result(result, papers, brief, annotation=annotation,
                                required_questions=['question-a', 'question-b'])
        self.assertEqual(score['semantic_support']['rate'], 0)
        self.assertEqual(score['semantic_support']['total'], 1)
        self.assertIsNone(score['question_coverage']['rate'])
        self.assertFalse(score['task_success'])

    def test_summary_does_not_turn_unscored_semantics_into_zero_or_one(self):
        summary = summarize([])
        self.assertIsNone(summary['semantic_support_rate'])
        self.assertEqual(summary['cases'], 0)

    def test_suite_has_frozen_separate_splits_and_explicit_synthetic_provenance(self):
        cases = load_cases()
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({c.case_id for c in cases}), 20)
        self.assertEqual({c.split for c in cases}, {'dev', 'test'})
        self.assertTrue(all(c.source_kind == 'synthetic' for c in cases))

