"""Request and response allowlists of the event collection routes (specification 004)."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.api.schemas import Input, Output
from app.collection.contract import FormDefinition, SubjectToken

PurposeCode = Literal[
    "analytics.first_party",
    "attribution",
    "identity_link",
    "ads.measurement",
    "ads.personalization",
    "sale_or_share",
]
Choice = Literal["granted", "denied", "withdrawn"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Origin = Annotated[str, Field(min_length=1, max_length=200)]


# Explicit consent choices. Without subject_token, a request that grants a purpose creates the
# subject and returns its token once. notice_sha256 is required from trusted API senders and
# rejected on the public route, where the source's registered notice digest is used.
class ConsentInput(Input):
    subject_token: SubjectToken | None = None
    choices: dict[PurposeCode, Choice] = Field(min_length=1, max_length=6)
    captured_at: AwareDatetime | None = None
    notice_sha256: Digest | None = None


class ConsentResponse(Output):
    subject_token: str | None
    receipts: list[UUID]
    states: dict[str, str]


class ErasureInput(Input):
    subject_token: SubjectToken


# Non-mutating consent-state read (specification 005); the token travels only in the body.
class ConsentStateInput(Input):
    subject_token: SubjectToken


# Current per-purpose states, the expiry of each granted purpose, and the server time.
# "unknown" covers missing and erased subjects alike; every state is then "unknown".
class ConsentStateResponse(Output):
    status: Literal["active", "unknown"]
    states: dict[str, str]
    expires_at: dict[str, datetime]
    server_time: datetime


# Generic public acknowledgement; identical for every accepted or discarded submission.
class Received(Output):
    status: Literal["received"] = "received"


class EventResult(Output):
    status: Literal["accepted", "duplicate", "upgraded"]
    revision: int


class SourceInput(Input):
    kind: Literal["browser", "webhook"]
    name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
    allowed_origins: list[Origin] | None = Field(default=None, min_length=1, max_length=10)
    notice_sha256: Digest | None = None


class SourceUpdate(Input):
    name: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")] | None = None
    status: Literal["active", "disabled"] | None = None
    allowed_origins: list[Origin] | None = Field(default=None, min_length=1, max_length=10)
    notice_sha256: Digest | None = None


class SourceResponse(Output):
    id: UUID
    agency_id: UUID
    client_id: UUID
    kind: str
    name: str
    status: str
    public_key: str | None
    allowed_origins: list[str] | None
    notice_sha256: str | None
    created_at: datetime


# Creation and rotation responses; the only place a webhook signing secret is returned, once.
class IssuedSource(Output):
    source: SourceResponse
    signing_secret: str | None = None


class IssuedSecret(Output):
    signing_secret: str


class FormResponse(Output):
    id: UUID
    form_key: str
    version: int
    status: str
    fields: FormDefinition
    updated_at: datetime


class ErasureRequestInput(Input):
    subject_token: SubjectToken | None = None
    event_id: UUID | None = None
    objected: bool = False


class ErasureRequestResponse(Output):
    id: UUID
    requester_kind: str
    status: str
    objected: bool
    received_at: datetime
    completed_at: datetime | None
    target_outcomes: dict[str, str]


class DiagnosticResponse(Output):
    day: date
    channel: str
    outcome: str
    reason: str
    count: int


# Metadata of one accepted event; never its payload, subject, or fingerprint.
class EventMetadata(Output):
    event_id: UUID
    event_type: str
    channel: str
    trust_rank: int
    revision: int
    occurred_at: datetime
    first_received_at: datetime
    last_received_at: datetime
    traffic_label: str
    conflict_count: int
