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

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import func, select

from app.api.collection import PublicKey, _browser_source, _limit, _public_body
from app.api.dependencies import BrowserDep, IngestDep, RawBody, ReaderDep, SessionDep
from app.identity.normalize import IdentifierRejected, canonical, check_method
from app.models import AgencyMembership, IdentitySubject
from app.services.access import resolve_scope
from app.services.collection import lock_client, require_live_source
from app.services.identity import (
    AssertedIdentifier,
    AssertionRequest,
    issue_handoff,
    person_group,
    process_assertion,
)
from app.services.identity_admin import (
    IdentityAdmin,
    Reader,
    leads,
    list_people,
    profile,
    timeline,
)
from app.services.revenue_identity import person_revenue
from app.services.tenancy import MANAGERS, AccessDenied

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


# ---------------------------------------------------------------------------------------------
# Person-level reads (identity:read) and Owner/Admin administration (design 9, 10 and 12.2).


class MergeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    survivor_id: UUID
    merged_id: UUID
    survivor_version: Annotated[int, Field(ge=1)]
    merged_version: Annotated[int, Field(ge=1)]
    reason_code: Literal["same_person_confirmed_by_client", "duplicate_account", "data_correction"]


class ReversalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    survivor_version: Annotated[int, Field(ge=1)]
    merged_version: Annotated[int, Field(ge=1)]
    reason_code: Literal["same_person_confirmed_by_client", "duplicate_account", "data_correction"]


class ErasureIdentifier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["email", "phone", "customer_ref"]
    value: Annotated[str, Field(min_length=1, max_length=320)]


class PersonErasureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: UUID | None = None
    identifier: ErasureIdentifier | None = None
    objected: bool = False


class ErasureResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_id: UUID | None = None
    unresolved_events: Literal["erase", "retain"] | None = None


class PersonErasureResponse(BaseModel):
    id: UUID
    status: str
    objected: bool
    received_at: datetime
    completed_at: datetime | None
    target_outcomes: dict[str, str]


def _reader(session, principal, agency_id: UUID, client_id: UUID) -> Reader:
    resolve_scope(session, principal, agency_id, client_id, "identity:read")
    try:
        resolve_scope(session, principal, agency_id, client_id, "finance:read")
        finance = True
    except AccessDenied:
        finance = False
    manager = False
    if principal.kind == "user":
        role = session.scalar(
            select(AgencyMembership.role).where(
                AgencyMembership.agency_id == agency_id,
                AgencyMembership.user_id == principal.identifier,
                AgencyMembership.status == "active",
            )
        )
        manager = role in MANAGERS
    return Reader(agency_id, client_id, finance, manager)


def _release(
    session, principal, agency_id: UUID, client_id: UUID, body: dict, *, finance: bool = False
) -> JSONResponse:
    # Recheck current scope immediately before releasing person-level data (D-075, JV03). A
    # body built with finance access carries financial-derived customer status, so that access
    # is rechecked too (R0607-14).
    resolve_scope(session, principal, agency_id, client_id, "identity:read")
    if finance:
        resolve_scope(session, principal, agency_id, client_id, "finance:read")
    return JSONResponse(jsonable_encoder(body), headers={"Cache-Control": "no-store"})


def _clock(session) -> datetime:
    return session.scalar(select(func.clock_timestamp()))


IDENTITY = "/agencies/{agency_id}/clients/{client_id}/identity"


