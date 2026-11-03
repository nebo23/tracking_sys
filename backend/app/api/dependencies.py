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

cookie_scheme = APIKeyCookie(name="tracking_session", auto_error=False)
secure_cookie_scheme = APIKeyCookie(
    name="__Host-tracking_session", auto_error=False, scheme_name="SecureSession"
)
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="ServiceKey")


def get_session(request: Request) -> Iterator[Session]:
    # Function scope commits before response delivery, including the session cookie.
    with Session(request.app.state.engine, expire_on_commit=False) as session, session.begin():
        yield session


SessionDep = Annotated[Session, Depends(get_session, scope="function")]


def require_origin(
    request: Request,
    _origin: Annotated[
        str | None, Header(alias="Origin", description="Exact allowed browser origin.")
    ] = None,
) -> None:
    if request.headers.get("origin") not in request.app.state.settings.allowed_origins:
        raise AuthError("origin_not_allowed", 403)


@dataclass(frozen=True)
class BrowserIdentity:
    user: User
    session: AuthSession
    token: str


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


BrowserDep = Annotated[BrowserIdentity, Depends(browser_identity)]


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


ReaderDep = Annotated[Principal, Depends(reader_principal)]
