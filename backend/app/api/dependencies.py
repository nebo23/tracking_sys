"""Resolve authenticated identity before any agency or client service is called."""

import hmac
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.models import AuthSession, User
from app.security import AuthError, csrf_token
from app.services.access import Principal, authenticate_service_key
from app.services.auth import AuthService

# OpenAPI security schemes for the development cookie, the __Host- secure cookie, and service
# Bearer keys. auto_error=False lets the dependencies below apply the project's own sanitized
# errors; the schemes document inputs and do not authenticate by themselves.
cookie_scheme = APIKeyCookie(name="tracking_session", auto_error=False)
secure_cookie_scheme = APIKeyCookie(
    name="__Host-tracking_session", auto_error=False, scheme_name="SecureSession"
)
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="ServiceKey")


# Yield one database Session (a unit of work, not a browser login session) for the request.
# session.begin() commits when the dependency exits normally and rolls back on an exception.
def get_session(request: Request) -> Iterator[Session]:
    # Function scope commits before response delivery, including the session cookie.
    with Session(request.app.state.engine, expire_on_commit=False) as session, session.begin():
        yield session


# Route parameter alias: obtains the database Session through get_session with function scope,
# so the transaction commits before the response is sent.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]


# Require an Origin header that exactly matches one configured allowed origin. Unauthenticated
# mutation routes use it as a decorator dependency, which enforces the check without passing
# a value to the handler; browser_identity also calls it for cookie mutations.
def require_origin(
    request: Request,
    _origin: Annotated[
        str | None, Header(alias="Origin", description="Exact allowed browser origin.")
    ] = None,
) -> None:
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise AuthError("origin_not_allowed", 403)


# Authenticated browser context: the active user, the locked session row, and the raw cookie
# token needed to derive the session-bound CSRF value.
@dataclass(frozen=True)
class BrowserIdentity:
    user: User
    session: AuthSession
    token: str


# Authenticate a browser request from the configured session cookie. A request that also has
# an Authorization header is rejected as ambiguous. Mutations additionally require an allowed
# Origin and the session-bound X-CSRF-Token. AuthService.authenticate then checks expiry,
# idle time, revocation, verification, and active status and locks the user and session rows.
# The underscored parameters only document headers/cookies in OpenAPI.
def browser_identity(
    request: Request,
    session: SessionDep,
    _development_cookie: Annotated[str | None, Depends(cookie_scheme)] = None,
    _secure_cookie: Annotated[str | None, Depends(secure_cookie_scheme)] = None,
    _origin: Annotated[
        str | None, Header(alias="Origin", description="Required for mutations.")
    ] = None,
    _csrf: Annotated[
        str | None,
        Header(
            alias="X-CSRF-Token",
            description="Session-bound token from login or /auth/me; required for mutations.",
        ),
    ] = None,
) -> BrowserIdentity:
    settings = request.app.state.settings
    raw = request.cookies.get(settings.cookie_name)
    if not raw or request.headers.get("authorization"):
        raise AuthError("authentication_required")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        submitted = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(submitted, csrf_token(settings, raw)):
            raise AuthError("csrf_failed", 403)
    user, item = AuthService(session, settings).authenticate(raw)
    return BrowserIdentity(user, item, raw)


# Route parameter alias for browser-only routes; it shares the request's SessionDep.
BrowserDep = Annotated[BrowserIdentity, Depends(browser_identity)]


# Resolve the principal for client read routes. An Authorization header selects a service key,
# and combining it with a session cookie is rejected to avoid ambiguous authority; otherwise
# the browser session is used. The principal still requires resolve_scope for each resource.
def reader_principal(
    request: Request,
    session: SessionDep,
    authorization: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    _development_cookie: Annotated[str | None, Depends(cookie_scheme)] = None,
    _secure_cookie: Annotated[str | None, Depends(secure_cookie_scheme)] = None,
) -> Principal:
    if request.headers.get("authorization"):
        if request.cookies.get(request.app.state.settings.cookie_name) or authorization is None:
            raise AuthError("authentication_required")
        return authenticate_service_key(session, authorization.credentials)
    browser = browser_identity(request, session)
    return Principal("user", browser.user.id)


# Route parameter alias for routes readable by browser users or scoped service keys.
ReaderDep = Annotated[Principal, Depends(reader_principal)]
