"""Pure 008-B mapping between engine runs and persisted rows (D-079; no database).

Round trips of engine runs through the stored values must reconstruct the latest revision
exactly, so that attribute() with it as previous returns it unchanged for identical inputs, and
the credit changes of every revision must sum to the latest allocations. Synthetic values only.
"""

import random
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from uuid import UUID, uuid4

import pytest

from app.attribution import (
    Association,
    AttributionModel,
    Conversion,
    ConversionKind,
    EvidenceClass,
    ModelVersion,
    SaleState,
    Touchpoint,
    attribute,
)
from app.ledger import Currency, LedgerScope
from app.privacy.consent import ConsentState
from app.services import attribution_records as records

AGENCY = UUID("00000000-0000-4000-8000-00000000a001")
CLIENT = UUID("00000000-0000-4000-8000-00000000c001")
CLIENT_2 = UUID("00000000-0000-4000-8000-00000000c002")
PERSON = UUID("00000000-0000-4000-8000-0000000000e1")
EGP = Currency("EGP", 2)
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
DAY = timedelta(days=1)
VERSIONS = tuple(
    ModelVersion(records.version_key(model.value, 30, 1), model) for model in AttributionModel
)


def touch(index: int, offset: timedelta, *, campaign: bool = True, **extra) -> Touchpoint:
    refs = (
        {
            "source": "tracker",
            "campaign_ref": f"spring-{index % 3}",
            "content_ref": f"post-{index % 2}",
            "link_ref": str(UUID(int=10_000 + index % 4)),
        }
        if campaign
        else {"source": "tracker"}
    )
    refs.update(extra)
    return Touchpoint(
        str(UUID(int=index + 1)),
        AGENCY,
        CLIENT,
        str(PERSON),
        EvidenceClass.CAMPAIGN_INTERACTION if campaign else EvidenceClass.DIRECT_VISIT,
        T0 + offset,
        Association.ASSIGNED,
        ConsentState.GRANTED,
        **refs,
    )


def sale_conversion(conversion_id: UUID) -> Conversion:
    return records.engine_conversion(
        conversion_id, AGENCY, CLIENT, "sale", PERSON, T0, "acct", "S1"
    )


def lead_conversion(conversion_id: UUID) -> Conversion:
    return records.engine_conversion(conversion_id, AGENCY, CLIENT, "lead", PERSON, T0, None, None)


def state(minor: int, at: datetime = T0) -> SaleState:
    return SaleState(LedgerScope(AGENCY, CLIENT, "acct"), "S1", EGP, at, minor)


def roundtrip(conversion: Conversion, version: ModelVersion, run, position=None):
    values = records.run_values(run)
    return values, records.reconstruct(conversion, version, values, ledger_position=position)


def ledger_sum(changes) -> dict[tuple, tuple[Fraction, int]]:
    totals: dict[tuple, list] = {}
    for item in changes:
        key = (
            item.effective_at,
            item.recipient,
            item.touchpoint_id,
            item.source,
            item.campaign_ref,
            item.content_ref,
            item.link_ref,
        )
        entry = totals.setdefault(key, [Fraction(0), 0])
        entry[0] += item.delta_share
        entry[1] += item.delta_minor or 0
    return {key: (share, minor) for key, (share, minor) in totals.items() if share or minor}


def allocation_sum(values: records.RunValues) -> dict[tuple, tuple[Fraction, int]]:
    found = {}
    for row in values.allocations:
        if row.credited:
            key = (
                values.window_end,
                row.recipient,
                row.touchpoint_id,
                row.source,
                row.campaign_ref,
                row.content_ref,
                row.link_ref,
            )
            found[key] = (row.share, row.amount_minor or 0)
    return found


def test_keys_digests_and_windows():
    sale = records.sale_slot_key(CLIENT, "acct", "S1")
    assert len(sale) == 64 and sale != records.sale_slot_key(CLIENT_2, "acct", "S1")
    lead = records.lead_slot_key(CLIENT, UUID(int=7))
    assert lead != sale and len(lead) == 64
    assert records.conversion_key(sale, 2) == f"{sale}.2"
    identifier = uuid4()
    assert records.scrubbed_conversion_key(identifier) == f"scrubbed.{identifier}"
    assert records.version_key("linear", 30, 1) == "linear_30d_v1"
    first = records.model_set_digest([("a", "linear", 86400, "008-A.1")])
    assert first == records.model_set_digest([("a", "linear", 86400, "008-A.1")])
    assert first != records.model_set_digest([("a", "linear", 172800, "008-A.1")])
    both = [("a", "linear", 86400, "008-A.1"), ("b", "first_click", 86400, "008-A.1")]
    assert records.model_set_digest(both) == records.model_set_digest(list(reversed(both)))
    assert [records.valid_window_days(value) for value in (0, 1, 90, 91, True, 30.0)] == [
        False,
        True,
        True,
        False,
        False,
        False,
    ]