@router.get(IDENTITY + "/subjects")
def list_identity_subjects(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    stage: Literal["unlinked", "known", "lead", "customer"] | None = None,
    updated_since: datetime | None = None,
    after: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> JSONResponse:
    reader = _reader(session, principal, agency_id, client_id)
    body = list_people(
        session,
        reader,
        _clock(session),
        stage=stage,
        updated_since=updated_since,
        after=after,
        limit=limit,
    )
    return _release(session, principal, agency_id, client_id, body, finance=reader.finance)


@router.get(IDENTITY + "/subjects/{subject_id}")
def read_identity_subject(
    agency_id: UUID, client_id: UUID, subject_id: UUID, session: SessionDep, principal: ReaderDep
) -> JSONResponse:
    reader = _reader(session, principal, agency_id, client_id)
    body = profile(session, reader, subject_id, _clock(session))
    return _release(session, principal, agency_id, client_id, body, finance=reader.finance)


@router.get(IDENTITY + "/subjects/{subject_id}/timeline")
def read_identity_timeline(
    agency_id: UUID,
    client_id: UUID,
    subject_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    after: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> JSONResponse:
    reader = _reader(session, principal, agency_id, client_id)
    body = timeline(session, reader, subject_id, _clock(session), after=after, limit=limit)
    return _release(session, principal, agency_id, client_id, body, finance=reader.finance)


# Verified sales currently associated with a person: identity:read and finance:read both, with
# consent, ownership and the published ledger rechecked before release (007-C, J4).
@router.get(IDENTITY + "/subjects/{subject_id}/revenue")
def read_identity_revenue(
    agency_id: UUID, client_id: UUID, subject_id: UUID, session: SessionDep, principal: ReaderDep
) -> JSONResponse:
    resolve_scope(session, principal, agency_id, client_id, "identity:read")
    resolve_scope(session, principal, agency_id, client_id, "finance:read")
    if (
        session.scalar(
            select(IdentitySubject.id).where(
                IdentitySubject.client_id == client_id, IdentitySubject.id == subject_id
            )
        )
        is None
    ):
        raise AccessDenied()
    group = person_group(session, client_id, subject_id)
    body = person_revenue(session, agency_id, client_id, group, _clock(session))
    resolve_scope(session, principal, agency_id, client_id, "finance:read")
    return _release(session, principal, agency_id, client_id, body)


@router.get(IDENTITY + "/leads")
def read_identity_leads(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    identified: bool | None = None,
    trust: Literal["browser", "trusted_sender"] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    after: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> JSONResponse:
    reader = _reader(session, principal, agency_id, client_id)
    body = leads(
        session,
        reader,
        _clock(session),
        identified=identified,
        trust=trust,
        start=start,
        end=end,
        after=after,
        limit=limit,
    )
    return _release(session, principal, agency_id, client_id, body, finance=reader.finance)


def _admin(request: Request, session, browser) -> IdentityAdmin:
    return IdentityAdmin(session, browser.user.id, request.app.state.settings)


@router.get(IDENTITY + "/review")
def read_identity_review(
    agency_id: UUID, client_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> JSONResponse:
    body = _admin(request, session, browser).review(agency_id, client_id)
    return JSONResponse(jsonable_encoder(body), headers={"Cache-Control": "no-store"})


@router.post(IDENTITY + "/merges", status_code=201)
def create_identity_merge(
    agency_id: UUID,
    client_id: UUID,
    data: MergeInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = _admin(request, session, browser).merge(
        agency_id, client_id, **data.model_dump()
    )
    return JSONResponse(result, status)


@router.post(IDENTITY + "/merges/{merge_id}/reversal", status_code=201)
def reverse_identity_merge(
    agency_id: UUID,
    client_id: UUID,
    merge_id: UUID,
    data: ReversalInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> JSONResponse:
    result, status = _admin(request, session, browser).reverse(
        agency_id, client_id, merge_id, **data.model_dump()
    )
    return JSONResponse(result, status)


@router.post(IDENTITY + "/erasures", status_code=201, response_model=PersonErasureResponse)
def erase_identity_subject(
    agency_id: UUID,
    client_id: UUID,
    data: PersonErasureInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> PersonErasureResponse:
    identifier = (data.identifier.kind, data.identifier.value) if data.identifier else None
    item = _admin(request, session, browser).erase(
        agency_id,
        client_id,
        subject_id=data.subject_id,
        identifier=identifier,
        objected=data.objected,
    )
    return PersonErasureResponse.model_validate(item, from_attributes=True)


@router.post(IDENTITY + "/erasures/{request_id}/resolution", response_model=PersonErasureResponse)
def resolve_identity_erasure(
    agency_id: UUID,
    client_id: UUID,
    request_id: UUID,
    data: ErasureResolutionInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> PersonErasureResponse:
    item = _admin(request, session, browser).resolve(
        agency_id,
        client_id,
        request_id,
        subject_id=data.subject_id,
        unresolved_events=data.unresolved_events,
    )
    return PersonErasureResponse.model_validate(item, from_attributes=True)
