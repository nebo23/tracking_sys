"""008-B persisted attribution consumer on disposable PostgreSQL (D-079).

Cases AV01-AV07, AV11, AV13 and AV16 of the 008-B verification matrix.

Persisted synthetic journeys, trusted leads, verified sales and associations go through the
bounded worker pass, and the stored conversions, runs, allocations and credit changes are read
back. Stored allocations equal a fresh calculation, the incremental state equals what a rebuild
would publish after every step, ownership changes supersede instead of mutating, and
publication follows the compare-and-swap. Synthetic values only.
"""

import json
import os
import random
import time
from datetime import UTC, datetime, timedelta, timezone
from fractions import Fraction
from uuid import uuid4

import pytest
from attribution_support import EGP, FIRST, LAST, LINEAR, USD, make_attribution_world
from identity_support import ATTRIBUTION, make_identity_world, rows
from report_support import append, evidence
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_revenue_identity import financial_snapshot

from app.ledger import Evidence, EvidenceClass, Money, OperationKind
from app.ledger_backfill import backfill
from app.models import (
    AttributionConversion,
    AttributionRun,
    IdentityFeedState,
    LedgerMovement,
    LedgerTransaction,
)
from app.security import now_utc
from app.services import attribution_store as store
from app.services.revenue import append_evidence, lock_revenue

pytestmark = pytest.mark.integration
HALF = Fraction(1, 2)
ONE = Fraction(1)


@pytest.fixture
def aw(authenticated_world, api):
    return make_attribution_world(make_identity_world(authenticated_world, api))


def buyer_with_touches(aw, email="buyer@example.test", campaigns=("spring", "autumn")):
    buyer = aw.person(email)
    events = [aw.touch(buyer.token, campaign) for campaign in campaigns]
    return buyer, events


def test_av01_first_last_and_linear_from_stored_allocations(aw):
    buyer, (first, second) = buyer_with_touches(aw)
    aw.sale("S1", 10_000)
    aw.associate(buyer.assertion, "S1")
    totals = aw.settle()
    assert totals["opened"] == 1 and totals["revisions"] == 3 and totals["rebuilds"] == 1
    conversion = aw.conversion("S1")
    assert conversion.owner_person_id == buyer.id and conversion.kind == "sale"
    stored = aw.latest(conversion.id)
    assert aw.credit(stored[FIRST]) == {"spring": (ONE, 10_000)}
    assert aw.credit(stored[LAST]) == {"autumn": (ONE, 10_000)}
    assert aw.credit(stored[LINEAR]) == {"spring": (HALF, 5_000), "autumn": (HALF, 5_000)}
    for key in (FIRST, LAST, LINEAR):
        values = stored[key]
        assert (values.status, values.basis, values.causes) == (
            "complete",
            "campaign",
            ("initial",),
        )
        assert values.currency == EGP and values.verified_net_minor == 10_000
        assert [row.touchpoint_id for row in values.allocations] == [first, second]
        assert [row.source for row in values.allocations] == ["tracker", "tracker"]
    # First and Last keep the uncredited eligible touch, which the next revision compares.
    assert [row.credited for row in stored[FIRST].allocations] == [True, False]
    assert [row.credited for row in stored[LAST].allocations] == [False, True]
    assert aw.ledger(LINEAR) == {("spring", "EGP"): (HALF, 5_000), ("autumn", "EGP"): (HALF, 5_000)}
    assert aw.state().status == "ready" and aw.state().generation == 1
    aw.assert_fresh()


