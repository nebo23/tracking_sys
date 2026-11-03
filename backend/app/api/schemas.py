"""Explicit request/response allowlists prevent credential material from escaping."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.security import normalize_email
from app.services.tenancy import Role

Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Password = Annotated[SecretStr, Field(min_length=15, max_length=128)]
Token = Annotated[SecretStr, Field(min_length=32, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(Output):
    error: str


class Acknowledgement(Output):
    message: str = "If eligible, a message has been queued."


class EmailInput(Input):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        return normalize_email(value)


class Registration(EmailInput):
    display_name: Name
    password: Password


class Login(EmailInput):
    password: SecretStr = Field(min_length=1, max_length=128)


class TokenInput(Input):
    token: Token


class PasswordReset(TokenInput):
    password: Password


class PasswordChange(Input):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: Password


class UserResponse(Output):
    id: UUID
    email_normalized: str
    display_name: str
    email_verified_at: datetime


class SessionResponse(Output):
    user: UserResponse
    csrf_token: str


class AgencyInput(Input):
    name: Name


class AgencyResponse(Output):
    id: UUID
    name: str
    status: str
    created_at: datetime


class AgencyAccess(Output):
    agency_id: UUID
    role: Role


class ClientUpdate(Input):
    name: Name | None = None
    status: Literal["active", "archived"] | None = None


class ClientResponse(AgencyResponse):
    agency_id: UUID


class MembershipResponse(Output):
    id: UUID
    agency_id: UUID
    user_id: UUID
    role: Role
    status: str


class MembershipUpdate(Input):
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None


class FinancialGrant(Input):
    can_view_financials: bool = False


class ClientGrantInput(FinancialGrant):
    client_id: UUID


class InvitationInput(EmailInput):
    role: Role
    clients: list[ClientGrantInput] = Field(default_factory=list, max_length=100)


class InvitationResponse(Output):
    id: UUID
    agency_id: UUID
    email_normalized: str
    role: Role
    status: str
    created_at: datetime
    expires_at: datetime


class ServiceKeyInput(Input):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    clients: list[ClientGrantInput] = Field(min_length=1, max_length=100)
    expires_in_days: int = Field(default=90, ge=1, le=90)


class ServiceKeyResponse(Output):
    id: UUID
    agency_id: UUID
    name: str
    status: str
    created_at: datetime
    expires_at: datetime


class IssuedServiceKey(Output):
    credential: ServiceKeyResponse
    key: str


class AuditResponse(Output):
    id: UUID
    agency_id: UUID
    client_id: UUID | None
    actor_user_id: UUID
    action: str
    resource_type: str
    resource_id: UUID
    occurred_at: datetime
