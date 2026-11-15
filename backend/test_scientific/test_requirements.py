import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.models import Brief,Paper,Page
from scientific_research.requirements import build_spec,assess_paper,assess_delivery

def paper(**changes):
    return Paper(paper_id='p1',title='Spatial forecasting',pages=[Page(number=1,text='Spatial sensor prediction.')],published_at='2026-01-02',**changes)

class RequirementsTests(unittest.TestCase):
    def test_required_year_and_preferred_journal_are_distinct(self):
        spec=build_spec(Brief(topic='必须2026年的论文，优先顶刊'))
        self.assertEqual((spec.year_from,spec.year_to),(2026,2026))
        self.assertEqual(spec.publication_policy,'prefer_journal')
        decision=assess_paper(paper(publication_type='preprint'),spec)
        self.assertTrue(decision['eligible'])
        self.assertTrue(any(c['status']=='unverified' and c['strength']=='preferred' for c in decision['checks']))

    def test_explicit_form_overrides_automatic_publication_interpretation(self):
        spec=build_spec(Brief(topic='找两篇顶刊',publication_policy='any'))
        self.assertEqual(spec.publication_policy,'any')
        self.assertTrue(assess_paper(paper(),spec)['eligible'])

    def test_verified_top_is_unknown_even_for_journal_record(self):
        spec=build_spec(Brief(topic='必须2026年顶刊'))
        decision=assess_paper(paper(publication_type='journal'),spec)
        self.assertFalse(decision['eligible'])
        self.assertEqual(decision['status'],'unverified')
        self.assertIn('rank_unverified',decision['reason_codes'])

    def test_range_and_structured_bounds(self):
        spec=build_spec(Brief(topic='2024—2026年时空论文'))
        self.assertEqual((spec.year_from,spec.year_to),(2024,2026))
        explicit=build_spec(Brief(topic='2026年论文',year_from=2023,year_to=2025))
        self.assertEqual((explicit.year_from,explicit.year_to),(2023,2025))

    def test_missing_year_and_preprint_cannot_satisfy_hard_requirements(self):
        spec=build_spec(Brief(topic='2026年论文',publication_policy='journal_only'))
        missing=paper().model_copy(update={'published_at':None})
        self.assertFalse(assess_paper(missing,spec)['eligible'])
        self.assertFalse(assess_paper(paper(publication_type='preprint'),spec)['eligible'])
        self.assertTrue(assess_paper(paper(publication_type='journal'),spec)['eligible'])

    def test_exclusions_and_wrong_year_are_rejected(self):
        spec=build_spec(Brief(topic='2026年时空论文，不要PM2.5预测'))
        bad=paper().model_copy(update={'pages':[Page(number=1,text='We predict PM2.5.')],'published_at':'2025-01-01'})
        decision=assess_paper(bad,spec)
        self.assertFalse(decision['eligible'])
        self.assertEqual(decision['status'],'rejected')
        self.assertIn('excluded_topic',decision['reason_codes'])
        self.assertIn('year_out_of_range',decision['reason_codes'])

    def test_preferred_year_does_not_become_a_hard_filter(self):
        spec=build_spec(Brief(topic='最好是2026年的论文，优先期刊'))
        self.assertIsNone(spec.year_from)
        self.assertTrue(assess_paper(paper().model_copy(update={'published_at':'2025-02-01'}),spec)['eligible'])

    def test_metadata_eligibility_is_not_scientific_or_resource_verification(self):
        spec=build_spec(Brief(topic='2026年论文',constraints='单卡两个月',target_papers=1))
        delivery=assess_delivery(spec,[paper()],[paper()])
        self.assertEqual(delivery['requirement_status'],'met')
        self.assertEqual(delivery['resource_status'],'unverified')
        self.assertEqual(delivery['evidence_scope'],'fulltext')
        self.assertFalse(delivery['scientific_validity_verified'])

    def test_no_verified_top_matches_is_a_deliverable_outcome(self):
        spec=build_spec(Brief(topic='必须顶刊'))
        delivery=assess_delivery(spec,[],[paper(publication_type='journal')])
        self.assertEqual(delivery['requirement_status'],'unverified')
        self.assertEqual(delivery['recommendation_status'],'not_ready')
        self.assertEqual(delivery['qualified_count'],0)
        self.assertEqual(len(delivery['screening']),1)


class RequirementIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_imported_sources_cannot_bypass_required_top_verification(self):
        from scientific_research.demo import DemoModel
        from scientific_research.workflow import ResearchWorkflow
        class Counted(DemoModel):
            roles=[]
            async def complete(self,role,system,context):
                self.roles.append(role)
                return await super().complete(role,system,context)
        model=Counted()
        result=await ResearchWorkflow(model).run(Brief(topic='必须顶刊'),[paper(publication_type='journal')])
        self.assertEqual(model.roles,[])
        self.assertEqual(result['papers'],[])
        self.assertEqual(result['status'],'degraded')
        self.assertEqual(result['delivery']['requirement_status'],'unverified')

    async def test_unqualified_run_finishes_with_deterministic_explanation(self):
        import tempfile
        from unittest.mock import patch
        from scientific_research.demo import DemoModel
        from scientific_research.store import Store
        from scientific_research.runner import Runner
        class Counted(DemoModel):
            roles=[]
            async def complete(self,role,system,context):
                self.roles.append(role)
                return await super().complete(role,system,context)
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            brief=Brief(topic='必须2026年顶刊',write_report=True)
            ident=store.create_run(brief.model_dump(),[paper(publication_type='journal').model_dump()],mode='model')['id']
            with patch('scientific_research.llm.OpenAIModel',Counted):
                await Runner(store,None).execute(store.claim_next())
            saved=store.get_run(ident)
            self.assertEqual(saved['status'],'degraded')
            self.assertEqual(saved['calls'],0)
            self.assertEqual(Counted.roles,[])
            self.assertEqual(saved['result']['directions'],[])
            self.assertEqual(saved['result']['delivery']['requirement_status'],'unverified')
            self.assertEqual(saved['result']['report']['status'],'partial')

    async def test_research_does_not_read_sources_with_unverifiable_hard_rank(self):
        from scientific_research.agent_loop import research
        class Model:
            async def complete(self,role,system,context):
                if role=='planner': return {'queries':['spatial prediction'],'selection_criteria':[],'year_from':None,'year_to':None}
                if context['candidates'][0]['read']: return {'action':'finish_research','selected_ids':['P1'],'reason':'select'}
                return {'action':'read_passages','paper_id':'P1','reason':'read'}
        result=await research(Brief(topic='必须顶刊'),Model(),seeds=[paper(publication_type='journal')])
        self.assertEqual(result['papers'],[])
        self.assertEqual(result['task_spec']['publication_policy'],'verified_top_only')
        self.assertEqual(result['screening'][0]['status'],'unverified')

    async def test_preferred_year_is_not_silently_enforced_by_search_plan(self):
        from unittest.mock import AsyncMock
        from scientific_research.agent_loop import research
        actions=iter([{'action':'search_papers','query':'spatial prediction','reason':'search'},
                      {'action':'read_passages','paper_id':'P1','reason':'read'},
                      {'action':'finish_research','selected_ids':['P1'],'reason':'select'}])
        class Model:
            async def complete(self,role,system,context):
                if role=='planner': return {'queries':['spatial prediction'],'selection_criteria':[],'year_from':2026,'year_to':2026}
                return next(actions)
        source=paper().model_copy(update={'published_at':'2025-01-02'})
        provider=type('Provider',(),{})()
        provider.search=AsyncMock(return_value={'papers':[source.model_dump()],'audit':{'provider':'fixture'}})
        result=await research(Brief(topic='最好2026年的论文',target_papers=1),Model(),provider)
        self.assertEqual(len(result['papers']),1)
        self.assertIsNone(provider.search.call_args.kwargs['year_from'])
        self.assertIsNone(provider.search.call_args.kwargs['year_to'])

