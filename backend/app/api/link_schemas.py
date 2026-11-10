"""Request and response allowlists of the managed-link routes (specification 005, D-033)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from app.api.schemas import Input, Output

Label = Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
Code = Annotated[str, Field(min_length=1, max_length=64)]
UtmValues = Annotated[dict[str, Code], Field(max_length=6)]


class CampaignInput(Input):
    public_code: Code
    label: Label


class CampaignUpdate(Input):
    label: Label | None = None
    status: Literal["active", "archived"] | None = None


class CampaignResponse(Output):
    id: UUID
    client_id: UUID
    public_code: str
    label: str
    status: str
    created_at: datetime
    updated_at: datetime


class ContentInput(Input):
    external_code: Annotated[str, Field(min_length=1, max_length=128)]
    platform_label: Annotated[str, Field(min_length=1, max_length=64, pattern=r"\S")] | None = None


class ContentUpdate(Input):
    platform_label: Annotated[str, Field(min_length=1, max_length=64, pattern=r"\S")] | None = None
    status: Literal["active", "archived"] | None = None


class ContentResponse(Output):
    id: UUID
    client_id: UUID
    external_code: str
    platform_label: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class TemplateInput(Input):
    name: Label
    parameters: UtmValues


class TemplateUpdate(Input):
    parameters: UtmValues | None = None
    status: Literal["active", "archived"] | None = None


class TemplateResponse(Output):
    id: UUID
    client_id: UUID
    name: str
    parameters: dict[str, str]
    revision: int
    status: str
    created_at: datetime
    updated_at: datetime


class OriginInput(Input):
    origin: Annotated[str, Field(min_length=1, max_length=200)]
    query_names: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=20
    )


class OriginUpdate(Input):
    query_names: list[Annotated[str, Field(min_length=1, max_length=64)]] | None = Field(
        default=None, max_length=20
    )
    status: Literal["active", "disabled"] | None = None


class OriginResponse(Output):
    id: UUID
    client_id: UUID
    origin: str
    query_names: list[str]
    status: str
    created_at: datetime
    updated_at: datetime


class DomainInput(Input):
    hostname: Annotated[str, Field(min_length=1, max_length=253)]


class DomainUpdate(Input):
    status: Literal["disabled"]


# Domain state without challenge material; failure_code is a closed reason code.
class DomainResponse(Output):
    id: UUID
    client_id: UUID
    hostname: str
    status: str
    challenge_generation: int
    challenge_expires_at: datetime | None
    verified_at: datetime | None
    verification_expires_at: datetime | None
    certificate_expires_at: datetime | None
    last_checked_at: datetime | None
    failure_code: str | None
    version: int
    created_at: datetime


# The only response that carries a raw ownership challenge, returned once at issuance.
class ChallengeResponse(Output):
    domain: DomainResponse
    record_type: Literal["TXT"] = "TXT"
    record_name: str
    record_value: str
    expires_at: datetime
    cname_target: str | None


# Outcome of one domain check: verified, failed (see domain.failure_code), or stale (the
# domain changed during the check, so the result was discarded).
class VerificationResponse(Output):
    outcome: Literal["verified", "failed", "stale"]
    domain: DomainResponse


class LinkInput(Input):
    slug: Annotated[str, Field(min_length=3, max_length=64)]
    destination: Annotated[str, Field(min_length=1, max_length=2048)]
    domain_id: UUID | None = None
    utm: UtmValues | None = None
    template_id: UUID | None = None
    campaign_id: UUID | None = None
    content_reference_id: UUID | None = None
    expires_at: AwareDatetime | None = None


# An explicit null expires_at removes the expiry.
class LinkUpdate(Input):
    status: Literal["active", "disabled"] | None = None
    expires_at: AwareDatetime | None = None


class LinkResponse(Output):
    id: UUID
    client_id: UUID
    domain_id: UUID | None
    slug: str
    destination: str
    utm: dict[str, str]
    target_url: str
    campaign_id: UUID | None
    content_reference_id: UUID | None
    template_id: UUID | None
    template_revision: int | None
    status: str
    expires_at: datetime | None
    created_at: datetime
