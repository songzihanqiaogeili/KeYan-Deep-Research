import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
class ReportDiagnosticsTests(unittest.TestCase):
 def test_duplicate_prose_is_flagged_without_quality_certification(self):
  from scientific_research.report_diagnostics import diagnose_report
  text='相同的研究判断。'*15
  result={'papers':[{'paper_id':'p','access_level':'abstract'}],'claims':[{'evidence_id':'e','paper_id':'p'}],
          'report':{'sections':[{'section_id':s,'paragraphs':[{'text':text,'evidence_ids':['e']}]} for s in ['decision','comparison']]}}
  d=diagnose_report(result)
  self.assertIn('repeated_cross_section_prose',{w['code'] for w in d['warnings']})
  self.assertFalse(d['semantic_quality_verified']);self.assertEqual(d['fulltext_papers'],0)
 def test_counts_actual_distinct_sources(self):
  from scientific_research.report_diagnostics import diagnose_report
  d=diagnose_report({'papers':[],'claims':[],'report':{'sections':[]}})
  self.assertEqual(d['sections'],[]);self.assertEqual(d['cited_source_count'],0)
