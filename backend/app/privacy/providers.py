"""Provider-specific policy table (specification 003-C, D-025) as versioned code data.

Connector rows come from research checked on 2026-11-03 and are marked stale: each connector
specification (009-016) must re-verify, test, and mark its rows current before the feature
they govern is allowed. A stale or unsupported row, or one past its review date, blocks the
feature instead of defaulting to permissive. The two Google platform rows describe existing
D-022 behavior. Specification 010-C (D-055) re-verified the Meta platform data and Instagram
Login rows on 2026-11-17 against the Platform Terms and Developer Policies of 2026-02-03 and
Meta's data deletion callback documentation; they are current until their review date.
Specification 011-C (D-060) re-verified the two YouTube rows on 2026-11-18 against the YouTube
API Services Developer Policies (III.D.2, III.E.2 to III.E.4), the YouTube API Services Terms of
Service (section 24.3) and the Google API Services User Data Policy of 2024-02-15. Specification
014-D (D-064) re-verified the Meta Conversions API row and added the Meta Marketing API row on
2026-11-20 against the Business Tools Terms of 2025-11-03, the Platform Terms of 2026-02-03 and
the Conversions API, Marketing API, Login for Business and permission pages of entry review
section 2.4. Specification 015-B (D-067) re-verified the payment processor row and added the
Paymob Accept row on 2026-11-21 against Paymob's callback, HMAC, transaction, refund, void,
capture, intention, credential and security pages, Paymob's terms and PCI SSC FAQ 1154 of
entry review section 2.4. No row implies provider app approval or review access.
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
# Specification 010-C re-verification (D-055) and the annual review it sets.
REVERIFIED_010 = date(2026, 11, 17)
REVIEW_010 = date(2027, 11, 17)
# Specification 011-C re-verification (D-060) and the annual review it sets.
REVERIFIED_011 = date(2026, 11, 18)
REVIEW_011 = date(2027, 11, 18)
# Specification 014-D re-verification (D-064) and the annual review it sets.
REVERIFIED_014 = date(2026, 11, 20)
REVIEW_014 = date(2027, 11, 20)
# Specification 015-B re-verification (D-067) and the annual review it sets.
REVERIFIED_015 = date(2026, 11, 21)
REVIEW_015 = date(2027, 11, 21)

RULES: tuple[ProviderRule, ...] = (
    ProviderRule(
        "meta",
        "meta.platform_data",
        "provider.social_data",
        "Until no longer necessary for a legitimate business purpose",
        "User, client, or Meta request, or no longer necessary: as soon as reasonably possible",
        "Signed data deletion callback over HTTPS; annual Data Use Checkup once live or with "
        "Advanced Access",
        "Each client's Platform Data kept separate; no cross-client aggregation",
        ("S-61", "S-62", "S-66"),
        "009, 010",
        REVERIFIED_010,
        RuleStatus.CURRENT,
        REVIEW_010,
    ),
    ProviderRule(
        "instagram",
        "instagram.login_api",
        "provider.social_data",
        "Meta rule; references and metrics, never media content or backups",
        "Deauthorize or deletion request: disconnect, destroy tokens, purge (D-053 D5)",
        "Signed deauthorize and deletion callbacks; long-lived token refreshed after 24 hours "
        "and at least 7 days before its 60-day expiry",
        "Development mode: only people with a role on the app; App Review, Advanced Access, "
        "and Business Verification before customer accounts (010-D)",
        ("S-63", "S-64", "S-65"),
        "010",
        REVERIFIED_010,
        RuleStatus.CURRENT,
        REVIEW_010,
    ),
    ProviderRule(
        "meta",
        "meta.conversions_api",
        "identity.provider_match_key",
        "Events older than 7 days rejected; Meta deletes contact information after matching "
        "and may keep event data up to two years; payloads destroyed when a delivery ends",
        "Consent and tombstone checks at enqueue and at the delivery claim (E4, E5) and "
        "before any replay",
        "None documented for Login for Business; token errors require reconnection",
        "ads_read; fbc only, never hashed; no contact field, IP address or user agent; "
        "website events need client_user_agent, which is not collected; agent authority for "
        "each client; no sensitive or under-13 data; Limited Data Use not used under J1",
        ("S-67", "S-68", "S-70", "V-8", "V-9", "V-10", "V-12", "V-14", "V-16"),
        "014",
        REVERIFIED_014,
        RuleStatus.CURRENT,
        REVIEW_014,
    ),
    ProviderRule(
        "meta",
        "meta.marketing_api",
        "advertising.spend",
        "While the connection is active and at most 730 days after the spend date "
        "(D-064 D13); Platform Data deleted when no longer necessary",
        "Disconnect purge; user, client or Meta request: as soon as reasonably possible",
        "None documented for Login for Business; token errors require reconnection",
        "ads_read; Limited Access covers ad accounts of people with a role on the app until "
        "Full Access, App Review and Business Verification (014-G); each client's data kept "
        "separate",
        ("S-61", "V-1", "V-2", "V-4", "V-5", "V-6", "V-7", "V-16"),
        "014",
        REVERIFIED_014,
        RuleStatus.CURRENT,
        REVIEW_014,
    ),
    ProviderRule(
        "youtube",
        "youtube.authorized_analytics",
        "provider.social_data",
        "While necessary, at most 730 days (Q-012 proposal); authorization confirmed at least "
        "every 30 days; videos checked for deletion every 30 days",
        "In-app revocation: revoke at once, delete within 7 days; revocation in Google settings "
        "or an unrefreshable token: within 30 days; user request or account deletion: 7 days; "
        "termination: immediately",
        "No deletion callback; refresh failures detect revocation; RISC not used",
        "Limited Use; the authorizing user and expressly approved agents only; aggregation "
        "within one content owner; no derived metrics without the additional terms; "
        "non-YouTube data disclosed",
        ("S-71", "S-72", "S-73", "S-74", "S-75"),
        "011",
        REVERIFIED_011,
        RuleStatus.CURRENT,
        REVIEW_011,
    ),
    ProviderRule(
        "youtube",
        "youtube.other_data",
        "provider.social_data",
        "Labels and video attributes refreshed or deleted within 30 days; non-authorized "
        "statistics at most 30 days; none collected at launch",
        "Expiry; termination: immediately, with certification possible",
        "Refresh or purge job",
        "Shown only to the authorizing user and approved agents",
        ("S-72", "S-74"),
        "011",
        REVERIFIED_011,
        RuleStatus.CURRENT,
        REVIEW_011,
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
        "revenue.evidence",
        "Provider transaction, order and integration IDs, amounts, currencies, states and times "
        "only, for the life of the client workspace (D-067 D14); no card, billing, shipping or "
        "customer field and no raw payload",
        "Subject deletion detaches identifiers (decision 11); workspace deletion (017)",
        "Webhook signature or HMAC verification before anything is stored",
        "Never a PAN or masked PAN, brand, last four digits, expiry, CVC, token or raw card "
        "posting; no sensitive authentication data after authorization (PCI DSS 3.3.1)",
        ("S-89", "S-90", "S-91", "V-1", "V-2", "V-12", "V-13"),
        "015",
        REVERIFIED_015,
        RuleStatus.CURRENT,
        REVIEW_015,
    ),
    ProviderRule(
        "paymob",
        "paymob.accept",
        "revenue.evidence",
        "Minimized transaction evidence for the life of the client workspace; callback "
        "diagnostics 30 days; replaced HMAC secrets 24 hours (D-067 D14)",
        "Workspace deletion (017); the source is disabled to stop intake",
        "HMAC-SHA512 processed callbacks over HTTPS (020) to a per-source URL; the response "
        "redirect is never evidence; the merchant's HMAC secret is sealed and never returned",
        "Region egypt; the merchant's own HMAC secret per client; no Paymob API key and no "
        "outbound call; whether a merchant may direct callbacks carrying the last four digits to "
        "this platform under Paymob's terms is reviewed before live intake (Q-012)",
        ("V-1", "V-2", "V-3", "V-4", "V-7", "V-8", "V-9", "V-11", "V-12", "V-13"),
        "015",
        REVERIFIED_015,
        RuleStatus.CURRENT,
        REVIEW_015,
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