def test_av02_unknown_and_unassociated_sales_reconcile_with_the_net(aw):
    buyer = aw.person("quiet@example.test")  # a person without any touch
    aw.sale("S1", 7_777)
    aw.associate(buyer.assertion, "S1")
    aw.sale("S2", 3_333)  # never associated
    aw.settle()
    for operation, net, owner in (("S1", 7_777, buyer.id), ("S2", 3_333, None)):
        conversion = aw.conversion(operation)
        assert conversion.owner_person_id == owner
        for values in aw.latest(conversion.id).values():
            assert values.basis == "unknown_fallback"
            assert aw.credit(values) == {"unknown": (ONE, net)}
            (row,) = values.allocations
            assert (row.position, row.touchpoint_id, row.evidence_class) == (0, None, None)
    # Attributed revenue equals ledger revenue under every model.
    for key in (FIRST, LAST, LINEAR):
        assert aw.ledger(key) == {("unknown", "EGP"): (2 * ONE, 11_110)}
    aw.assert_fresh()


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_av02_random_journeys_allocate_the_exact_net(aw, seed):
    generator = random.Random(seed)
    people = [aw.person(f"random{index}@example.test") for index in range(3)]
    for index, person in enumerate(people):
        for _ in range(generator.randint(0, 4)):
            campaign = generator.choice([None, "spring", "autumn", "winter"])
            aw.touch(person.token, campaign)
        net = generator.randint(1, 99_999)
        aw.sale(f"S{index}", net)
        aw.associate(person.assertion, f"S{index}")
    aw.settle()
    for index in range(3):
        conversion = aw.conversion(f"S{index}")
        for values in aw.latest(conversion.id).values():
            credited = [row for row in values.allocations if row.credited]
            assert sum(row.amount_minor for row in credited) == values.verified_net_minor
            assert sum((row.share for row in credited), Fraction(0)) == 1
    aw.assert_fresh()


def test_av03_window_boundaries_zones_ties_refund_and_late_touch(aw):
    buyer = aw.person("window@example.test")
    base = now_utc()
    tie = base + timedelta(seconds=2)
    edge = aw.touch(buyer.token, "edge", at=base + timedelta(seconds=1))
    tied = sorted([aw.touch(buyer.token, "tie-a", at=tie), aw.touch(buyer.token, "tie-b", at=tie)])
    # The sale takes effect exactly 30 days after the first touch, written in another zone.
    cairo = timezone(timedelta(hours=2))
    effective = (base + timedelta(seconds=1) + timedelta(days=30)).astimezone(cairo)
    aw.sale("S1", 9_000, when=effective)
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    conversion = aw.conversion("S1")
    linear = aw.latest(conversion.id)[LINEAR]
    assert linear.window_end == effective.astimezone(UTC)
    assert linear.window_start == effective.astimezone(UTC) - timedelta(days=30)
    # Inclusive at the start: the touch at the window's first instant is eligible. Equal
    # instants are ordered by touchpoint ID.
    assert [row.touchpoint_id for row in linear.allocations] == [edge, *tied]
    assert [row.amount_minor for row in linear.allocations] == [3_000, 3_000, 3_000]
    first = aw.latest(conversion.id)[FIRST]
    assert [row.touchpoint_id for row in first.allocations if row.credited] == [edge]
    # One microsecond later the first touch falls before the window.
    aw.sale("S2", 9_000, when=effective + timedelta(microseconds=1))
    aw.associate(buyer.assertion, "S2")
    aw.settle()
    second = aw.latest(aw.conversion("S2").id)[LINEAR]
    assert [row.touchpoint_id for row in second.allocations] == tied
    assert (edge, "before_window") in second.excluded
    # A refund revises the amounts with exact signed differences.
    aw.sale("R1", 3_000, kind=OperationKind.REFUND, parent="S1")
    aw.settle()
    revisions = aw.revisions(conversion.id, LINEAR)
    assert [item.revision for item in revisions] == [1, 2]
    assert revisions[1].causes == ("revenue_changed",) and revisions[1].verified_net_minor == 6_000
    assert [row.amount_minor for row in revisions[1].allocations] == [2_000, 2_000, 2_000]
    assert aw.ledger(LINEAR, conversion_id=conversion.id) == {
        ("edge", "EGP"): (Fraction(1, 3), 2_000),
        ("tie-a", "EGP"): (Fraction(1, 3), 2_000),
        ("tie-b", "EGP"): (Fraction(1, 3), 2_000),
    }
    # A late touch before the sale instant joins the journey as a new revision; a touch after
    # the sale instant is excluded.
    late = aw.touch(buyer.token, "late", at=base + timedelta(seconds=3))
    aw.settle()
    revisions = aw.revisions(conversion.id, LINEAR)
    assert revisions[-1].revision == 3 and revisions[-1].causes == ("touches_changed",)
    assert [row.touchpoint_id for row in revisions[-1].allocations] == [edge, *tied, late]
    assert [row.amount_minor for row in revisions[-1].allocations] == [1_500] * 4
    last = aw.revisions(conversion.id, LAST)
    assert [row.touchpoint_id for row in last[-1].allocations if row.credited] == [late]
    aw.assert_fresh()


