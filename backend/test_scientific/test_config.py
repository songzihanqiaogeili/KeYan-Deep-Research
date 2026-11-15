import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from scientific_research.config import load_project_env


class ConfigTests(unittest.TestCase):
    def test_optional_embedding_and_tracing_settings_are_loaded_but_unrelated_variables_are_not(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            path=Path(tmp)/'.env.scientific'
            path.write_text('SCIENTIFIC_EMBEDDING_MODEL=bge-m3\nSCIENTIFIC_LANGSMITH_ENABLED=false\nLANGSMITH_PROJECT=test\nLANGSMITH_API_KEY=fake\nPATH=forbidden\n',encoding='utf-8')
            load_project_env(path)
            self.assertEqual(os.environ.get('SCIENTIFIC_EMBEDDING_MODEL'),'bge-m3')
            self.assertEqual(os.environ.get('LANGSMITH_PROJECT'),'test')
            self.assertNotIn('PATH',os.environ)
    def test_project_settings_load_without_overriding_powershell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'.env.scientific'
            path.write_text('# local config\nSCIENTIFIC_LLM_API_KEY=ollama\nSCIENTIFIC_LLM_MODEL="qwen3.5:4b"\nHOME=do-not-change\n',encoding='utf-8')
            with patch.dict(os.environ,{'SCIENTIFIC_LLM_MODEL':'explicit-model'},clear=True):
                load_project_env(path)
                self.assertEqual(os.environ['SCIENTIFIC_LLM_API_KEY'],'ollama')
                self.assertEqual(os.environ['SCIENTIFIC_LLM_MODEL'],'explicit-model')
                self.assertNotIn('HOME',os.environ)

    def test_absent_file_is_optional_and_values_are_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{},clear=True):
            path=Path(tmp)/'.env.scientific'
            load_project_env(path)
            path.write_text('SCIENTIFIC_LLM_MODEL=$(echo injected)\n',encoding='utf-8')
            load_project_env(path)
            self.assertEqual(os.environ['SCIENTIFIC_LLM_MODEL'],'$(echo injected)')

    def test_local_token_persists_between_launcher_processes(self):
        from scientific_research.config import local_access_token
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            first = local_access_token(Path(tmp))
            self.assertGreaterEqual(len(first), 24)
            self.assertEqual(first, local_access_token(Path(tmp)))
            with patch.dict(os.environ, {'SCIENTIFIC_LOCAL_TOKEN': 'explicit-local-token'}):
                self.assertEqual(local_access_token(Path(tmp)), 'explicit-local-token')
