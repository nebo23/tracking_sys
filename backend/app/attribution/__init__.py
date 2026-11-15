"""Specification 008-A lead and revenue attribution calculation (D-046).

engine holds the contracts (ModelVersion, Touchpoint, Conversion, SaleState, AttributionRun,
CreditAllocation and the attribution EvidenceClass), attribute() for one conversion under one
model version, AttributionHistory for revisions and their registry, ledger_feed() for the
receipt journal of a 007-A receipt log, and IncrementalAttribution, which consumes it.
Everything is pure and in memory: no table, HTTP route, identity matching or live provider
exists yet.
"""

from app.attribution.engine import (
    DEFAULT_WINDOW,
    EARLIEST_INSTANT,
    RULES,
    Association,
    AttributionHistory,
    AttributionInputError,
    AttributionModel,
    AttributionRun,
    Conversion,
    ConversionKind,
    CreditAllocation,
    CreditBasis,
    CreditDifference,
    EvidenceClass,
    ExcludedTouch,
    ExclusionReason,
    IncrementalAttribution,
    JournalItem,
    ModelVersion,
    Recipient,
    RevisionCause,
    RunStatus,
    SaleState,
    Touchpoint,
    attribute,
    ledger_feed,
    sale_conversion,
    sale_state,
)

__all__ = [
    "DEFAULT_WINDOW",
    "EARLIEST_INSTANT",
    "RULES",
    "Association",
    "AttributionHistory",
    "AttributionInputError",
    "AttributionModel",
    "AttributionRun",
    "Conversion",
    "ConversionKind",
    "CreditAllocation",
    "CreditBasis",
    "CreditDifference",
    "EvidenceClass",
    "ExcludedTouch",
    "ExclusionReason",
    "IncrementalAttribution",
    "JournalItem",
    "ModelVersion",
    "Recipient",
    "RevisionCause",
    "RunStatus",
    "SaleState",
    "Touchpoint",
    "attribute",
    "ledger_feed",
    "sale_conversion",
    "sale_state",
]
