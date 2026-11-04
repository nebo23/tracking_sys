"""Explicit request/response allowlists prevent credential material from escaping."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.security import normalize_email
from app.services.tenancy import Role

# Reusable annotated field types. Name requires 1-200 characters with at least one visible
# character. Password enforces the 15-128 character policy for new passwords. Token bounds
# opaque one-time tokens. SecretStr masks password/token values in reprs and logs.
Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Password = Annotated[SecretStr, Field(min_length=15, max_length=128)]
Token = Annotated[SecretStr, Field(min_length=32, max_length=128)]


# Base for request bodies: extra="forbid" rejects unexpected fields, and hide_input_in_errors
# keeps submitted values out of textual validation errors. It does not replace the
# application's sanitized validation handler, which returns only a generic error code.
class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


# Base for responses: from_attributes reads ORM object attributes, and only the declared
# fields are serialized, so hashes, digests, and encrypted payloads cannot leak by accident.
class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Documented shape of every sanitized error body: a stable machine-readable code only.
class ErrorResponse(Output):
    error: str


# Generic acknowledgement for registration and recovery requests; it is identical whether or
# not an eligible account exists, which limits account enumeration.
class Acknowledgement(Output):
    message: str = "If eligible, a message has been queued."


# Request body carrying an email address, normalized by the shared account email policy.
class EmailInput(Input):
    email: str = Field(min_length=3, max_length=320)

    # Field validator run by Pydantic during parsing; invalid syntax raises ValueError.
    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        return normalize_email(value)


# Registration input: inherits the normalized email and adds display name and new password.
class Registration(EmailInput):
    display_name: Name
    password: Password


# Login input: accepts any submitted password up to 128 characters. The new-password length
# policy is not reapplied here; Argon2 verification decides.
class Login(EmailInput):
    password: SecretStr = Field(min_length=1, max_length=128)


# Body for consuming one-time verification, reset, or invitation tokens; tokens are never
# accepted in backend URL query parameters.
class TokenInput(Input):
    token: Token


# Reset input: the inherited one-time token plus the new password.
class PasswordReset(TokenInput):
    password: Password


# Authenticated password change: current password for re-verification and a new password.
class PasswordChange(Input):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: Password


# Public identity projection. Only verified users can hold sessions, so the timestamp is set.
class UserResponse(Output):
    id: UUID
    email_normalized: str
    display_name: str
    email_verified_at: datetime


# Login and /auth/me response; the session token itself stays in the HttpOnly cookie.
class SessionResponse(Output):
    user: UserResponse
    csrf_token: str


# Name-only body used to create or rename agencies and to create client workspaces.
class AgencyInput(Input):
    name: Name


# Agency profile projection; ClientResponse reuses these fields.
class AgencyResponse(Output):
    id: UUID
    name: str
    status: str
    created_at: datetime


# Membership summary for the agency list: agency identifier and the caller's role only.
class AgencyAccess(Output):
    agency_id: UUID
    role: Role


# Partial client update; the route rejects a body with neither field.
class ClientUpdate(Input):
    name: Name | None = None
    status: Literal["active", "archived"] | None = None


# Client workspace projection: agency profile fields plus the owning agency identifier.
class ClientResponse(AgencyResponse):
    agency_id: UUID


# Membership projection without user email or other private profile data.
class MembershipResponse(Output):
    id: UUID
    agency_id: UUID
    user_id: UUID
    role: Role
    status: str


# Partial membership update; the route rejects a body with neither field.
class MembershipUpdate(Input):
    role: Role | None = None
    status: Literal["active", "disabled"] | None = None


# Client grant options; financial visibility is false unless explicitly requested.
class FinancialGrant(Input):
    can_view_financials: bool = False


# One client grant entry used by invitations and service keys.
class ClientGrantInput(FinancialGrant):
    client_id: UUID


# Invitation request: normalized recipient email, role, and up to 100 explicit client grants.
class InvitationInput(EmailInput):
    role: Role
    clients: list[ClientGrantInput] = Field(default_factory=list, max_length=100)


# Invitation projection for managers; the token digest is never included.
class InvitationResponse(Output):
    id: UUID
    agency_id: UUID
    email_normalized: str
    role: Role
    status: str
    created_at: datetime
    expires_at: datetime


# Service key request: name, at least one client grant, and a 1-90 day lifetime.
class ServiceKeyInput(Input):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    clients: list[ClientGrantInput] = Field(min_length=1, max_length=100)
    expires_in_days: int = Field(default=90, ge=1, le=90)


# Service key metadata projection without the stored key digest.
class ServiceKeyResponse(Output):
    id: UUID
    agency_id: UUID
    name: str
    status: str
    created_at: datetime
    expires_at: datetime


# Issuance response; the only place the raw key is ever returned, once, at creation.
class IssuedServiceKey(Output):
    credential: ServiceKeyResponse
    key: str


# Audit event projection: identifiers and action codes only, without payload data.
class AuditResponse(Output):
    id: UUID
    agency_id: UUID
    client_id: UUID | None
    actor_user_id: UUID
    action: str
    resource_type: str
    resource_id: UUID
    occurred_at: datetime
