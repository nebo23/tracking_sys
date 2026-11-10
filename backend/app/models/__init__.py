"""Approved SQLAlchemy metadata for specifications 002 to 004."""

# Importing this package registers every mapped table in Base.metadata, which Alembic's env.py
# and the readiness/model-agreement checks rely on. It covers the 002-A tenancy models, the
# approved 002-B/C/D authentication and access models, the D-022 identity and verification
# models, and the D-027 event collection models.
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
from app.models.collection import (
    CollectedEvent,
    CollectionForm,
    CollectionSubject,
    EventDiagnostic,
    IngestionSource,
    IngestionSourceSecret,
    StoredConsentRecord,
    StoredTombstone,
    SubjectDeletionRequest,
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
    "CollectedEvent",
    "CollectionForm",
    "CollectionSubject",
    "EventDiagnostic",
    "IngestionSource",
    "IngestionSourceSecret",
    "StoredConsentRecord",
    "StoredTombstone",
    "SubjectDeletionRequest",
]