def test_av04_an_identical_pass_stores_nothing(aw):
    buyer, _ = buyer_with_touches(aw)
    aw.sale("S1", 5_000)
    aw.associate(buyer.assertion, "S1")
    aw.lead(buyer.token)
    aw.settle()
    before, counts = aw.snapshot(), aw.counts()
    assert counts["attribution_conversions"] == 2 and counts["attribution_runs"] == 6
    for _ in range(3):
        result = aw.run()
        assert result["outcome"] == "caught_up"
        assert not result.get("revisions") and not result.get("opened")
    assert aw.counts() == counts and aw.snapshot() == before


def test_av04_a_new_version_keeps_the_old_history_byte_identical(aw):
    buyer, _ = buyer_with_touches(aw)
    aw.sale("S1", 5_000)
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    aw.sale("R1", 1_000, kind=OperationKind.REFUND, parent="S1")
    aw.settle()
    before = aw.snapshot()
    owner = aw.idw.owner
    created = owner.post(
        f"/agencies/{aw.w.a}/clients/{aw.w.a1}/attribution/models",
        json={"operation_id": str(uuid4()), "model": "first_click", "window_days": 7},
    )
    assert created.status_code == 201, created.text
    totals = aw.settle()
    assert totals["rebuilds"] == 1 and totals["revisions"] == 1 and not totals["opened"]
    after = aw.snapshot()
    for table, rows_before in before.items():
        assert set(rows_before) <= set(after[table]), table  # every old row is unchanged
    conversion = aw.conversion("S1")
    assert [item.revision for item in aw.revisions(conversion.id, "first_click_7d_v1")] == [1]
    assert [item.revision for item in aw.revisions(conversion.id, LINEAR)] == [1, 2]
    assert aw.state().generation == 2
    aw.assert_fresh()


def test_av13_currencies_stay_apart(aw):
    buyer, _ = buyer_with_touches(aw, campaigns=("spring",))
    aw.sale("S1", 10_000)
    aw.sale("S2", 2_500, currency=USD, account="shop-usd")
    aw.associate(buyer.assertion, "S1")
    aw.associate(buyer.assertion, "S2", account="shop-usd")
    aw.settle()
    egp = aw.latest(aw.conversion("S1").id)[LINEAR]
    usd = aw.latest(aw.conversion("S2").id)[LINEAR]
    assert (egp.currency, usd.currency) == (EGP, USD)
    # One row per currency: the ledger never adds or converts across currencies.
    assert aw.ledger(LINEAR) == {("spring", "EGP"): (ONE, 10_000), ("spring", "USD"): (ONE, 2_500)}
    aw.assert_fresh()


def _net(aw, operation, account="shop"):
    (net,) = rows(
        aw.w.db,
        select(LedgerTransaction.net).where(
            LedgerTransaction.client_id == aw.w.a1,
            LedgerTransaction.source_account_id == account,
            LedgerTransaction.operation_id == operation,
        ),
    )
    return net


