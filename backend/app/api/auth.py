"""Local email/password and numeric verification routes; Google sign-in is in app.api.google."""

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import BrowserDep, SessionDep, require_origin
from app.api.schemas import (
    Acknowledgement,
    EmailInput,
    Login,
    PasswordChange,
    PasswordReset,
    Registration,
    SessionResponse,
    TokenInput,
    UserResponse,
    VerificationCode,
)
from app.config import Settings
from app.security import AuthError, csrf_token
from app.services.auth import AuthService, enforce_rate_limit

# All browser authentication routes live under /auth and share one OpenAPI tag.
router = APIRouter(prefix="/auth", tags=["Authentication"])


# Apply persistent throttles before route work: a per-peer bucket for every call and, when a
# subject is supplied, a per-scope subject bucket (login attempts per minute, otherwise three
# per hour). Counters commit through the separate security engine, so they persist even when
# the request transaction later rolls back. Raises RateLimited when a limit is exceeded.
def throttle(request: Request, scope: str, subject: str | None = None) -> None:
    settings, engine = request.app.state.settings, request.app.state.security_engine
    peer = request.client.host if request.client else "unknown"
    enforce_rate_limit(
        engine, settings, "auth-ip", peer, limit=settings.auth_requests_per_minute, period=60
    )
    if subject is not None:
        enforce_rate_limit(
            engine,
            settings,
            scope,
            subject,
            limit=settings.login_attempts_per_minute if scope == "login" else 3,
            period=60 if scope == "login" else 3600,
        )


# Self-service registration. Requires an allowed Origin, throttles by peer and email, and
# atomically stores an unverified account, credential, token digest, and encrypted outbox
# entry. The generic 202 response is identical for existing emails and returns no token.
@router.post(
    "/register",
    status_code=202,
    response_model=Acknowledgement,
    dependencies=[Depends(require_origin)],
)
def register(data: Registration, request: Request, session: SessionDep) -> Acknowledgement:
    throttle(request, "register", data.email)
    AuthService(session, request.app.state.settings).register(
        data.email, data.display_name, data.password.get_secret_value()
    )
    return Acknowledgement()


# Queue a fresh numeric verification code for an active unverified account once the resend
# cooldown has passed; the previous code stops working. The generic 202 response does not
# reveal whether an eligible account exists or whether a code was queued.
@router.post(
    "/resend-verification",
    status_code=202,
    response_model=Acknowledgement,
    dependencies=[Depends(require_origin)],
)
def resend_verification(data: EmailInput, request: Request, session: SessionDep) -> Acknowledgement:
    throttle(request, "verify-email", data.email)
    AuthService(session, request.app.state.settings).request_verification(data.email)
    return Acknowledgement()


# Verify an email with the six-digit code from the latest verification message (D-022). 204
# on success; every wrong, expired, superseded, or exhausted code and every unknown email gets
# the same 400 invalid_or_expired_code. Failures are counted independently of the rolled-back
# request; the per-email 24-hour failure cap returns 429 with Retry-After. Throttled per peer.
@router.post("/verify-email-code", status_code=204, dependencies=[Depends(require_origin)])
def verify_email_code(data: VerificationCode, request: Request, session: SessionDep) -> Response:
    throttle(request, "verify-code")
    AuthService(session, request.app.state.settings).verify_email_code(
        data.email, data.code, request.app.state.security_engine
    )
    return Response(status_code=204)


# Legacy transition (D-022): consume a verification link token issued before numeric codes,
# while it is unexpired; no new links are issued. 204 on success, a generic invalid-token
# error otherwise. Throttled per peer.
@router.post("/verify-email", status_code=204, dependencies=[Depends(require_origin)])
def verify_email(data: TokenInput, request: Request, session: SessionDep) -> Response:
    throttle(request, "verify-token")
    AuthService(session, request.app.state.settings).verify_email(data.token.get_secret_value())
    return Response(status_code=204)


