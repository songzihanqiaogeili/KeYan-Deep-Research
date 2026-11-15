import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from scientific_research.middleware import BodyLimit


class BodyLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_upload_rejected_before_multipart_parser(self):
        called, responses = [], []
        async def app(scope, receive, send):
            called.append(True)
        chunks = iter([{'type': 'http.request', 'body': b'123456', 'more_body': True},
                       {'type': 'http.request', 'body': b'123456', 'more_body': False}])
        async def receive():
            return next(chunks)
        async def send(message):
            responses.append(message)
        await BodyLimit(app, max_bytes=10)({'type':'http','method':'POST'}, receive, send)
        self.assertEqual(called, [])
        self.assertEqual(responses[0]['status'], 413)

    async def test_small_body_is_replayed_without_loss(self):
        observed = []
        async def app(scope, receive, send):
            observed.append((await receive())['body'])
        async def receive():
            return {'type':'http.request','body':b'abc','more_body':False}
        await BodyLimit(app, max_bytes=10)({'type':'http','method':'POST'}, receive, None)
        self.assertEqual(observed, [b'abc'])