def test_av05_incremental_equals_rebuild_after_every_random_step(aw):
    generator = random.Random(8)
    people = [aw.person(f"p{index}@example.test") for index in range(3)]
    sales: dict[str, int] = {}
    associated: dict[str, object] = {}
    withdrawn: set[int] = set()
    edge = None
    steps = [
        "sale", "touch", "sale", "refund", "lead", "merge", "touch", "withdraw", "sale",
        "unmerge", "grant", "detach", "refund", "touch", "sale", "lead",
    ]  # fmt: skip
    for number, step in enumerate(steps):
        index = generator.randrange(len(people))
        person = people[index]
        if step == "sale":
            operation = f"S{number}"
            sales[operation] = generator.randint(2_000, 90_000)
            aw.sale(operation, sales[operation])
            if generator.random() < 0.75 and index not in withdrawn:
                aw.associate(person.assertion, operation)
                associated[operation] = person
        elif step == "refund" and sales:
            operation = generator.choice(sorted(sales))
            amount = generator.randint(1, sales[operation] // 2)
            sales[operation] -= amount
            aw.sale(f"R{number}", amount, kind=OperationKind.REFUND, parent=operation)
        elif step == "touch":
            aw.touch(person.token, generator.choice([None, "spring", "autumn"]))
        elif step == "lead":
            aw.lead(person.token)
        elif step == "merge" and edge is None:
            edge = aw.merge(people[0].id, people[1].id)
        elif step == "unmerge" and edge is not None:
            aw.unmerge(edge)
            edge = None
        elif step == "withdraw":
            aw.consent(person.token, ATTRIBUTION, "withdrawn")
            withdrawn.add(index)
        elif step == "grant" and withdrawn:
            back = withdrawn.pop()
            aw.consent(people[back].token, ATTRIBUTION, "granted")
        elif step == "detach" and associated:
            operation = sorted(associated)[0]
            del associated[operation]
            if any(
                row.owner_person_id
                for row in aw.conversions()
                if row.sale_operation_id == operation
            ):
                aw.detach(operation)
        aw.settle()
        aw.assert_fresh()
        # Attributed revenue reconciles with the ledger under every model after every step.
        for key in (FIRST, LAST, LINEAR):
            assert sum(minor for _, minor in aw.ledger(key).values()) == sum(sales.values()), step
    # The sequence really exercised ownership changes, leads and unassociated sales.
    every = aw.conversions(every=True)
    reasons = {row.superseded_reason for row in every if row.status == "superseded"}
    assert "owner_changed" in reasons and len(every) > len(aw.conversions())
    assert {row.kind for row in every} == {"sale", "lead"}
    # A real rebuild of the caught-up state stores nothing new for the existing versions.
    before = aw.snapshot()
    owner = aw.idw.owner
    created = owner.post(
        f"/agencies/{aw.w.a}/clients/{aw.w.a1}/attribution/models",
        json={"operation_id": str(uuid4()), "model": "last_click", "window_days": 14},
    )
    assert created.status_code == 201, created.text
    totals = aw.settle()
    assert totals["rebuilds"] == 1 and not totals["opened"] and not totals["superseded"]
    after = aw.snapshot()
    for table, rows_before in before.items():
        assert set(rows_before) <= set(after[table]), table
    new_version = created.json()["id"]
    added = {
        table: [row for row in after[table] if row not in set(before[table])]
        for table in ("attribution_runs",)
    }
    assert added["attribution_runs"] and all(
        new_version in {str(value) for value in row} for row in added["attribution_runs"]
    )
    aw.assert_fresh()


def test_av06_refund_release_chargeback_and_correction_revisions(aw):
    buyer, _ = buyer_with_touches(aw, campaigns=("spring",))
    moment = datetime.now(UTC)
    for operation in ("S1", "S2", "S3"):
        aw.sale(operation, 10_000, when=moment)
        aw.associate(buyer.assertion, operation)
    aw.settle()
    # S1: a refund, then an earlier-effective larger refund releases the first one.
    aw.sale(
        "R1", 6_000, kind=OperationKind.REFUND, parent="S1", when=moment + timedelta(seconds=20)
    )
    aw.settle()
    aw.sale(
        "R2", 7_000, kind=OperationKind.REFUND, parent="S1", when=moment + timedelta(seconds=10)
    )
    aw.settle()
    # S2: a chargeback and its reversal. S3: an audited correction.
    aw.sale("CB", 10_000, kind=OperationKind.CHARGEBACK, parent="S2", when=moment)
    aw.settle()
    aw.sale("CBR", 10_000, kind=OperationKind.CHARGEBACK_REVERSAL, parent="CB", when=moment)
    aw.settle()
    aw.sale(
        "X1",
        -1_000,
        kind=OperationKind.CORRECTION,
        parent="S3",
        when=moment,
        actor="ops",
        reason="fee",
        source_reference="ticket-1",
    )
    aw.settle()
    expected = {"S1": [10_000, 4_000, 3_000], "S2": [10_000, 0, 10_000], "S3": [10_000, 9_000]}
    with Session(aw.w.db.migration) as session:
        releases = session.scalar(
            select(func.count())
            .select_from(LedgerMovement)
            .where(LedgerMovement.client_id == aw.w.a1, LedgerMovement.direction == "release")
        )
    assert releases >= 1  # the stored journal really released the first refund
    for operation, nets in expected.items():
        conversion = aw.conversion(operation)
        revisions = aw.revisions(conversion.id, LINEAR)
        assert [item.verified_net_minor for item in revisions] == nets, operation
        assert all(item.causes == ("revenue_changed",) for item in revisions[1:])
        assert revisions[-1].verified_net_minor == _net(aw, operation)
        assert aw.ledger(LINEAR, conversion_id=conversion.id) == {
            ("spring", "EGP"): (ONE, nets[-1])
        }
    aw.assert_fresh()


def test_av06_a_held_refund_changes_nothing_until_it_posts(aw):
    w = aw.w
    day = datetime.now(UTC)
    append(w, [evidence(w, "700", minor=10_000, when=day, order="8000")])
    aw.settle()
    conversion = aw.conversion("700")
    assert conversion.source_account_id == "paymob-egypt" and conversion.owner_person_id is None
    before = aw.snapshot()
    # A refund carrying another signed order is held: its receipt moves nothing.
    append(
        w, [evidence(w, "777", OperationKind.REFUND, 4_000, when=day, parent="700", order="9001")]
    )
    totals = aw.settle()
    assert not totals["revisions"] and aw.snapshot() == before
    assert aw.state().receipt_ordinal == 2  # the receipt was consumed all the same
    # A settlement of the sale under the refund's order proves the parent: the refund posts.
    append(
        w,
        [
            evidence(
                w,
                "700",
                minor=10_000,
                when=day,
                order="9001",
                classification=EvidenceClass.CONFIRMED_SETTLEMENT,
                delivery="d:settle",
            )
        ],
    )
    aw.settle()
    revisions = aw.revisions(conversion.id, LINEAR)
    assert [item.verified_net_minor for item in revisions] == [10_000, 6_000]
    assert aw.ledger(LINEAR) == {("unknown", "EGP"): (ONE, 6_000)}
    aw.assert_fresh()


def test_av06_a_ledger_generation_change_rebuilds(aw):
    buyer, _ = buyer_with_touches(aw, campaigns=("spring",))
    aw.sale("S1", 10_000)
    aw.associate(buyer.assertion, "S1")
    aw.sale("R1", 2_500, kind=OperationKind.REFUND, parent="S1")
    aw.settle()
    before = aw.snapshot()
    state = aw.state()
    assert (state.ledger_generation, state.receipt_ordinal) == (1, 2)
    assert backfill(aw.w.db.migration, aw.w.a, aw.w.a1, batch_size=50) == "published"
    totals = aw.settle()
    state = aw.state()
    assert totals["rebuilds"] == 1 and state.ledger_generation == 2 and state.generation == 2
    # The same money in the new journal: the rebuild recalculated against the stored history
    # and stored nothing new.
    assert aw.snapshot() == before
    aw.sale("R2", 500, kind=OperationKind.REFUND, parent="S1")
    aw.settle()
    conversion = aw.conversion("S1")
    assert [item.verified_net_minor for item in aw.revisions(conversion.id, LINEAR)] == [
        7_500,
        7_000,
    ]
    aw.assert_fresh()


def _identity(row):
    return (
        row.id,
        row.slot_key,
        row.conversion_key,
        row.kind,
        row.owner_person_id,
        row.source_account_id,
        row.sale_operation_id,
        row.effective_at,
        row.generation,
        row.created_at,
    )


def test_av07_ownership_changes_supersede_without_mutation(aw):
    w = aw.w
    buyer, _ = buyer_with_touches(aw, campaigns=("spring",))
    other = aw.person("other@example.test")
    aw.touch(other.token, "autumn")
    aw.sale("S1", 10_000)
    aw.settle()
    financial = financial_snapshot(w)
    history = [_identity(aw.conversion("S1"))]

    def step(action, owner, reason="owner_changed"):
        action()
        totals = aw.settle()
        assert totals["superseded"] == 1 and totals["opened"] == 1
        every = sorted(aw.conversions(every=True), key=lambda row: row.conversion_key)
        # Earlier conversions keep their identity; only the publication columns changed.
        assert [_identity(row) for row in every[:-1]] == history
        closed = every[-2]
        assert (closed.status, closed.superseded_reason) == ("superseded", reason)
        assert closed.superseded_at is not None
        current = every[-1]
        assert current.status == "active" and current.owner_person_id == owner
        assert current.conversion_key == f"{current.slot_key}.{len(every)}"
        history.append(_identity(current))
        for key in (FIRST, LAST, LINEAR):
            closing = aw.revisions(closed.id, key)[-1]
            assert (closing.status, closing.causes, closing.allocations) == (
                "superseded",
                ("superseded",),
                (),
            )
            assert aw.ledger(key, conversion_id=closed.id) == {}
            # Money is conserved: the sale is credited exactly once.
            assert sum(minor for _, minor in aw.ledger(key).values()) == 10_000
        assert financial_snapshot(w) == financial
        aw.assert_fresh()

    step(lambda: aw.associate(buyer.assertion, "S1"), buyer.id)
    assert aw.credit(aw.latest(aw.conversion("S1").id)[LINEAR]) == {"spring": (ONE, 10_000)}
    edges = []
    step(lambda: edges.append(aw.merge(other.id, buyer.id)), other.id)
    assert aw.credit(aw.latest(aw.conversion("S1").id)[LINEAR]) == {
        "spring": (HALF, 5_000),
        "autumn": (HALF, 5_000),
    }
    step(lambda: aw.unmerge(edges[0]), buyer.id)
    step(lambda: aw.detach("S1"), None)
    assert aw.credit(aw.latest(aw.conversion("S1").id)[LINEAR]) == {"unknown": (ONE, 10_000)}
    assert len(aw.conversions(every=True)) == 5


def _pending_touch(aw):
    """A settled sale that takes effect in an hour, and one later touch not yet processed."""
    buyer, _ = buyer_with_touches(aw, campaigns=("spring",))
    aw.sale("S1", 10_000, when=datetime.now(UTC) + timedelta(hours=1))
    aw.associate(buyer.assertion, "S1")
    aw.settle()
    aw.touch(buyer.token, "autumn")
    return buyer


def test_av11_two_workers_publish_once(aw):
    _pending_touch(aw)
    inner = []
    outer = aw.run(hook=lambda stage: inner.append(aw.run()))
    assert outer["outcome"] == "conflict" and not outer.get("revisions")
    assert [item["outcome"] for item in inner] == ["caught_up"]
    # The eligible touches changed, so each version records one revision exactly once.
    assert inner[0]["revisions"] == 3
    conversion = aw.conversion("S1")
    assert [item.revision for item in aw.revisions(conversion.id, LINEAR)] == [1, 2]
    assert aw.run()["outcome"] == "caught_up"
    aw.assert_fresh()


def test_av11_a_stale_checkpoint_never_publishes(aw):
    buyer = _pending_touch(aw)
    aw.settle()
    version = aw.state().version

    def advance(stage):
        # The sweep read its snapshot; a sale and a complete pass are published meanwhile.
        aw.sale("S2", 4_000)
        aw.associate(buyer.assertion, "S2")
        assert aw.settle()["opened"] == 1

    outer = aw.run(hook=advance)
    assert outer["outcome"] == "conflict"
    assert aw.state().version > version
    assert len(aw.conversions()) == 2
    aw.assert_fresh()


def test_av11_a_concurrent_rebuild_wins_once(aw):
    _pending_touch(aw)
    aw.settle()
    created = aw.idw.owner.post(
        f"/agencies/{aw.w.a}/clients/{aw.w.a1}/attribution/models",
        json={"operation_id": str(uuid4()), "model": "linear", "window_days": 3},
    )
    assert created.status_code == 201
    inner = []
    outer = aw.run(hook=lambda stage: inner.append(aw.run()))
    assert outer["outcome"] == "conflict" and not outer.get("rebuilds")
    assert inner[0]["outcome"] == "caught_up" and inner[0]["rebuilds"] == 1
    state = aw.state()
    assert (state.generation, state.status, state.unit_kind) == (2, "ready", None)
    conversion = aw.conversion("S1")
    assert [item.revision for item in aw.revisions(conversion.id, "linear_3d_v1")] == [1]
    aw.assert_fresh()


def test_av11_a_pruned_feed_forces_a_rebuild(aw):
    buyer = _pending_touch(aw)
    aw.settle()
    aw.touch(buyer.token, "winter")
    with aw.w.db.migration.begin() as connection:
        last = connection.execute(
            select(IdentityFeedState.last_seq).where(IdentityFeedState.client_id == aw.w.a1)
        ).scalar_one()
        connection.execute(
            text("DELETE FROM identity_changes WHERE client_id = :c"), {"c": aw.w.a1}
        )
        connection.execute(
            update(IdentityFeedState)
            .where(IdentityFeedState.client_id == aw.w.a1)
            .values(pruned_through_seq=last)
        )
    assert aw.state().identity_seq < last
    totals = aw.settle()
    assert totals["rebuilds"] == 1
    state = aw.state()
    assert state.identity_seq == last and state.generation == 2
    credited = aw.credit(aw.latest(aw.conversion("S1").id)[LINEAR])
    assert set(credited) == {"spring", "autumn", "winter"}
    aw.assert_fresh()


def test_av16_pass_transaction_and_touch_bounds(aw, monkeypatch):
    w = aw.w
    monkeypatch.setattr(store, "CHUNK_LIMIT", 2)
    monkeypatch.setattr(store, "TOUCH_LIMIT", 3)
    busy = aw.person("busy@example.test")
    for campaign in ("a", "b", "c", "d"):
        aw.touch(busy.token, campaign)
    calm = aw.person("calm@example.test")
    aw.touch(calm.token, "spring")
    for index in range(5):
        aw.sale(f"S{index}", 1_000 + index)
    aw.associate(busy.assertion, "S0")
    aw.associate(calm.assertion, "S1")
    # A pass of three slots runs in transactions of at most two and stops with the explicit
    # bounded outcome; the staged work is not published.
    first = aw.run(budget=3)
    assert (first["outcome"], first["slots"]) == ("bounded", 3)
    state = aw.state()
    assert (state.status, state.generation, state.unit_kind) == ("building", 0, "rebuild")
    assert state.progress_key is not None and state.version == 3  # start, then two chunks
    assert aw.conversions() and all(row.generation == 1 for row in aw.conversions())
    second = aw.run()
    assert second["outcome"] == "caught_up" and second["slots"] == 2 and second["rebuilds"] == 1
    assert aw.state().generation == 1 and len(aw.conversions()) == 5
    # Above the touch bound the person credits unknown explicitly.
    with Session(w.db.migration) as session:
        flags = dict(
            session.execute(
                select(AttributionConversion.sale_operation_id, AttributionRun.touch_bound_exceeded)
                .join(AttributionRun, AttributionRun.conversion_id == AttributionConversion.id)
                .where(AttributionConversion.client_id == w.a1)
                .distinct()
            ).all()
        )
    assert flags == {"S0": True, "S1": False, "S2": False, "S3": False, "S4": False}
    assert aw.credit(aw.latest(aw.conversion("S0").id)[LINEAR]) == {"unknown": (ONE, 1_000)}
    assert aw.credit(aw.latest(aw.conversion("S1").id)[LINEAR]) == {"spring": (ONE, 1_001)}
    # A ledger that is behind its evidence is an explicit state, and nothing changes.
    before = (aw.snapshot(), aw.state().version)
    with Session(w.db.runtime) as session, session.begin():
        clock = lock_revenue(session, w.a1)
        behind = Evidence(
            "d:behind",
            w.a,
            w.a1,
            "shop",
            "S9",
            OperationKind.SALE,
            EvidenceClass.CONFIRMED_CAPTURE,
            Money(5_000, EGP),
            clock,
            clock,
        )
        append_evidence(session, behind, "csv_import", uuid4(), project=False)
    assert aw.run() == {"outcome": "ledger_unavailable"}
    assert (aw.snapshot(), aw.state().version) == before


def test_worker_command_prints_counts_only(aw):
    buyer, _ = buyer_with_touches(aw, campaigns=("spring",))
    aw.sale("S1", 10_000)
    aw.associate(buyer.assertion, "S1")
    result = store.run_pass(aw.w.db.runtime)
    assert result["clients"] == 4 and result["caught_up"] == 4
    assert result["opened"] == 1 and result["revisions"] == 3 and result["rebuilds"] == 4
    assert all(isinstance(value, int) for value in result.values())
    assert set(result) <= {
        "clients",
        "caught_up",
        "bounded",
        "conflict",
        "ledger_unavailable",
        "failed",
        "slots",
        "revisions",
        "opened",
        "superseded",
        "rebuilds",
        "swept",
    }


def test_a_database_error_for_one_client_does_not_stop_the_pass(aw, monkeypatch, caplog):
    w = aw.w
    buyer, _ = buyer_with_touches(aw, campaigns=("spring",))
    aw.sale("S1", 10_000)
    aw.associate(buyer.assertion, "S1")
    original = store.process_client

    def failing(engine, agency_id, client_id, **options):
        if client_id == w.a2:
            raise OperationalError("SELECT 1", {}, Exception("synthetic outage"))
        return original(engine, agency_id, client_id, **options)

    monkeypatch.setattr(store, "process_client", failing)
    caplog.clear()
    result = store.run_pass(w.db.runtime)
    assert result["clients"] == 4 and result["unavailable"] == 1 and result["caught_up"] == 3
    assert result["opened"] == 1  # the other clients were still processed
    assert "attribution_client_failed" in caplog.text
    assert str(w.a2) not in caplog.text and "synthetic outage" not in caplog.text


@pytest.mark.skipif(
    os.environ.get("TRACKING_ATTRIBUTION_MEASURE") != "1",
    reason="Set TRACKING_ATTRIBUTION_MEASURE=1 to record the AV16 measurements.",
)
@pytest.mark.parametrize("size", [50, 200, 1000])
def test_av16_measurements(aw, size):
    """One first pass, one incremental step and one rebuild; observations, not limits."""
    w = aw.w
    people = [aw.person(f"measure{index}@example.test") for index in range(5)]
    for person in people:
        for campaign in ("spring", "autumn", "winter"):
            aw.touch(person.token, campaign)
    moment = datetime.now(UTC) + timedelta(hours=1)
    with Session(w.db.runtime) as session, session.begin():
        clock = lock_revenue(session, w.a1)
        for index in range(size):
            item = Evidence(
                f"d:M{index}",
                w.a,
                w.a1,
                "shop",
                f"M{index}",
                OperationKind.SALE,
                EvidenceClass.CONFIRMED_CAPTURE,
                Money(1_000 + index, EGP),
                moment,
                clock,
            )
            append_evidence(session, item, "csv_import", uuid4(), project=False)
    # Evidence stored before any projection is published by the operator backfill (007-B).
    outcome = None
    for _ in range(50):
        outcome = backfill(w.db.migration, w.a, w.a1, batch_size=500)
        if outcome == "published":
            break
        assert outcome == "interrupted", outcome
    assert outcome == "published"
    for index in range(0, size, 5):  # one sale in five has an owner with three touches
        aw.associate(people[(index // 5) % 5].assertion, f"M{index}")
    statements = [0]

    def count(*_):
        statements[0] += 1

    def measured(action):
        statements[0] = 0
        started = time.perf_counter()
        totals = action()
        return {
            "seconds": round(time.perf_counter() - started, 2),
            "statements": statements[0],
            "slots": totals.get("slots", 0),
            "revisions": totals.get("revisions", 0),
        }

    event.listen(w.db.runtime, "before_cursor_execute", count)
    try:
        first = measured(aw.settle)
        aw.sale("N1", 5_000, when=moment)
        aw.associate(people[0].assertion, "N1")
        aw.touch(people[0].token, "late")
        step = measured(aw.settle)
        created = aw.idw.owner.post(
            f"/agencies/{w.a}/clients/{w.a1}/attribution/models",
            json={"operation_id": str(uuid4()), "model": "linear", "window_days": 7},
        )
        assert created.status_code == 201
        rebuild = measured(aw.settle)
    finally:
        event.remove(w.db.runtime, "before_cursor_execute", count)
    assert len(aw.conversions()) == size + 1
    print(
        "ATTRIBUTION_TIMINGS",
        json.dumps({"conversions": size, "first_pass": first, "step": step, "rebuild": rebuild}),
    )
