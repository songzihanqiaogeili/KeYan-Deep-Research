import shutil
import subprocess
import unittest
from pathlib import Path


class FrontendConnectionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node is needed')
    def test_completed_run_drains_events_and_avoids_concurrent_duplicates(self):
        directory=Path(__file__).resolve().parent
        source=directory.parent/'app/scientific_research/web/app.js'
        result=subprocess.run(['node',str(directory/'frontend_events.cjs'),str(source)],capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    @unittest.skipUnless(shutil.which('node'),'Node is needed for frontend transport regression')
    def test_transport_failure_and_search_failure_are_distinguished(self):
        directory=Path(__file__).resolve().parent
        source=directory.parent/'app/scientific_research/web/app.js'
        result=subprocess.run(['node',str(directory/'frontend_connection.cjs'),str(source)],capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
