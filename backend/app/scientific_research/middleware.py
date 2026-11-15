"""Cap request bodies before framework multipart parsing, including chunked input."""
from starlette.responses import JSONResponse


class BodyLimit:
    def __init__(self, app, max_bytes=26 * 1024 * 1024):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') not in {'POST', 'PUT', 'PATCH'}:
            return await self.app(scope, receive, send)
        parts, total = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body = message.get('body', b'')
            total += len(body)
            if total > self.max_bytes:
                return await JSONResponse({'detail': 'Request body exceeds allowed size'}, status_code=413)(scope, receive, send)
            parts.append(body)
            if not message.get('more_body'):
                break
        payload, first = b''.join(parts), True

        async def replay():
            nonlocal first
            if first:
                first = False
                return {'type': 'http.request', 'body': payload, 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
