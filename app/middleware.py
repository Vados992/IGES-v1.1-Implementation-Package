"""Bound request bodies, including requests without Content-Length."""
from app.problems import problem
from collections import deque
import time


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        limit = 8388608 if scope['path'].startswith('/v1/cases/') and scope['path'].endswith('/documents') else self.max_bytes
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                response = problem(413, 'REQUEST_TOO_LARGE')
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break

        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


class RateLimitMiddleware:
    """Bounded per-process peer limit. A shared external gateway is still needed for production."""
    def __init__(self, app, limit=240):
        self.app, self.limit, self.peers = app, limit, {}

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        peer = (scope.get('client') or ('unknown',))[0]
        if peer not in self.peers and len(self.peers) >= 5000:
            self.peers.pop(next(iter(self.peers)))
        window = self.peers.setdefault(peer, deque())
        now = time.monotonic()
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= self.limit:
            return await problem(429, 'RATE_LIMIT_EXCEEDED', headers={'Retry-After': '60'})(scope, receive, send)
        window.append(now)
        return await self.app(scope, receive, send)
