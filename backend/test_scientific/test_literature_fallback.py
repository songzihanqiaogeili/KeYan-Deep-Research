import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.literature import LiteratureProvider,parse_openalex


class LiteratureTests(unittest.TestCase):
    def test_openalex_abstract_is_reconstructed_with_venue(self):
        result=parse_openalex({'results':[{'id':'https://openalex.org/W123','title':'Spatial learning',
            'publication_date':'2026-01-03','doi':'https://doi.org/10.1234/test',
            'abstract_inverted_index':{'We':[0],'study':[1],'space':[2]},
            'primary_location':{'source':{'display_name':'Example Journal'}},'authorships':[]}]})
        self.assertEqual(result[0].pages[0].text,'We study space')
        self.assertEqual(result[0].venue,'Example Journal')
        self.assertEqual(result[0].access_level,'abstract')

    def test_missing_abstract_is_not_mislabeled_as_fulltext(self):
        self.assertEqual(parse_openalex({'results':[{'id':'https://openalex.org/W123','title':'No abstract'}]}),[])


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_primary_failure_switches_source_and_opens_short_circuit(self):
        provider=LiteratureProvider()
        provider.primary.search=AsyncMock(side_effect=ConnectionError('source disconnected'))
        provider.secondary.search=AsyncMock(return_value={'papers':[{'paper_id':'known'}],'audit':{'provider':'openalex'}})
        result=await provider.search('spatiotemporal',year_from=2026,year_to=2026)
        await provider.search('spatial learning')
        self.assertEqual(result['audit']['provider'],'openalex')
        self.assertEqual(result['audit']['fallback_from'],'arxiv')
        self.assertEqual(provider.primary.search.await_count,1)
        self.assertEqual(provider.secondary.search.call_args_list[0].kwargs['year_from'],2026)

    async def test_all_sources_fail_explicitly(self):
        provider=LiteratureProvider()
        provider.primary.search=AsyncMock(side_effect=ConnectionError())
        provider.secondary.search=AsyncMock(side_effect=ConnectionError())
        with self.assertRaisesRegex(ValueError,'literature_sources_unavailable'):
            await provider.search('memory')
