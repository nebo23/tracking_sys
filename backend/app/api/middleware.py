"""Bound request bodies before JSON parsing and prevent caching authenticated data."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Pure ASGI middleware installed by create_app around every HTTP request. It buffers mutation
# bodies up to max_bytes before routing and adds no-store, no-referrer, and nosniff headers to
# every HTTP response. Non-HTTP scopes, such as lifespan, pass through unchanged.
class RequestBoundary:
    # Wrap the next ASGI application; 16 KiB covers the bounded JSON request contracts.
    def __init__(self, app: ASGIApp, max_bytes: int = 16384) -> None:
        self.app, self.max_bytes = app, max_bytes

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
            content = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                content.extend(message.get("body", b""))
                if len(content) > self.max_bytes:
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