# Set the opaque session cookie: HttpOnly, SameSite=Lax, path=/, Secure when configured, and
# the __Host- prefix in secure deployments. Shared by password login and Google sign-in.
def set_session_cookie(response: Response, settings: Settings, raw: str) -> None:
    response.set_cookie(
        settings.cookie_name,
        raw,
        max_age=settings.session_lifetime_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


# Password login for a verified active account. On success, set the HttpOnly session cookie
# and return the user plus the session-bound CSRF token. A failure records login_failed in an
# independent transaction before the request transaction rolls back.
@router.post("/login", response_model=SessionResponse, dependencies=[Depends(require_origin)])
def login(
    data: Login, request: Request, response: Response, session: SessionDep
) -> SessionResponse:
    throttle(request, "login", data.email)
    settings = request.app.state.settings
    service = AuthService(session, settings)
    try:
        user, raw = service.login(data.email, data.password.get_secret_value())
    except AuthError:
        # Failed attempts and security events survive the failed request transaction.
        from sqlalchemy.orm import Session

        with Session(request.app.state.security_engine) as audit, audit.begin():
            AuthService(audit, settings).event("login_failed")
        raise
    set_session_cookie(response, settings, raw)
    return SessionResponse(
        user=UserResponse.model_validate(user), csrf_token=csrf_token(settings, raw)
    )


# Return the current browser identity and its CSRF token; a safe GET, so no CSRF is required.
@router.get("/me", response_model=SessionResponse)
def me(request: Request, browser: BrowserDep) -> SessionResponse:
    return SessionResponse(
        user=UserResponse.model_validate(browser.user),
        csrf_token=csrf_token(request.app.state.settings, browser.token),
    )


# Build a 204 response that clears the session cookie with the attributes used to set it.
def clear_cookie(request: Request) -> Response:
    response = Response(status_code=204)
    settings = request.app.state.settings
    response.delete_cookie(
        settings.cookie_name, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
    return response


# Revoke the current server-side session (Origin/CSRF enforced by BrowserDep) and clear it.
@router.post("/logout", status_code=204)
def logout(request: Request, session: SessionDep, browser: BrowserDep) -> Response:
    AuthService(session, request.app.state.settings).logout(browser.user, browser.session)
    return clear_cookie(request)


# Revoke every unrevoked session of the current user and clear this browser's cookie.
@router.post("/logout-all", status_code=204)
def logout_all(request: Request, session: SessionDep, browser: BrowserDep) -> Response:
    AuthService(session, request.app.state.settings).logout_all(browser.user)
    return clear_cookie(request)


# Queue a password-reset link for a verified active account; the response is always generic.
@router.post(
    "/forgot-password",
    status_code=202,
    response_model=Acknowledgement,
    dependencies=[Depends(require_origin)],
)
def forgot_password(data: EmailInput, request: Request, session: SessionDep) -> Acknowledgement:
    throttle(request, "reset-email", data.email)
    AuthService(session, request.app.state.settings).request_reset(data.email)
    return Acknowledgement()


# Consume a reset token, replace the password, revoke all sessions, and clear the cookie.
@router.post("/reset-password", status_code=204, dependencies=[Depends(require_origin)])
def reset_password(data: PasswordReset, request: Request, session: SessionDep) -> Response:
    throttle(request, "reset-token")
    AuthService(session, request.app.state.settings).reset_password(
        data.token.get_secret_value(), data.password.get_secret_value()
    )
    return clear_cookie(request)


# Authenticated password change: verify the current password, store the new hash, revoke all
# sessions including this one, and clear the cookie. Throttled per peer and per user.
@router.post("/change-password", status_code=204)
def change_password(
    data: PasswordChange, request: Request, session: SessionDep, browser: BrowserDep
) -> Response:
    throttle(request, "password-change", str(browser.user.id))
    AuthService(session, request.app.state.settings).change_password(
        browser.user.id,
        data.current_password.get_secret_value(),
        data.new_password.get_secret_value(),
    )
    return clear_cookie(request)
