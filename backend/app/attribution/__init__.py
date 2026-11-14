"""Specification 008-A lead and revenue attribution calculation (D-046).

engine holds the contracts (ModelVersion, Touchpoint, Conversion, AttributionRun,
CreditAllocation and the attribution EvidenceClass), attribute() for one conversion under one
model version, AttributionHistory for revisions, and IncrementalAttribution, which consumes the
007-A movement journal. Everything is pure and in memory: no table, HTTP route, identity
matching or live provider exists yet.
"""

from app.attribution.engine import (
    DEFAULT_WINDOW,
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
    ModelVersion,
    Recipient,
    RevisionCause,
    RunStatus,
    Touchpoint,
    attribute,
    sale_conversion,
    verified_net,
)

__all__ = [
    "DEFAULT_WINDOW",
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
    "ModelVersion",
    "Recipient",
    "RevisionCause",
    "RunStatus",
    "Touchpoint",
    "attribute",
    "sale_conversion",
    "verified_net",
]
