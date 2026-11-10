"""FastAPI application factory for the backend and database foundation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.auth import router as auth_router
from app.api.collection import public_router as collection_public_router
from app.api.collection import router as collection_router
from app.api.collection import webhook_router as collection_webhook_router
from app.api.google import router as google_router
from app.api.middleware import RequestBoundary
from app.api.schemas import ErrorResponse
from app.api.tenancy import router as tenancy_router
from app.config import Settings
from app.database import create_database_engine, expected_revision, readiness_failure
from app.logging_config import configure_logging
from app.security import AuthError, RateLimited
from app.services.collection import CollectionError
from app.services.google import GoogleOIDC
from app.services.tenancy import AccessDenied, MembershipConflict


# Liveness body: the process answers HTTP; it says nothing about the database.
class HealthResponse(BaseModel):
    status: Literal["ok"]


# Readiness body: whether the database is reachable at the exact expected migration revision.
class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]


# Build a configured application. Uvicorn calls it with --factory; tests pass explicit
# settings. Without an argument, Settings() reads the environment and root .env and fails
# closed on invalid configuration before any route is served.
def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings if settings is not None else Settings()
    logger = configure_logging()

    # Application lifetime: create the request engine and a small separate security engine at
    # startup, read the expected migration head, and dispose of both pools at shutdown. The
    # lifespan does not run migrations or block startup on database availability. Logging is
    # configured again here because a server may apply its own logging configuration after the
    # application object was built; the allowlist must cover the server's loggers as well.
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        application.state.engine = create_database_engine(configuration)
        # Counters/failure events commit independently while a request may hold a user lock.
        # A separate bounded pool prevents concurrent requests starving their own commits.
        application.state.security_engine = create_database_engine(configuration, pool_size=2)
        try:
            application.state.expected_revision = expected_revision()
            logger.info("application_started")
            yield
        finally:
            application.state.engine.dispose()
            application.state.security_engine.dispose()
            logger.info("application_stopped")

    application = FastAPI(
        title="Tracking System API",
        version="0.4.0",
        description=(
            "Agency/client access, email/password authentication, invitations, "
            "scoped service credentials, numeric email verification, and optional Google sign-in. "
            "Facebook sign-in is deferred. "
            "Cookie mutations require an allowed Origin and X-CSRF-Token "
            "from login or /auth/me. "
            "Event collection (specification 004): trusted intake with ingest keys, limited-trust "
            "public intake, generic signed webhooks, consent, erasure, and diagnostics."
        ),
        lifespan=lifespan,
        responses={
            code: {"model": ErrorResponse} for code in (400, 401, 403, 409, 413, 422, 429, 503)
        },
    )
    application.state.settings = configuration
    # Google endpoint client (network access, cached discovery and keys); tests substitute it.
    application.state.google = GoogleOIDC(configuration)
    application.add_middleware(RequestBoundary)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configuration.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
    )

    # The handlers below translate known exceptions into fixed, sanitized JSON error codes.
    # None of them echo exception text, request input, or database details to the caller.

    # Authentication/authorization failures raised with an explicit code and status.
    @application.exception_handler(AuthError)
    async def authentication_error(request: Request, error: AuthError) -> JSONResponse:
        return JSONResponse({"error": error.code}, status_code=error.status)

    # Event collection failures carry a fixed public code; 503 responses invite a retry.
    @application.exception_handler(CollectionError)
    async def collection_error(request: Request, error: CollectionError) -> JSONResponse:
        headers = {"Retry-After": "1"} if error.status == 503 else None
        return JSONResponse({"error": error.code}, status_code=error.status, headers=headers)

    # Tenant policy denials share one response so callers cannot probe resource existence.
    @application.exception_handler(AccessDenied)
    async def access_error(request: Request, error: AccessDenied) -> JSONResponse:
        return JSONResponse({"error": "access_denied"}, status_code=403)

    # Allowed requests that would break membership invariants, such as removing a last Owner.
    @application.exception_handler(MembershipConflict)
    async def conflict_error(request: Request, error: MembershipConflict) -> JSONResponse:
        return JSONResponse({"error": "state_conflict"}, status_code=409)

    # Persistent throttles report only the wait time in the standard Retry-After header.
    @application.exception_handler(RateLimited)
    async def rate_error(request: Request, error: RateLimited) -> JSONResponse:
        return JSONResponse(
            {"error": "rate_limited"},
            status_code=429,
            headers={"Retry-After": str(error.retry_after)},
        )

    # Request and domain validation failures return one generic code.
    @application.exception_handler(RequestValidationError)
    @application.exception_handler(ValueError)
    async def validation_error(request: Request, error: Exception) -> JSONResponse:
        # Never echo input/context: those can contain passwords, tokens, or private identifiers.
        return JSONResponse({"error": "validation_failed"}, status_code=422)

    # Database constraint violations, such as concurrent duplicates, map to a state conflict.
    @application.exception_handler(IntegrityError)
    async def integrity_error(request: Request, error: IntegrityError) -> JSONResponse:
        return JSONResponse({"error": "state_conflict"}, status_code=409)

    # Other database failures, including lock timeouts, are logged by event name only and
    # reported as temporary with a short Retry-After.
    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.error("database_operation_failed")
        return JSONResponse(
            {"error": "temporarily_unavailable"}, status_code=503, headers={"Retry-After": "1"}
        )

    application.include_router(auth_router)
    application.include_router(google_router)
    application.include_router(tenancy_router)
    application.include_router(collection_router)
    application.include_router(collection_public_router)
    application.include_router(collection_webhook_router)

    # Liveness: answers while the process runs, even when PostgreSQL is unavailable.
    @application.get("/health/live", response_model=HealthResponse, tags=["Health"])
    def liveness(response: Response) -> HealthResponse:
        """Report process availability independently of database availability."""
        response.headers["Cache-Control"] = "no-store"
        return HealthResponse(status="ok")

    # Readiness: 200 only with database access at the expected revision; otherwise 503 and a
    # logged sanitized reason. A failed probe does not stop the process or change the schema.
    @application.get(
        "/health/ready",
        response_model=ReadinessResponse,
        responses={503: {"model": ReadinessResponse, "description": "Dependency not ready"}},
        tags=["Health"],
    )
    def readiness(request: Request, response: Response) -> ReadinessResponse:
        """Require PostgreSQL access and the exact migration revision for this build."""
        response.headers["Cache-Control"] = "no-store"
        failure = readiness_failure(request.app.state.engine, request.app.state.expected_revision)
        if failure is not None:
            logger.warning("readiness_failed", extra={"reason": failure})
            response.status_code = 503
            return ReadinessResponse(status="not_ready")
        return ReadinessResponse(status="ready")

    return application
