"""Bound request bodies before JSON parsing and prevent caching authenticated data."""

import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Per-route exceptions to the default bound (specification 015, D-067 decision D13): the Paymob
# processed callback and the 015-D booking and CRM callbacks (D-068) up to 64 KiB, and the CSV
# preview and commit up to 2 MiB. Each entry is a
# method, a full-path pattern and a limit in bytes; every other route keeps the default.
ROUTE_LIMITS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("POST", re.compile(r"/payments/paymob/callback/[^/]+"), 65536),
    ("POST", re.compile(r"/integrations/(?:cal-com|webhook)/[^/]+"), 65536),
    (
        "POST",
        re.compile(r"/agencies/[^/]+/clients/[^/]+/revenue-imports/(?:preview|[0-9a-f]{64})"),
        2097152,
    ),
)


# Pure ASGI middleware installed by create_app around every HTTP request. It buffers mutation
# bodies up to the route's limit before routing and adds no-store, no-referrer, and nosniff
# headers to every HTTP response. A declared Content-Length above the limit is refused before
# any body is read; otherwise the body is counted while it streams and refused at the first
# chunk that passes the limit. Non-HTTP scopes, such as lifespan, pass through unchanged.
class RequestBoundary:
    # Wrap the next ASGI application; 16 KiB covers the bounded JSON request contracts.
    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int = 16384,
        route_limits: tuple[tuple[str, re.Pattern[str], int], ...] = ROUTE_LIMITS,
    ) -> None:
        self.app, self.max_bytes, self.route_limits = app, max_bytes, route_limits

    # The body limit of one request: the first matching route exception, or the default.
    def limit(self, method: str, path: str) -> int:
        for route_method, pattern, limit in self.route_limits:
            if method == route_method and pattern.fullmatch(path):
                return limit
        return self.max_bytes

    # Called once per ASGI connection scope.
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Replace any downstream Cache-Control header and add privacy headers to the response
        # start message before forwarding it.
        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ]
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        if scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            limit = self.limit(scope["method"], scope.get("path", ""))
            declared = dict(scope.get("headers") or []).get(b"content-length", b"")
            if declared.isdigit() and int(declared) > limit:
                await JSONResponse({"error": "request_too_large"}, status_code=413)(
                    scope, receive, private_send
                )
                return
            content = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                content.extend(message.get("body", b""))
                if len(content) > limit:
                    await JSONResponse({"error": "request_too_large"}, status_code=413)(
                        scope, receive, private_send
                    )
                    return
                if not message.get("more_body", False):
                    break
            sent = False

            # Replay the already bounded body once to the application, then defer to the
            # original receive channel, for example for disconnect notifications.
            async def bounded_receive() -> Message:
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": bytes(content), "more_body": False}
                return await receive()

            await self.app(scope, bounded_receive, private_send)
        else:
            await self.app(scope, receive, private_send)