@pytest.mark.parametrize("version", VERSIONS, ids=lambda item: item.model.value)
@pytest.mark.parametrize("kind", ["sale", "lead"])
@pytest.mark.parametrize(
    "journey",
    ["campaign", "direct", "none", "mixed"],
)
def test_reconstruction_is_exact_for_identical_inputs(version, kind, journey):
    identifier = uuid4()
    conversion = sale_conversion(identifier) if kind == "sale" else lead_conversion(identifier)
    touches = {
        "campaign": [touch(1, -3 * DAY), touch(2, -DAY), touch(3, -DAY)],
        "direct": [touch(4, -2 * DAY, campaign=False), touch(5, -DAY, campaign=False)],
        "none": [],
        "mixed": [
            touch(6, -40 * DAY),
            touch(7, -2 * DAY, campaign=False),
            touch(8, -DAY),
            touch(9, DAY),
        ],
    }[journey]
    sale = state(10_001) if kind == "sale" else None
    position = 4 if kind == "sale" else None
    run = attribute(conversion, touches, version, sale=sale, ledger_position=position)
    values, rebuilt = roundtrip(conversion, version, run, position)
    assert rebuilt.outcome == run.outcome
    again = attribute(
        conversion, touches, version, sale=sale, ledger_position=position, previous=rebuilt
    )
    assert again is rebuilt  # unchanged outcome: the same revision, nothing new to store
    later = attribute(
        conversion,
        touches,
        version,
        sale=sale,
        ledger_position=7 if kind == "sale" else None,
        previous=rebuilt,
    )
    assert later.revision == run.revision
    assert ledger_sum(records.credit_changes(ConversionKind(kind), None, values, run)) == (
        allocation_sum(values)
    )


def test_a_previous_run_of_another_ledger_journal_has_no_position():
    conversion = sale_conversion(uuid4())
    version = VERSIONS[2]
    run = attribute(conversion, [touch(1, -DAY)], version, sale=state(5_000), ledger_position=9)
    _, rebuilt = roundtrip(conversion, version, run, None)
    # The new journal starts again at receipt 2; the engine still checks currency and state.
    again = attribute(
        conversion,
        [touch(1, -DAY)],
        version,
        sale=state(5_000),
        ledger_position=2,
        previous=rebuilt,
    )
    assert again.revision == run.revision


def test_scrubbed_runs_are_never_reconstructed():
    conversion = sale_conversion(uuid4())
    version = VERSIONS[0]
    run = attribute(conversion, [touch(1, -DAY)], version, sale=state(100), ledger_position=1)
    values = records.run_values(run)
    rows = tuple(
        records.AllocationValues(**{**row.__dict__, "touchpoint_id": None, "occurred_at": None})
        for row in values.allocations
    )
    scrubbed = records.RunValues(**{**values.__dict__, "allocations": rows})
    with pytest.raises(ValueError, match="scrubbed_run"):
        records.reconstruct(conversion, version, scrubbed, ledger_position=1)


@pytest.mark.parametrize("seed", range(12))
def test_credit_changes_sum_to_the_latest_allocations(seed):
    generator = random.Random(seed)
    for version in VERSIONS:
        conversion = sale_conversion(uuid4())
        pool = [touch(index, -generator.randint(0, 35) * DAY) for index in range(6)]
        pool += [
            touch(10 + index, -generator.randint(1, 5) * DAY, campaign=False) for index in range(2)
        ]
        anchor, net, position = T0, 20_000, 1
        touches = generator.sample(pool, 3)
        previous_run, previous_values, ledger = None, None, []
        for step in range(10):
            action = generator.choice(["refund", "touch", "drop", "anchor", "same"])
            if action == "refund" and net > 1:
                net -= generator.randint(1, net // 2 + 1)
            elif action == "touch":
                touches = [*touches, generator.choice(pool)]
            elif action == "drop" and touches:
                touches = touches[1:]
            elif action == "anchor":
                anchor = anchor + timedelta(hours=generator.choice([-30, 7, 90]))
            position += 1
            run = attribute(
                conversion,
                touches,
                version,
                sale=state(net, anchor),
                ledger_position=position,
                previous=previous_run,
            )
            if previous_run is not None and run.revision == previous_run.revision:
                continue
            values = records.run_values(run)
            ledger += records.credit_changes(ConversionKind.SALE, previous_values, values, run)
            assert ledger_sum(ledger) == allocation_sum(values), (seed, step, action)
            previous_values = values
            _, previous_run = roundtrip(conversion, version, run, position)
        ledger += records.closing_changes(ConversionKind.SALE, previous_values)
        assert ledger_sum(ledger) == {}
        assert sum(item.delta_minor for item in ledger) == 0


def test_lead_credit_changes_carry_shares_only():
    conversion = lead_conversion(uuid4())
    version = VERSIONS[2]
    first = attribute(conversion, [touch(1, -2 * DAY), touch(2, -DAY)], version)
    first_values = records.run_values(first)
    booked = records.credit_changes(ConversionKind.LEAD, None, first_values, first)
    assert [item.delta_share for item in booked] == [Fraction(1, 2), Fraction(1, 2)]
    assert {item.delta_minor for item in booked} == {None}
    assert {item.currency for item in booked} == {None}
    _, rebuilt = roundtrip(conversion, version, first)
    second = attribute(conversion, [touch(2, -DAY)], version, previous=rebuilt)
    second_values = records.run_values(second)
    booked += records.credit_changes(ConversionKind.LEAD, first_values, second_values, second)
    assert ledger_sum(booked) == allocation_sum(second_values)
