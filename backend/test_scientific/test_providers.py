import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.providers import ArxivProvider, parse_feed

FEED = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/2501.12345v2</id><title>Agent Memory</title>
<summary>A memory method evaluated on tasks.</summary><published>2025-01-21T00:00:00Z</published>
<updated>2025-02-01T00:00:00Z</updated><author><name>A. Researcher</name></author>
</entry></feed>'''


class ProviderTests(unittest.TestCase):
    def test_parse_preserves_provenance_and_abstract_scope(self):
        papers = parse_feed(FEED)
        self.assertEqual(papers[0].arxiv_id, '2501.12345v2')
        self.assertEqual(papers[0].access_level, 'abstract')
        self.assertEqual(papers[0].published_at, '2025-01-21T00:00:00Z')
        self.assertEqual(papers[0].authors, ['A. Researcher'])
        self.assertTrue(papers[0].source_url.startswith('https://arxiv.org/abs/'))

    def test_missing_abstract_excluded(self):
        self.assertEqual(parse_feed(FEED.replace('A memory method evaluated on tasks.', '')), [])

    def test_error_entry_and_unsafe_xml_rejected(self):
        with self.assertRaises(ValueError):
            parse_feed(FEED.replace('http://arxiv.org/abs/2501.12345v2', 'http://arxiv.org/api/errors#bad_query'))
        with self.assertRaises(ValueError):
            parse_feed('<!DOCTYPE x [<!ENTITY y "x">]><feed/>')


class ProviderAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_audits_query_and_caches_result(self):
        provider = ArxivProvider()
        provider._fetch = AsyncMock(return_value=FEED)
        first = await provider.search('agent memory', limit=3)
        second = await provider.search('agent memory', limit=3)
        self.assertEqual(first['papers'][0]['title'], 'Agent Memory')
        self.assertEqual(second['audit']['cache_hit'], True)
        self.assertEqual(provider._fetch.await_count, 1)
        self.assertIn('query', first['audit'])

    async def test_bad_bounds_rejected_before_network(self):
        provider = ArxivProvider()
        provider._fetch = AsyncMock()
        for query, limit in [('', 1), ('x', 31), ('x', 0)]:
            with self.assertRaises(ValueError):
                await provider.search(query, limit=limit)
        provider._fetch.assert_not_called()

    async def test_year_scope_is_encoded_and_latest_sort_used(self):
        provider=ArxivProvider()
        provider._fetch=AsyncMock(return_value=FEED)
        result=await provider.search('memory',year_from=2026,year_to=2026)
        self.assertIn('submittedDate:[202601010000 TO 202612312359]',provider._fetch.call_args.args[0])
        self.assertEqual(result['audit']['sort_by'],'submittedDate')

    async def test_fulltext_rejects_unverified_id_before_network(self):
        from scientific_research.models import Paper,Page
        provider=ArxivProvider()
        with self.assertRaises(ValueError):
            await provider.fulltext(Paper(paper_id='x',title='x',arxiv_id='../../etc/passwd',pages=[Page(number=1,text='x')]))
