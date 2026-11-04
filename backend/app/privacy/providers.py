"""Provider-specific policy table (specification 003-C, D-025) as versioned code data.

Connector rows come from research checked on 2026-11-03 and are marked stale: each connector
specification (009-016) must re-verify, test, and mark its rows current before the feature
they govern is allowed. A stale or unsupported row, or one past its review date, blocks the
feature instead of defaulting to permissive. The two Google platform rows describe existing
D-022 behavior. No row implies provider app approval or review access.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.privacy.consent import Decision


class RuleStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ProviderRule:
    provider: str
    rule_id: str
    data_class: str
    retention_limit: str
    deletion_trigger: str
    callback_or_refresh: str
    use_limits: str
    source_refs: tuple[str, ...]
    reverify_in: str
    verified_at: date
    status: RuleStatus
    review_due_at: date | None = None


RESEARCHED = date(2026, 11, 3)
STALE = RuleStatus.STALE

RULES: tuple[ProviderRule, ...] = (
    ProviderRule(
        "meta",
        "meta.platform_data",
        "provider.social_data",
        "Until no longer necessary, including derived and aggregated data",
        "User, client, or Meta request, or product end: as soon as reasonably possible",
        "Signed data deletion callback; annual Data Use Checkup",
        "Per-client separation; no cross-client aggregation",
        ("S-61", "S-62", "S-66"),
        "009, 010",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "instagram",
        "instagram.login_api",
        "provider.social_data",
        "Meta rule; references and metrics, not media archives",
        "Deauthorize: revoke, disconnected state, purpose-end deletion",
        "Deauthorize and deletion URLs; refresh after 24 hours, before 60 days",
        "App Review, Advanced Access, and Business Verification are prerequisites",
        ("S-63", "S-64", "S-65"),
        "010",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "meta",
        "meta.conversions_api",
        "identity.provider_match_key",
        "Events older than 7 days rejected; Meta deletes contact data after matching",
        "Tombstone and consent check before send and replay",
        "None",
        "SHA-256 contact fields; never hash IP, user agent, fbc, fbp; verifiable consent; "
        "Limited Data Use for listed US states; no sensitive or under-13 data",
        ("S-67", "S-68", "S-69", "S-70"),
        "014",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "youtube",
        "youtube.authorized_analytics",
        "provider.social_data",
        "While necessary; authorization rechecked every 30 days",
        "In-app revocation: delete within 7 days; settings revocation: 30 days; "
        "user request: 7 days",
        "Optional Cross-Account Protection receiver",
        "Limited Use; no cross-owner aggregation; no derived metrics by default",
        ("S-71", "S-72", "S-73", "S-75"),
        "011",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "youtube",
        "youtube.other_data",
        "provider.social_data",
        "30 days, statistics included for public data",
        "Expiry; termination: immediately, with certification possible",
        "Refresh or purge job",
        "Shown only to the authorizing user and approved agents",
        ("S-72", "S-74"),
        "011",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "linkedin",
        "linkedin.member_data",
        "provider.social_data",
        "Social activity 48 hours; other member profiles a 24-hour cache, not stored",
        "User request or account closure: immediately",
        "Token 60 days, refresh token 365 days; re-consent at expiry",
        "Not for leads, CRM enrichment, audiences, combination, or export",
        ("S-80", "S-81", "S-82", "S-84"),
        "012",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "linkedin",
        "linkedin.organization_data",
        "provider.social_data",
        "Social activity 6 weeks (6 months if authenticated); profile 8 weeks if "
        "authenticated; reporting 1 year",
        "Client offboarding or request: 10 days; termination: immediately for member data",
        "Incident notice within 24 hours",
        "Shortest applicable duration wins",
        ("S-80", "S-81", "S-83"),
        "012",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "linkedin",
        "linkedin.conversions_api",
        "identity.provider_match_key",
        "Conversions within 90 days",
        "Tombstone check before send",
        "None",
        "SHA256_EMAIL; plaintext IP subject to consent; legal basis per event; "
        "normalization unverified",
        ("S-83", "S-85"),
        "014",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "x",
        "x.stored_content",
        "provider.social_data",
        "Kept in sync with X",
        "Deletion, protection, suspension, or request: 24 hours; termination: delete, "
        "evidence within 10 business days",
        "Batch compliance jobs (delete, rehydrate, scrub_geo)",
        "Off-X matching needs express opt-in; no model training or off-X ad targeting; "
        "export IDs only",
        ("S-86", "S-87", "S-88"),
        "013",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "google_ads",
        "google_ads.enhanced_conversions",
        "identity.provider_match_key",
        "Not researched",
        "Tombstone check before upload",
        "None",
        "SHA-256 email, E.164 phone, names, street; location fields plain; ad_user_data "
        "consent per upload; no IP matching for EEA, UK, or Swiss users",
        ("S-76", "S-77", "S-78"),
        "014",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "payments",
        "payments.processor_records",
        "financial.record",
        "Provider IDs, brand, last four digits, and expiry only",
        "Subject deletion detaches identifiers (decision 11)",
        "Webhook signature or HMAC verification",
        "Never PAN, CVC, or raw card posting",
        ("S-89", "S-90", "S-91"),
        "015",
        RESEARCHED,
        STALE,
    ),
    ProviderRule(
        "google",
        "google.sign_in",
        "identity.external_subject",
        "Issuer and subject only, while linked; no Google token or profile copy",
        "Account closure (D-024): the lifecycle runner deletes the identity",
        "None",
        "Identity scopes only; the subject, not the email, identifies the account",
        ("S-114",),
        "020",
        date(2026, 11, 4),
        RuleStatus.CURRENT,
    ),
    ProviderRule(
        "google",
        "google.gmail_sender",
        "message.transactional",
        "Sent copies remain in the sender mailbox, outside application control",
        "The owner revokes the authorization in their Google account",
        "Refresh token in ignored .env; 7-day expiry in Testing publishing status",
        "gmail.send only; no inbox read or modify",
        ("auth design",),
        "020",
        date(2026, 11, 4),
        RuleStatus.CURRENT,
    ),
)


def rule(rule_id: str) -> ProviderRule:
    for item in RULES:
        if item.rule_id == rule_id:
            return item
    raise KeyError(rule_id)


# Gate for a provider-governed feature: only a current rule within its review date allows it.
def feature_allowed(item: ProviderRule, today: date) -> Decision:
    if item.status is RuleStatus.UNSUPPORTED:
        return Decision(False, "rule_unsupported")
    if item.status is RuleStatus.STALE:
        return Decision(False, "rule_stale")
    if item.review_due_at is not None and today > item.review_due_at:
        return Decision(False, "rule_review_overdue")
    return Decision(True, "rule_current")
