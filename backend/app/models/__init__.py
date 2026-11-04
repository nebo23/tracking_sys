"""Approved SQLAlchemy metadata for specification 002-A."""

# Importing this package registers every mapped table in Base.metadata, which Alembic's env.py
# and the readiness/model-agreement checks rely on. It covers the 002-A tenancy models and the
# later approved 002-B/C/D authentication and access models, plus the D-022 identity and
# verification models.
from app.models.access import (
    AgencyInvitation,
    InvitationClientGrant,
    ServiceClientGrant,
    ServiceCredential,
)
from app.models.auth import (
    AuthRateLimit,
    AuthSession,
    AuthToken,
    ExternalIdentity,
    MailOutbox,
    OAuthTransaction,
    PasswordCredential,
    SecurityEvent,
    VerificationChallenge,
)
from app.models.tenancy import (
    Agency,
    AgencyMembership,
    AuditEvent,
    ClientGrant,
    ClientWorkspace,
    User,
)

__all__ = [
    "Agency",
    "AgencyMembership",
    "AuditEvent",
    "ClientGrant",
    "ClientWorkspace",
    "User",
    "AuthRateLimit",
    "AuthSession",
    "AuthToken",
    "ExternalIdentity",
    "MailOutbox",
    "OAuthTransaction",
    "PasswordCredential",
    "SecurityEvent",
    "VerificationChallenge",
    "AgencyInvitation",
    "InvitationClientGrant",
    "ServiceClientGrant",
    "ServiceCredential",
]
