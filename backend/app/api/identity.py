"""Identity handoff and trusted assertion routes (specification 006, D-075; design 12.2).

The public handoff route derives its client from the browser source's public key, requires an
exact registered Origin and answers every refusal with the same `unavailable` body. The
assertion route authenticates a client-granted ingest key; its responses disclose only the
sender's own request (syntax, freshness, proof and idempotency) and never whether an
identifier had an owner, was contested, erased or objected to. Neither route echoes a value,
token, code or challenge.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.api.collection import PublicKey, _browser_source, _limit, _public_body
from app.api.dependencies import IngestDep, RawBody, SessionDep
from app.identity.normalize import IdentifierRejected, canonical, check_method
from app.services.access import resolve_scope
from app.services.collection import lock_client, require_live_source
from app.services.identity import (
    AssertedIdentifier,
    AssertionRequest,
    issue_handoff,
    process_assertion,
)

router = APIRouter(tags=["Identity"])
Challenge = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{22,128}$")]
SubjectToken = Annotated[str, Field(min_length=8, max_length=128)]


class HandoffInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_token: SubjectToken
    challenge: Challenge


class HandoffResponse(BaseModel):
    status: Literal["issued", "unavailable"]
    code: str | None = None
    expires_at: datetime | None = None


class IdentifierInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["email", "phone", "customer_ref"]
    value: Annotated[str, Field(min_length=1, max_length=320)]
    method: Annotated[str, Field(min_length=1, max_length=32)]
    verified_at: datetime


class AssertionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assertion_id: UUID
    handoff: Annotated[str | None, Field(min_length=8, max_length=128)] = None
    challenge: Challenge | None = None
    subject_token: SubjectToken | None = None
    identity_consent_receipt_id: UUID | None = None
    identifiers: Annotated[list[IdentifierInput], Field(min_length=1, max_length=3)]

    @model_validator(mode="after")
    def one_proof(self) -> "AssertionInput":
        handoff = self.handoff is not None and self.challenge is not None
        direct = self.subject_token is not None and self.identity_consent_receipt_id is not None
        partial = (self.handoff is None) != (self.challenge is None) or (
            self.subject_token is None
        ) != (self.identity_consent_receipt_id is None)
        if handoff == direct or partial:
            raise ValueError("exactly one proof form")
        if len({item.kind for item in self.identifiers}) != len(self.identifiers):
            raise ValueError("one identifier per kind")
        if any(item.verified_at.tzinfo is None for item in self.identifiers):
            raise ValueError("verified_at needs a time zone")
        return self


class AssertionResponse(BaseModel):
    status: Literal["accepted", "duplicate", "conflict", "rejected"]
    assertion_id: UUID | None = None
    reason: str | None = None


def _inline_schema(model: type[BaseModel]) -> dict:
    """A request-body schema without $defs references (the routes read the raw body)."""
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def resolve(value):
        if isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None:
                return resolve(definitions[reference.rsplit("/", 1)[-1]])
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    return resolve(schema)


def _body(model: type[BaseModel], *media: str) -> dict:
    schema = _inline_schema(model)
    return {
        "requestBody": {"required": True, "content": {item: {"schema": schema} for item in media}}
    }


def _rejected(reason: str) -> JSONResponse:
    return JSONResponse({"status": "rejected", "reason": reason}, 422)


# Issue a one-time handoff code to the holder of a browser subject token (D3).
@router.post(
    "/collect/v1/{public_key}/identity-handoff",
    tags=["Public collection"],
    response_model=HandoffResponse,
    status_code=201,
    responses={200: {"model": HandoffResponse, "description": "Unavailable, for every refusal."}},
    openapi_extra=_body(HandoffInput, "application/json", "text/plain"),
)
def identity_handoff(
    public_key: PublicKey,
    request: Request,
    session: SessionDep,
    body: RawBody,
) -> JSONResponse:
    source = _browser_source(request, session, public_key, bucket="consent-state")
    headers = {"Cache-Control": "no-store"}
    try:
        data = _public_body(request, body, HandoffInput)
    except ValidationError:
        return JSONResponse({"status": "unavailable"}, 200, headers=headers)
    settings = request.app.state.settings
    # Per-subject limit; the bucket key is a keyed digest of the token (app.services.auth).
    _limit(request, "identity-handoff", data.subject_token, settings.consent_state_per_minute)

    def lock() -> datetime:
        now = lock_client(session, source.client_id)
        require_live_source(session, "browser", source.id)
        return now

    issued = issue_handoff(
        session,
        source.agency_id,
        source.client_id,
        subject_token=data.subject_token,
        challenge=data.challenge,
        lock=lock,
    )
    if issued is None:
        return JSONResponse({"status": "unavailable"}, 200, headers=headers)
    code, expires_at = issued
    return JSONResponse(
        {"status": "issued", "code": code, "expires_at": expires_at.isoformat()},
        201,
        headers=headers,
    )


# Trusted identity assertion with a client-granted ingest key (design section 12.2).
@router.post(
    "/agencies/{agency_id}/clients/{client_id}/identity-assertions",
    response_model=AssertionResponse,
    status_code=201,
    responses={
        200: {"model": AssertionResponse, "description": "Duplicate within the retry window."},
        409: {"model": AssertionResponse, "description": "Changed request, same assertion ID."},
        422: {"model": AssertionResponse, "description": "Rejected request or proof."},
    },
    openapi_extra=_body(AssertionInput, "application/json"),
)
def identity_assertion(
    agency_id: UUID,
    client_id: UUID,
    request: Request,
    session: SessionDep,
    principal: IngestDep,
    body: RawBody,
) -> JSONResponse:
    settings = request.app.state.settings
    _limit(request, "ingest-key", str(principal.identifier), settings.ingest_trusted_per_minute)
    resolve_scope(session, principal, agency_id, client_id, "events:write")
    try:
        data = AssertionInput.model_validate_json(body)
    except ValidationError:
        return _rejected("request_invalid")
    try:
        identifiers = []
        for item in data.identifiers:
            value = canonical(item.kind, item.value)
            check_method(item.kind, item.method)
            identifiers.append(AssertedIdentifier(value, item.method, item.verified_at))
    except IdentifierRejected as rejection:
        return _rejected(rejection.reason)
    assertion = AssertionRequest(
        data.assertion_id,
        tuple(identifiers),
        handoff=data.handoff,
        challenge=data.challenge,
        subject_token=data.subject_token,
        identity_consent_receipt_id=data.identity_consent_receipt_id,
    )

    def lock() -> datetime:
        now = lock_client(session, client_id)
        resolve_scope(session, principal, agency_id, client_id, "events:write")
        return now

    result = process_assertion(
        session, settings, agency_id, client_id, principal.identifier, assertion, lock=lock
    )
    if result.status == "rejected":
        return _rejected(result.reason or "proof_invalid")
    return JSONResponse(
        {"status": result.status, "assertion_id": str(data.assertion_id)}, result.http
    )
