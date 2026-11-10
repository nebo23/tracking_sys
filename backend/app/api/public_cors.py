"""Origin-scoped browser access for public collection routes (specification 004, R004-01).

Customer websites call /collect/v1/{public_key}/... from their own origins. Those origins are
never added to the credentialed platform CORS policy. Instead:

- PlatformCors is Starlette's CORSMiddleware for every other path; it leaves public
  collection paths alone, so platform origins gain no credentialed access to them and
  customer origins gain none to platform routes.
- PublicCollectionCors answers CORS preflights for public collection routes only when the
  Origin is registered for that public key's active browser source, the method is POST, and
  the only requested header is Content-Type. On actual requests it adds
  Access-Control-Allow-Origin, never Access-Control-Allow-Credentials, after the route itself
  has accepted the Origin (the route marks the request scope). Unregistered origins receive no
  CORS grant, so a browser cannot read the response.
"""

import re
from collections.abc import Callable

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PUBLIC_PREFIX = "/collect/v1/"
PUBLIC_ROUTE = re.compile(r"/collect/v1/(pk_[A-Za-z0-9_-]{43})/(events|consent|erasure)")
# Request scope key through which a public route reports the Origin it accepted.
SCOPE_KEY = "tracking.public_cors"
ALLOWED_REQUEST_HEADERS = frozenset({"content-type"})
PREFLIGHT_MAX_AGE = "600"
_SAFE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _is_public(scope: Scope) -> bool:
    return scope["type"] == "http" and scope["path"].startswith(PUBLIC_PREFIX)


# The platform's credentialed CORS policy for every path except public collection routes.
class PlatformCors(CORSMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if _is_public(scope):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


# Record that the public route accepted this request's Origin, so the response may be read by
# that origin. Has no effect outside PublicCollectionCors.
def grant_origin(scope: Scope, origin: str) -> None:
    grant = scope.get(SCOPE_KEY)
    if isinstance(grant, dict):
        grant["origin"] = origin


class PublicCollectionCors:
    # origins(app, public_key) returns the registered Origins of the key's active browser
    # source (empty when none); it runs in a worker thread because it queries the database.
    def __init__(self, app: ASGIApp, origins: Callable[[object, str], frozenset[str]]) -> None:
        self.app, self.origins = app, origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_public(scope):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if scope["method"] == "OPTIONS":
            response = await self._preflight(scope, headers)
            await response(scope, receive, send)
            return
        origin = headers.get("origin")
        grant: dict[str, str] = {}
        scope[SCOPE_KEY] = grant

        async def cors_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers.add_vary_header("Origin")
                if origin is not None and grant.get("origin") == origin:
                    response_headers["Access-Control-Allow-Origin"] = origin
            await send(message)

        await self.app(scope, receive, cors_send)

    async def _preflight(self, scope: Scope, headers: Headers) -> Response:
        origin = headers.get("origin")
        method = headers.get("access-control-request-method")
        requested = {
            item.strip().lower()
            for item in headers.get("access-control-request-headers", "").split(",")
            if item.strip()
        }
        route = PUBLIC_ROUTE.fullmatch(scope["path"])
        allowed = False
        if route and origin and method == "POST" and requested <= ALLOWED_REQUEST_HEADERS:
            allowed = origin in await run_in_threadpool(self.origins, scope["app"], route[1])
        if not allowed:
            return JSONResponse(
                {"error": "cors_not_allowed"},
                status_code=403,
                headers={**_SAFE_HEADERS, "Vary": "Origin"},
            )
        return Response(
            status_code=204,
            headers={
                **_SAFE_HEADERS,
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": PREFLIGHT_MAX_AGE,
                "Vary": "Origin",
            },
        )
