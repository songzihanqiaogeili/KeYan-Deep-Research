import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
from scientific_research.mcp_server import SnapshotServer


def snapshot():
    return {'schema_version': 1, 'workflow_type': 'scientific_research', 'run_id': 'test',
            'papers': [{'paper_id': 'p1', 'title': 'Paper'}],
            'claims': [{'evidence_id': 'e1', 'paper_id': 'p1', 'quote': 'Original text', 'page': 1}],
            'directions': []}


def request(method, params=None, ident=1):
    return {'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params or {}}


class MCPTests(unittest.TestCase):
    def ready(self):
        server = SnapshotServer(snapshot())
        server.handle(request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}))
        server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return server

    def test_cannot_call_before_initialization(self):
        reply = SnapshotServer(snapshot()).handle(request('tools/list'))
        self.assertIn('error', reply)

    def test_read_only_tool_discovery_and_evidence_lookup(self):
        server = self.ready()
        names = {t['name'] for t in server.handle(request('tools/list'))['result']['tools']}
        self.assertEqual(names, {'list_papers', 'get_evidence', 'list_directions'})
        reply = server.handle(request('tools/call', {'name': 'get_evidence', 'arguments': {'evidence_id': 'e1'}}))
        value = json.loads(reply['result']['content'][0]['text'])
        self.assertEqual(value['quote'], 'Original text')

    def test_unknown_or_path_arguments_rejected(self):
        server = self.ready()
        for args in [{'evidence_id': 'missing'}, {'path': 'secret'}, {'evidence_id': 'e1', 'path': 'secret'}]:
            reply = server.handle(request('tools/call', {'name': 'get_evidence', 'arguments': args}))
            self.assertTrue(reply['result']['isError'])

    def test_malformed_protocol_is_error(self):
        reply = self.ready().handle({'id': 1, 'method': 'tools/list'})
        self.assertEqual(reply['error']['code'], -32600)

    def test_non_string_tool_name_does_not_crash_server(self):
        server = self.ready()
        for name in [[], {}, None, 1]:
            reply = server.handle(request('tools/call', {'name': name}))
            self.assertEqual(reply['error']['code'], -32602)
        self.assertIn('result', server.handle(request('tools/list')))

    def test_stdio_process_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            path.write_text(json.dumps(snapshot()), encoding='utf-8')
            messages = [request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}),
                        {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, request('tools/list', ident=2),
                        request('tools/call', {'name': 'get_evidence', 'arguments': {'evidence_id': 'e1'}}, 3)]
            env = {**os.environ, 'PYTHONPATH': str(APP), 'PYTHONIOENCODING': 'utf-8'}
            proc = subprocess.run([sys.executable, '-B', '-m', 'scientific_research.mcp_server', '--result', str(path)],
                                  input='\n'.join(json.dumps(m) for m in messages) + '\n', capture_output=True,
                                  text=True, encoding='utf-8', timeout=15, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            replies = [json.loads(line) for line in proc.stdout.splitlines()]
            self.assertEqual([r['id'] for r in replies], [1, 2, 3])
            self.assertFalse(replies[-1]['result']['isError'])


if __name__ == '__main__':
    unittest.main()