class PublicationMetadataTests(unittest.TestCase):
    def test_publication_types_come_from_index_metadata_not_venue_name(self):
        from scientific_research.literature import parse_openalex
        work={'id':'https://openalex.org/W123','title':'Study','abstract_inverted_index':{'Source':[0]},
              'type':'article','primary_location':{'source':{'type':'journal','display_name':'Example'}}}
        self.assertEqual(parse_openalex({'results':[work]})[0].publication_type,'journal')
        work['type']='preprint';work['primary_location']['source']['type']='repository'
        self.assertEqual(parse_openalex({'results':[work]})[0].publication_type,'preprint')
        work.pop('type');work['primary_location']['source'].pop('type')
        self.assertEqual(parse_openalex({'results':[work]})[0].publication_type,'unknown')

    def test_task_spec_is_saved_without_model_calls(self):
        import tempfile
        from scientific_research.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            run=store.create_run(Brief(topic='必须2026年，优先顶刊').model_dump(),[],mode='model')
            self.assertEqual(run['task_spec']['publication_policy'],'prefer_journal')
            self.assertEqual(run['calls'],0)


class RequirementInterpretationTests(unittest.TestCase):
    def test_hard_journal_constraint_survives_top_preference(self):
        spec=build_spec(Brief(topic='必须期刊记录，优先顶刊'))
        self.assertEqual(spec.publication_policy,'journal_only')
        self.assertTrue(spec.rank_requested)
        self.assertFalse(assess_paper(paper(publication_type='preprint'),spec)['eligible'])

    def test_negated_rank_requirement_and_invalid_range(self):
        self.assertEqual(build_spec(Brief(topic='研究时空方向，不需要顶刊')).publication_policy,'any')
        with self.assertRaisesRegex(ValueError,'年份'):
            build_spec(Brief(topic='2026—2024年时空论文'))


class MixedModalityTests(unittest.TestCase):
    def test_resource_requirement_does_not_promote_journal_preference(self):
        spec=build_spec(Brief(topic='必须单卡完成且优先顶刊'))
        self.assertEqual(spec.publication_policy,'prefer_journal')
        self.assertTrue(assess_paper(paper(publication_type='journal'),spec)['eligible'])

    def test_resource_requirement_does_not_make_preferred_year_hard(self):
        spec=build_spec(Brief(topic='必须单卡完成且最好2026年的论文'))
        self.assertIsNone(spec.year_from)
        self.assertIn(2026,spec.preferred_years)

class LegacyRequirementTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_search_respects_preference_and_structured_years(self):
        from unittest.mock import AsyncMock
        from scientific_research.discovery import discover
        class Model:
            async def complete(self,role,system,context):
                if role=='planner': return {'queries':['spatial learning'],'selection_criteria':[],'year_from':2026,'year_to':2026}
                return {'selected_ids':['P1']}
        provider=type('Provider',(),{})()
        source=paper().model_copy(update={'published_at':'2025-02-01'})
        provider.search=AsyncMock(return_value={'papers':[source.model_dump()],'audit':{'provider':'fixture'}})
        provider.fulltext=AsyncMock(return_value=source)
        result=await discover(Brief(topic='最好2026年的论文',agent_loop=False),Model(),provider)
        self.assertEqual(len(result['papers']),1)
        self.assertIsNone(provider.search.call_args.kwargs['year_from'])
        provider.search.reset_mock()
        result=await discover(Brief(topic='2026年论文',year_from=2024,year_to=2025,agent_loop=False),Model(),provider)
        self.assertEqual(len(result['papers']),1)
        self.assertEqual(provider.search.call_args.kwargs['year_from'],2024)

    async def test_legacy_unverified_hard_rank_does_not_invoke_selector(self):
        from unittest.mock import AsyncMock
        from scientific_research.discovery import discover
        class Model:
            roles=[]
            async def complete(self,role,system,context):
                self.roles.append(role)
                if role=='planner': return {'queries':['spatial learning'],'selection_criteria':[],'year_from':None,'year_to':None}
                raise AssertionError('Unverified sources must not enter selector')
        provider=type('Provider',(),{})()
        provider.search=AsyncMock(return_value={'papers':[paper(publication_type='journal').model_dump()],'audit':{'provider':'fixture'}})
        model=Model()
        result=await discover(Brief(topic='必须顶刊',agent_loop=False),model,provider)
        self.assertEqual(result['papers'],[])
        self.assertEqual(model.roles,['planner'])
        self.assertTrue(any(i['code']=='requirements_not_satisfied' for i in result['issues']))
