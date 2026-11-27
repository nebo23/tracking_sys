"""Approved SQLAlchemy metadata for specifications 002 to 005 and 009-A."""

# Importing this package registers every mapped table in Base.metadata, which Alembic's env.py
# and the readiness/model-agreement checks rely on. It covers the 002-A tenancy models, the
# approved 002-B/C/D authentication and access models, the D-022 identity and verification
# models, the D-027 event collection models, the D-033 managed-link models, the D-048
# connector lifecycle models, the D-064 advertising models, the D-067 revenue and payment
# models, the D-075 identity and ledger models, the D-079 attribution models, the D-092
# plan, closure and agreement models, the D-095 report delivery models, and the D-098
# offboarding export and purge models.
from app.models.access import (
    AgencyInvitation,
    InvitationClientGrant,
    ServiceClientGrant,
    ServiceCredential,
)
from app.models.advertising import AdAccount, AdObject, AdSpendFact
from app.models.attribution import (
    AttributionAllocation,
    AttributionConsumerState,
    AttributionConversion,
    AttributionCreditChange,
    AttributionModelVersion,
    AttributionRun,
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
from app.models.ledger import (
    LedgerMovement,
    LedgerProjectionState,
    LedgerReceipt,
    LedgerReconciliationAction,
    LedgerTransaction,
)
from app.models.links import (
    LinkCampaign,
    LinkContentReference,
    LinkDestinationOrigin,
    LinkDomain,
    LinkUtmTemplate,
    ManagedLink,
)
from app.models.offboarding import AgencyExport, AgencyExportPart, AgencyPurge
from app.models.payments import PaymentCallbackDiagnostic, PaymentSource, PaymentSourceSecret
from app.models.report_delivery import (
    AgencyBranding,
    ReportExport,
    ReportExportContent,
    ReportSchedule,
    ReportScheduleRecipient,
)
from app.models.revenue import RevenueEvidence, RevenueImport
from app.models.revenue_identity import RevenueIdentityBinding
from app.models.saas import AgencyClosure, AgencyPlanAssignment, SaasPlan, UserAgreement
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
    "LedgerMovement",
    "LedgerProjectionState",
    "LedgerReceipt",
    "LedgerReconciliationAction",
    "LedgerTransaction",
    "RevenueIdentityBinding",
    "AttributionAllocation",
    "AttributionConsumerState",
    "AttributionConversion",
    "AttributionCreditChange",
    "AttributionModelVersion",
    "AttributionRun",
    "AgencyClosure",
    "AgencyPlanAssignment",
    "SaasPlan",
    "UserAgreement",
    "AgencyBranding",
    "ReportExport",
    "ReportExportContent",
    "ReportSchedule",
    "ReportScheduleRecipient",
    "AgencyExport",
    "AgencyExportPart",
    "AgencyPurge",
]
