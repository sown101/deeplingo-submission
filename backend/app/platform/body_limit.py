"""Reject oversized HTTP request bodies before any route parses them (SEC-02).

FastAPI reads and parses form/multipart bodies while resolving a route's parameters, before
authentication dependencies run. This pure ASGI middleware caps the bytes that can reach that
parser: a declared Content-Length over the cap is refused at once, and streamed or chunked bodies
without one are counted as they arrive. WebSocket and lifespan scopes pass through untouched.
"""
from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The largest legitimate body is a speaking upload (2.6 MB WAV) plus multipart framing.
DEFAULT_MAX_BODY_BYTES = 3 * 1024 * 1024

_TOO_LARGE = json.dumps(
    {"error": "PayloadTooLarge", "message": "The request body is too large."}
).encode()


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _content_length(scope)
        if declared is not None and declared > self.max_body_bytes:
            await _reject(send)
            return

        received = 0
        too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, too_large
            if too_large:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    too_large = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if too_large and not response_started:
                # Whatever the route made of the truncated body (FastAPI turns it into a 400)
                # is replaced by the 413 below.
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if response_started:
                raise
        if too_large and not response_started:
            await _reject(send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _reject(send: Send) -> None:
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(_TOO_LARGE)).encode()),
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": _TOO_LARGE})
