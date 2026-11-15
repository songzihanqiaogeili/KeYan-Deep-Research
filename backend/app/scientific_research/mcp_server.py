"""Minimal read-only MCP stdio server for one explicitly selected result snapshot.

Protocol: 2025-06-18. Local single-user stdio only, not an HTTP service.
"""
import argparse
import json
import sys
from pathlib import Path

PROTOCOL = '2025-06-18'
EMPTY_SCHEMA = {'type': 'object', 'properties': {}, 'additionalProperties': False}
TOOLS = [
    {'name': 'list_papers', 'description': 'List papers in the selected research result.', 'inputSchema': EMPTY_SCHEMA},
    {'name': 'get_evidence', 'description': 'Read a located quote by evidence ID from this result only.',
     'inputSchema': {'type': 'object', 'properties': {'evidence_id': {'type': 'string'}}, 'required': ['evidence_id'], 'additionalProperties': False}},
    {'name': 'list_directions', 'description': 'List candidate directions; these are not novelty-certified.', 'inputSchema': EMPTY_SCHEMA},
]


class SnapshotServer:
    def __init__(self, result: dict):
        if not isinstance(result, dict) or result.get('workflow_type') != 'scientific_research' or result.get('schema_version') != 1:
            raise ValueError('Unsupported scientific research snapshot')
        for name in ('papers', 'claims', 'directions'):
            if not isinstance(result.get(name), list) or any(not isinstance(v, dict) for v in result[name]):
                raise ValueError(f'Invalid snapshot field: {name}')
        papers = {p['paper_id'] for p in result['papers']}
        ids = [c['evidence_id'] for c in result['claims']]
        if len(ids) != len(set(ids)) or any(c['paper_id'] not in papers for c in result['claims']):
            raise ValueError('Invalid snapshot evidence references')
        self.result = json.loads(json.dumps(result))
        self.initialized = self.ready = False

    def handle(self, message):
        ident = message.get('id') if isinstance(message, dict) else None

        def error(code, text):
            return {'jsonrpc': '2.0', 'id': ident, 'error': {'code': code, 'message': text}}

        def reply(value):
            return {'jsonrpc': '2.0', 'id': ident, 'result': value}

        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            return error(-32600, 'Invalid request')
        method, params = message['method'], message.get('params', {})
        if method == 'notifications/initialized' and 'id' not in message:
            self.ready = self.initialized
            return None
        if 'id' not in message:
            return None
        if not isinstance(params, dict):
            return error(-32602, 'Parameters must be an object')
        if method == 'initialize':
            if self.initialized:
                return error(-32600, 'Already initialized')
            if not isinstance(params.get('protocolVersion'), str) or not isinstance(params.get('capabilities'), dict) or not isinstance(params.get('clientInfo'), dict):
                return error(-32602, 'Missing initialization parameters')
            self.initialized = True
            return reply({'protocolVersion': PROTOCOL, 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'scientific-research-evidence', 'version': '0.1.0'},
                          'instructions': 'Read-only local result. Quotes are located, not scientifically certified. Directions require novelty review.'})
        if method == 'ping':
            return reply({})
        if not self.ready:
            return error(-32002, 'Initialize and send notifications/initialized first')
        if method == 'tools/list':
            return reply({'tools': TOOLS})
        if method != 'tools/call':
            return error(-32601, 'Method not found')
        name, args = params.get('name'), params.get('arguments', {})
        if not isinstance(name, str):
            return error(-32602, 'Tool name must be a string')
        try:
            if not isinstance(args, dict):
                raise ValueError('Arguments must be an object')
            if name == 'get_evidence':
                if set(args) != {'evidence_id'} or not isinstance(args['evidence_id'], str):
                    raise ValueError('Only evidence_id is accepted')
                value = next((c for c in self.result['claims'] if c['evidence_id'] == args['evidence_id']), None)
                if value is None:
                    raise ValueError('Evidence not found in selected snapshot')
            elif name in {'list_papers', 'list_directions'}:
                if args:
                    raise ValueError('No arguments accepted')
                value = self.result['papers' if name == 'list_papers' else 'directions']
            else:
                raise ValueError('Unknown tool')
            return reply({'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}], 'isError': False})
        except ValueError as exc:
            return reply({'content': [{'type': 'text', 'text': str(exc)}], 'isError': True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    if args.result.stat().st_size > 16 * 1024 * 1024:
        parser.error('Snapshot exceeds 16 MiB')
    server = SnapshotServer(json.loads(args.result.read_text(encoding='utf-8')))
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    while True:
        line = sys.stdin.readline(1024 * 1024 + 1)
        if not line:
            break
        if len(line) > 1024 * 1024:
            print(json.dumps({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Message too large'}}), flush=True)
            break
        try:
            response = server.handle(json.loads(line))
        except json.JSONDecodeError:
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
