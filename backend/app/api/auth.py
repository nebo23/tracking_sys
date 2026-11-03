"""Local email/password routes; Google and Facebook login are explicitly deferred."""

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
)
from app.security import AuthError, csrf_token
from app.services.auth import AuthService, enforce_rate_limit

router = APIRouter(prefix="/auth", tags=["Authentication"])


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


@router.post("/verify-email", status_code=204, dependencies=[Depends(require_origin)])
def verify_email(data: TokenInput, request: Request, session: SessionDep) -> Response:
    throttle(request, "verify-token")
    AuthService(session, request.app.state.settings).verify_email(data.token.get_secret_value())
    return Response(status_code=204)


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
    response.set_cookie(
        settings.cookie_name,
        raw,
        max_age=settings.session_lifetime_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return SessionResponse(
        user=UserResponse.model_validate(user), csrf_token=csrf_token(settings, raw)
    )


@router.get("/me", response_model=SessionResponse)
def me(request: Request, browser: BrowserDep) -> SessionResponse:
    return SessionResponse(
        user=UserResponse.model_validate(browser.user),
        csrf_token=csrf_token(request.app.state.settings, browser.token),
    )


def clear_cookie(request: Request) -> Response:
    response = Response(status_code=204)
    settings = request.app.state.settings
    response.delete_cookie(
        settings.cookie_name, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
    return response


@router.post("/logout", status_code=204)
def logout(request: Request, session: SessionDep, browser: BrowserDep) -> Response:
    AuthService(session, request.app.state.settings).logout(browser.user, browser.session)
    return clear_cookie(request)


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, session: SessionDep, browser: BrowserDep) -> Response:
    AuthService(session, request.app.state.settings).logout_all(browser.user)
    return clear_cookie(request)


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


@router.post("/reset-password", status_code=204, dependencies=[Depends(require_origin)])
def reset_password(data: PasswordReset, request: Request, session: SessionDep) -> Response:
    throttle(request, "reset-token")
    AuthService(session, request.app.state.settings).reset_password(
        data.token.get_secret_value(), data.password.get_secret_value()
    )
    return clear_cookie(request)


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
