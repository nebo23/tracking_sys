"""Approved SQLAlchemy metadata for specifications 002 to 005 and 009-A."""

# Importing this package registers every mapped table in Base.metadata, which Alembic's env.py
# and the readiness/model-agreement checks rely on. It covers the 002-A tenancy models, the
# approved 002-B/C/D authentication and access models, the D-022 identity and verification
# models, the D-027 event collection models, the D-033 managed-link models, the D-048
# connector lifecycle models, the D-064 advertising models, and the D-067 revenue and
# payment models.
from app.models.access import (
    AgencyInvitation,
    InvitationClientGrant,
    ServiceClientGrant,
    ServiceCredential,
)
from app.models.advertising import AdAccount, AdObject, AdSpendFact
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
from app.models.connectors import (
    ConnectorCheckpoint,
    ConnectorConnection,
    ConnectorDeletionRequest,
    ConnectorOAuthTransaction,
    ConnectorRecord,
    ConnectorSyncRun,
    ConnectorTokenSecret,
    ConnectorUsageRecord,
    ConnectorWebhookDelivery,
)
from app.models.crm import CrmDeal, CrmStageRule
from app.models.delivery import (
    ConversionAcknowledgement,
    ConversionDelivery,
    ConversionDestination,
)
from app.models.identity import (
    IdentityAssertion,
    IdentityAssertionReceipt,
    IdentityChange,
    IdentityErasureHold,
    IdentityFeedState,
    IdentityHandoff,
    IdentityKey,
    IdentityKeySecret,
    IdentityLink,
    IdentityMerge,
    IdentitySubject,
)
from app.models.integrations import (
    Booking,
    BookingEvent,
    IntegrationDelivery,
    IntegrationSource,
    IntegrationSourceSecret,
)
from app.models.links import (
    LinkCampaign,
    LinkContentReference,
    LinkDestinationOrigin,
    LinkDomain,
    LinkUtmTemplate,
    ManagedLink,
)
from app.models.payments import PaymentCallbackDiagnostic, PaymentSource, PaymentSourceSecret
from app.models.revenue import RevenueEvidence, RevenueImport
from app.models.tenancy import (
    Agency,
    AgencyMembership,
    AuditEvent,
    ClientGrant,
    ClientWorkspace,
    User,
)
from app.models.whatsapp import WhatsappMessage, WhatsappNumber

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
    "LinkCampaign",
    "LinkContentReference",
    "LinkDestinationOrigin",
    "LinkDomain",
    "LinkUtmTemplate",
    "ManagedLink",
    "ConnectorCheckpoint",
    "ConnectorConnection",
    "ConnectorDeletionRequest",
    "ConnectorOAuthTransaction",
    "ConnectorRecord",
    "ConnectorSyncRun",
    "ConnectorTokenSecret",
    "ConnectorUsageRecord",
    "ConnectorWebhookDelivery",
    "AdAccount",
    "AdObject",
    "AdSpendFact",
    "ConversionAcknowledgement",
    "ConversionDelivery",
    "ConversionDestination",
    "PaymentCallbackDiagnostic",
    "PaymentSource",
    "PaymentSourceSecret",
    "RevenueEvidence",
    "RevenueImport",
    "Booking",
    "BookingEvent",
    "CrmDeal",
    "CrmStageRule",
    "IntegrationDelivery",
    "IntegrationSource",
    "IntegrationSourceSecret",
    "WhatsappMessage",
    "WhatsappNumber",
    "IdentityAssertion",
    "IdentityAssertionReceipt",
    "IdentityChange",
    "IdentityErasureHold",
    "IdentityFeedState",
    "IdentityHandoff",
    "IdentityKey",
    "IdentityKeySecret",
    "IdentityLink",
    "IdentityMerge",
    "IdentitySubject",
]
