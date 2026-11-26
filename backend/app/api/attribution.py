"""Attribution model, status and run routes (specification 008-B, D-079 decision D10).

Below /agencies/{agency_id}/clients/{client_id}/attribution:
- GET /models needs client:read and is open to read service keys with the client's grant.
- POST /models, /models/{version_id}/default and /models/{version_id}/retire are for an
  Owner or Admin with a browser session, idempotent by operation ID and audited.

Aggregated credit reports belong to 016-B. Refusals carry a closed code only.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import Field

from app.api.dependencies import BrowserDep, ReaderDep, SessionDep
from app.api.schemas import Input, Output
from app.services.access import resolve_scope
from app.services.attribution_models import ModelAdmin, listing

router = APIRouter(tags=["Attribution"])
BASE = "/agencies/{agency_id}/clients/{client_id}/attribution"


class ModelVersionView(Output):
    id: UUID
    version_key: str
    model: Literal["first_click", "last_click", "linear"]
    window_days: int
    rules: str
    is_default: bool
    status: Literal["active", "retired"]
    created_at: datetime
    retired_at: datetime | None


class ModelVersionList(Output):
    versions: list[ModelVersionView]
    default_version_id: UUID | None
    active_limit: int


class ModelVersionInput(Input):
    operation_id: UUID
    model: Literal["first_click", "last_click", "linear"]
    # Validated by the service, so an out-of-range window answers the closed invalid_window.
    window_days: Annotated[int, Field(strict=True)]


class ModelOperationInput(Input):
    operation_id: UUID


@router.get(f"{BASE}/models", response_model=ModelVersionList)
def list_attribution_models(
    agency_id: UUID, client_id: UUID, session: SessionDep, principal: ReaderDep
) -> JSONResponse:
    resolve_scope(session, principal, agency_id, client_id)
    return JSONResponse(listing(session, agency_id, client_id))


@router.post(f"{BASE}/models", status_code=201, response_model=ModelVersionView)
def create_attribution_model(
    agency_id: UUID,
    client_id: UUID,
    data: ModelVersionInput,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = ModelAdmin(session, browser.user.id).create(
        agency_id, client_id, **data.model_dump()
    )
    return JSONResponse(result, status)


@router.post(
    f"{BASE}/models/{{version_id}}/default", status_code=201, response_model=ModelVersionView
)
def set_default_attribution_model(
    agency_id: UUID,
    client_id: UUID,
    version_id: UUID,
    data: ModelOperationInput,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = ModelAdmin(session, browser.user.id).set_default(
        agency_id, client_id, version_id, operation_id=data.operation_id
    )
    return JSONResponse(result, status)


@router.post(
    f"{BASE}/models/{{version_id}}/retire", status_code=201, response_model=ModelVersionView
)
def retire_attribution_model(
    agency_id: UUID,
    client_id: UUID,
    version_id: UUID,
    data: ModelOperationInput,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = ModelAdmin(session, browser.user.id).retire(
        agency_id, client_id, version_id, operation_id=data.operation_id
    )
    return JSONResponse(result, status)
