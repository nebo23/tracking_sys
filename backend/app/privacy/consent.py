"""ConsentRecord contract and consent evaluation (specification 003-B, D-025).

The only enabled jurisdiction profile is J1, strict opt-in in every workspace: each purpose
except "necessary" is allowed only while the latest server-received record grants it and has
not expired. Unknown, denied, withdrawn, and expired states are all denials. Consent is never
inferred from scrolling, form submission, or closing a banner; those are not record sources.
Market-specific profiles wait for Q-003 and a reviewed decision.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

POLICY_VERSION = "003-B.1"
_HEX64 = re.compile(r"[0-9a-f]{64}")


# Internal purpose codes, mapped to provider signals so a provider renaming its signals never
# changes the internal model (design section 5).
class Purpose(StrEnum):
    NECESSARY = "necessary"
    ANALYTICS = "analytics.first_party"
    ATTRIBUTION = "attribution"
    IDENTITY_LINK = "identity_link"
    ADS_MEASUREMENT = "ads.measurement"
    ADS_PERSONALIZATION = "ads.personalization"
    SALE_OR_SHARE = "sale_or_share"


class ConsentState(StrEnum):
    UNKNOWN = "unknown"
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


# Where a record came from. Implicit signals (scroll, form submission, banner close) are
# deliberately absent, so they cannot be recorded as consent.
class ConsentSource(StrEnum):
    TRACKER_BANNER = "tracker_banner"
    EXTERNAL_CMP = "external_cmp"
    GPC = "gpc"
    API = "api"
    ADMIN_IMPORT = "admin_import"


class Profile(StrEnum):
    STRICT_OPT_IN = "J1"


ENABLED_PROFILES = frozenset({Profile.STRICT_OPT_IN})
# A Global Privacy Control signal is an opt-out; it may only deny these purposes. The set is
# conservative: it includes advertising measurement because conversion delivery can be
# "sharing" under some laws.
GPC_PURPOSES = frozenset(
    {Purpose.SALE_OR_SHARE, Purpose.ADS_MEASUREMENT, Purpose.ADS_PERSONALIZATION}
)
RECORDABLE_STATES = frozenset({ConsentState.GRANTED, ConsentState.DENIED, ConsentState.WITHDRAWN})


# One append-only consent record. subject_ref is the keyed subject key (hex HMAC), never a
# raw identifier; captured_at is the untrusted client time and is never used for ordering.
@dataclass(frozen=True)
class ConsentRecord:
    id: UUID
    agency_id: UUID
    client_id: UUID
    subject_ref: str
    key_id: str
    purpose: Purpose
    state: ConsentState
    source: ConsentSource
    jurisdiction_profile: Profile
    policy_version: str
    notice_snapshot_hash: str
    received_at: datetime
    captured_at: datetime | None = None
    expires_at: datetime | None = None
    supersedes_id: UUID | None = None

    def __post_init__(self) -> None:
        if not _HEX64.fullmatch(self.subject_ref) or not _HEX64.fullmatch(
            self.notice_snapshot_hash
        ):
            raise ValueError("Consent records hold keyed subject and notice digests only.")
        if self.purpose is Purpose.NECESSARY:
            raise ValueError("Necessary processing is not consent-based.")
        if self.state not in RECORDABLE_STATES:
            raise ValueError("Only granted, denied, or withdrawn states are recorded.")
        if self.jurisdiction_profile not in ENABLED_PROFILES:
            raise ValueError("The jurisdiction profile is not enabled.")
        if self.source is ConsentSource.GPC and (
            self.state is ConsentState.GRANTED or self.purpose not in GPC_PURPOSES
        ):
            raise ValueError("A GPC signal may only deny sale, sharing, or advertising.")
        if self.received_at.tzinfo is None or (
            self.expires_at is not None and self.expires_at.tzinfo is None
        ):
            raise ValueError("Consent times must be timezone-aware.")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


# Current state of one purpose from a subject's records: the latest by server receipt (ties
# broken by ID), with an expired grant reported as expired. No record means unknown.
def current_state(
    records: Iterable[ConsentRecord], purpose: Purpose, now: datetime
) -> ConsentState:
    relevant = [record for record in records if record.purpose == purpose]
    if not relevant:
        return ConsentState.UNKNOWN
    latest = max(relevant, key=lambda record: (record.received_at, str(record.id)))
    if (
        latest.state is ConsentState.GRANTED
        and latest.expires_at is not None
        and latest.expires_at <= now
    ):
        return ConsentState.EXPIRED
    return latest.state


# Allow or deny one purpose with a closed reason code.
def evaluate(
    purpose: Purpose, state: ConsentState, profile: Profile = Profile.STRICT_OPT_IN
) -> Decision:
    if profile not in ENABLED_PROFILES:
        return Decision(False, "profile_not_enabled")
    if purpose is Purpose.NECESSARY:
        return Decision(True, "necessary")
    if state is ConsentState.GRANTED:
        return Decision(True, "granted")
    return Decision(False, f"consent_{state.value}")


# Enforcement points E2-E6 (ingestion, identity linking, outbound enqueue and delivery claim,
# imports): every required purpose must be allowed; the first denial is reported.
def require_all(
    purposes: Iterable[Purpose],
    states: Mapping[Purpose, ConsentState],
    profile: Profile = Profile.STRICT_OPT_IN,
) -> Decision:
    for purpose in sorted(set(purposes)):
        decision = evaluate(purpose, states.get(purpose, ConsentState.UNKNOWN), profile)
        if not decision.allowed:
            return decision
    return Decision(True, "granted")


# Google Consent Mode v2 signals for basic mode (tags wait for consent). Each signal follows
# the internal purpose it represents.
GOOGLE_CONSENT_SIGNALS: dict[str, Purpose] = {
    "ad_storage": Purpose.ADS_MEASUREMENT,
    "ad_user_data": Purpose.ADS_MEASUREMENT,
    "ad_personalization": Purpose.ADS_PERSONALIZATION,
    "analytics_storage": Purpose.ANALYTICS,
    "functionality_storage": Purpose.NECESSARY,
    "security_storage": Purpose.NECESSARY,
}


def google_consent_mode(
    states: Mapping[Purpose, ConsentState], profile: Profile = Profile.STRICT_OPT_IN
) -> dict[str, str]:
    return {
        signal: "granted"
        if evaluate(purpose, states.get(purpose, ConsentState.UNKNOWN), profile).allowed
        else "denied"
        for signal, purpose in GOOGLE_CONSENT_SIGNALS.items()
    }
