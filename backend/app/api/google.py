"""Google sign-in and account-linking routes (D-022); Facebook remains deferred."""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError

from app.api.auth import set_session_cookie
from app.api.dependencies import BrowserDep, SessionDep
from app.api.schemas import AuthorizationURL
from app.config import Settings
from app.security import AuthError
from app.services.auth import enforce_rate_limit
from app.services.google import (
    TRANSACTION_SECONDS,
    GoogleProviderError,
    begin_authorization,
    complete_authorization,
)

# Fixed error codes the callback may append to the completion URL; anything else becomes
# google_sign_in_failed, so no provider or internal detail reaches the browser address bar.
CALLBACK_ERRORS = frozenset(
    {
        "google_sign_in_failed",
        "google_sign_in_cancelled",
        "google_email_not_verified",
        "google_link_required",
        "google_identity_in_use",
        "google_already_linked",
        "google_sign_in_conflict",
        "google_unavailable",
    }
)

router = APIRouter(prefix="/auth/google", tags=["Google sign-in"])


# Decorator dependency: the routes exist only while TRACKING_GOOGLE_SIGN_IN_ENABLED is true.
def require_enabled(request: Request) -> None:
    if not request.app.state.settings.google_sign_in_enabled:
        raise AuthError("not_found", 404)


# Decorator dependency: persistent per-peer limit in its own namespace, resolved before any
# session authentication or transaction work.
def google_peer_limit(request: Request) -> None:
    settings = request.app.state.settings
    peer = request.client.host if request.client else "unknown"
    enforce_rate_limit(
        request.app.state.security_engine,
        settings,
        "google-ip",
        peer,
        limit=settings.auth_requests_per_minute,
        period=60,
    )


# Bind the authorization to this browser with a short-lived HttpOnly cookie limited to the
# /auth/google path. SameSite=Lax lets the top-level redirect back from Google include it.
def set_binding_cookie(response: Response, settings: Settings, binding: str) -> None:
    response.set_cookie(
        settings.oauth_cookie_name,
        binding,
        max_age=TRANSACTION_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/auth/google",
    )


# Begin Google sign-in from a top-level browser navigation: store a login transaction, set the
# binding cookie, and redirect (303) to Google with identity scopes only.
@router.get(
    "/start",
    status_code=303,
    response_class=RedirectResponse,
    dependencies=[Depends(require_enabled), Depends(google_peer_limit)],
)
def start(request: Request, session: SessionDep) -> RedirectResponse:
    settings = request.app.state.settings
    url, binding = begin_authorization(session, settings, request.app.state.google, "login")
    response = RedirectResponse(url, status_code=303)
    set_binding_cookie(response, settings, binding)
    return response


# Begin linking Google to the signed-in account. BrowserDep enforces the session, Origin, and
# CSRF token; the response carries the authorization URL for the browser to open.
@router.post(
    "/link",
    response_model=AuthorizationURL,
    dependencies=[Depends(require_enabled), Depends(google_peer_limit)],
)
def link(
    request: Request, response: Response, session: SessionDep, browser: BrowserDep
) -> AuthorizationURL:
    settings = request.app.state.settings
    url, binding = begin_authorization(
        session, settings, request.app.state.google, "link", browser.user.id
    )
    set_binding_cookie(response, settings, binding)
    return AuthorizationURL(authorization_url=url)


# Google redirects here. This is the only route that accepts protocol values (code, state,
# error) in the query string, and the only mutation without an Origin header; the single-use
# state, browser-binding cookie, nonce, and PKCE protect it instead. On success a login sets
# the existing session cookie. The browser is always redirected (303) to the configured
# completion URL with, at most, a fixed result code; no token ever appears in a URL.
@router.get(
    "/callback",
    status_code=303,
    response_class=RedirectResponse,
    dependencies=[Depends(require_enabled), Depends(google_peer_limit)],
)
def callback(
    request: Request,
    session: SessionDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=128)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> RedirectResponse:
    settings = request.app.state.settings
    result: dict[str, str] = {}
    raw: str | None = None
    if error:
        result["error"] = "google_sign_in_cancelled"
    elif not code or not state:
        result["error"] = "google_sign_in_failed"
    else:
        try:
            _, purpose, raw = complete_authorization(
                session,
                settings,
                request.app.state.google,
                state,
                request.cookies.get(settings.oauth_cookie_name),
                code,
            )
        except AuthError as failure:
            code_name = failure.code if failure.code in CALLBACK_ERRORS else None
            result["error"] = code_name or "google_sign_in_failed"
        except GoogleProviderError as failure:
            known = failure.code in CALLBACK_ERRORS
            result["error"] = failure.code if known else "google_unavailable"
        except IntegrityError:
            result["error"] = "google_sign_in_conflict"
        else:
            result["result"] = "linked" if purpose == "link" else "signed_in"
    target = settings.google_completion_url
    separator = "&" if "?" in target else "?"
    response = RedirectResponse(f"{target}{separator}{urlencode(result)}", status_code=303)
    if raw is not None:
        set_session_cookie(response, settings, raw)
    response.delete_cookie(
        settings.oauth_cookie_name,
        path="/auth/google",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response
