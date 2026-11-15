import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))

from scientific_research.models import Brief, Paper, Page
from scientific_research.documents import deduplicate, load_pdf
from scientific_research.evidence import validate_extraction
from scientific_research.policy import context_for, require_tool
from scientific_research.skills import load_skill


def paper(pid='p1', **kwargs):
    return Paper(paper_id=pid, title='Memory research', pages=[Page(number=1, text='Shared memory improves retrieval. However, costs increase.')], **kwargs)


class ContractTests(unittest.TestCase):
    def test_budget_cannot_exceed_server_caps(self):
        for key, value in [('max_concurrency', 4), ('max_papers', 11), ('max_calls', 61), ('max_directions', 4)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                Brief(topic='memory', **{key: value})

    def test_question_size_is_bounded(self):
        with self.assertRaises(ValueError):
            Brief(topic='x', questions=['x' * 2001])

    def test_duplicate_page_and_blank_text_rejected(self):
        with self.assertRaises(ValueError):
            Paper(paper_id='x', title='x', pages=[Page(number=1, text='a'), Page(number=1, text='b')])
        with self.assertRaises(ValueError):
            Page(number=1, text='  ')

    def test_reader_context_is_deeply_read_only_and_scoped(self):
        ctx = context_for('reader', {'paper': paper().model_dump(), 'brief': {'topic': 'x'}, 'secret': 'key', 'papers': ['other']})
        self.assertNotIn('secret', ctx)
        self.assertNotIn('papers', ctx)
        with self.assertRaises(TypeError):
            ctx['paper']['pages'][0]['text'] = 'changed'

    def test_tool_and_skill_allowlists(self):
        require_tool('reader', 'read_paper')
        for role, tool in [('proposer', 'read_paper'), ('reader', 'execute_python'), ('unknown', 'read_paper')]:
            with self.assertRaises(PermissionError):
                require_tool(role, tool)
        self.assertIn('author', load_skill('reader').lower())
        with self.assertRaises(PermissionError):
            load_skill('../../secrets')

    def test_quote_and_physical_page_are_checked(self):
        extracted = {'claims': [{'text': 'Retrieval improves', 'kind': 'author_claim', 'quote': 'Shared memory improves retrieval.', 'page': 1}]}
        claims, issues = validate_extraction(paper(), extracted)
        self.assertEqual(len(claims), 1)
        self.assertEqual(issues, [])
        extracted['claims'][0]['page'] = 2
        claims, issues = validate_extraction(paper(), extracted)
        self.assertEqual(claims, [])
        self.assertIn('unlocated_quote', issues[0]['code'])

    def test_abstract_limitations_cannot_be_fulltext_claims(self):
        extracted = {'claims': [{'text': 'No ablation', 'kind': 'author_limitation', 'quote': 'Shared memory improves retrieval.', 'page': 1}]}
        claims, issues = validate_extraction(paper(access_level='abstract'), extracted)
        self.assertEqual(claims, [])
        self.assertEqual(issues[0]['code'], 'abstract_scope_violation')

    def test_arxiv_versions_are_one_work(self):
        items = deduplicate([paper('a', arxiv_id='2501.12345v1'), paper('b', arxiv_id='2501.12345v2')])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].paper_id, 'b')

    def test_doi_and_arxiv_aliases_are_deduplicated_together(self):
        items = deduplicate([paper('a', arxiv_id='2501.12345v1'),
                             paper('b', arxiv_id='2501.12345v2', doi='10.1234/memory'),
                             paper('c', doi='https://doi.org/10.1234/memory')])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].paper_id, 'b')

    def test_unknown_id_collision_rejected(self):
        with self.assertRaises(ValueError):
            deduplicate([paper(), Paper(paper_id='p1', title='different', pages=[Page(number=1, text='different')])])

    def test_pdf_loader_preserves_page_positions(self):
        from tempfile import TemporaryDirectory
        try:
            from pypdf import PdfWriter
        except ImportError:
            from PyPDF2 import PdfWriter
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'blank.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            with path.open('wb') as output:
                writer.write(output)
            with self.assertRaisesRegex(ValueError, 'OCR|extractable'):
                load_pdf(path)

    def test_real_text_pdf_keeps_physical_page_after_blank_page(self):
        from tempfile import TemporaryDirectory
        try:
            from pypdf import PdfWriter
            from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        except ImportError:
            from PyPDF2 import PdfWriter
            from PyPDF2.generic import DictionaryObject, NameObject, DecodedStreamObject
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'paper.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            writer.add_blank_page(width=300, height=300)
            page = writer.pages[1]
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            stream.set_data(b'BT /F1 12 Tf 10 200 Td (Memory improves retrieval.) Tj ET')
            page[NameObject('/Contents')] = stream
            with path.open('wb') as output:
                writer.write(output)
            paper = load_pdf(path)
            self.assertEqual(paper.pages[0].number, 2)
            self.assertIn('Memory improves retrieval.', paper.pages[0].text)


if __name__ == '__main__':
    unittest.main()
