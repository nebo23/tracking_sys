"""Synthetic fixtures for the 008-B persisted attribution tests (D-079).

Builds on the 006 identity world: persons with a browser subject and a trusted assertion,
touches with or without a campaign, trusted lead signals, verified sales with their
adjustments, sale associations, worker passes and read helpers over the stored rows. Every
value is synthetic (example.test addresses, fictional operations).
"""

from collections import Counter
from datetime import UTC, datetime
from fractions import Fraction
from types import SimpleNamespace
from uuid import UUID, uuid4

from identity_support import rows
from report_support import append
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.attribution import attribute
from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind
from app.models import (
    AttributionAllocation,
    AttributionConsumerState,
    AttributionConversion,
    AttributionCreditChange,
    AttributionModelVersion,
    AttributionRun,
    IdentityAssertion,
    IdentityLink,
    IdentitySubject,
    RevenueIdentityBinding,
)
from app.services import attribution_records as records
from app.services import attribution_store as store
from app.services.identity_feed import begin_snapshot
from app.services.revenue_identity import association_id

EGP = Currency("EGP", 2)
USD = Currency("USD", 2)
CLASSES = {
    OperationKind.SALE: EvidenceClass.CONFIRMED_CAPTURE,
    OperationKind.REFUND: EvidenceClass.CONFIRMED_ADJUSTMENT,
    OperationKind.CHARGEBACK: EvidenceClass.CONFIRMED_ADJUSTMENT,
    OperationKind.CHARGEBACK_REVERSAL: EvidenceClass.CONFIRMED_ADJUSTMENT,
    OperationKind.CORRECTION: EvidenceClass.AUDITED_CORRECTION,
}
TABLES = (
    AttributionConversion,
    AttributionRun,
    AttributionAllocation,
    AttributionCreditChange,
)
FIRST, LAST, LINEAR = "first_click_30d_v1", "last_click_30d_v1", "linear_30d_v1"


def make_attribution_world(idw) -> SimpleNamespace:
    w = idw.w

    def person(email, *, client=None):
        """A person with one browser subject and one trusted assertion submitted for it."""
        client = client or w.a1
        token = idw.browser_subject(client_id=client)["subject_token"]
        return link(token, email, client=client)

    def link(token, email, *, client=None):
        client = client or w.a1
        assertion_id = uuid4()
        response = idw.via_browser(
            token,
            [idw.identifier("email", email, "email_code")],
            client_id=client,
            assertion_id=assertion_id,
        )
        assert response.status_code == 201, response.text
        (person_id,) = rows(
            w.db,
            select(IdentityLink.subject_id)
            .join(IdentityAssertion, IdentityAssertion.id == IdentityLink.assertion_ref)
            .where(IdentityAssertion.assertion_id == assertion_id),
        )
        return SimpleNamespace(token=token, assertion=assertion_id, id=person_id)

    def touch(token, campaign=None, *, at=None, client=None):
        url = "https://shop.example.test/p"
        if campaign is not None:
            url += f"?utm_campaign={campaign}"
        return idw.event(token, occurred_at=at, payload={"url": url}, client_id=client or w.a1)

    def lead(token, *, at=None, client=None, trusted=True):
        return idw.event(
            token,
            event_type="lead_signal",
            trusted=trusted,
            occurred_at=at,
            client_id=client or w.a1,
        )

    def sale(
        operation,
        minor=10_000,
        *,
        kind=OperationKind.SALE,
        parent=None,
        when=None,
        account="shop",
        currency=EGP,
        client=None,
        **extra,
    ):
        moment = when or datetime.now(UTC)
        item = Evidence(
            f"d:{operation}:{kind.value}:{minor}",
            w.a,
            client or w.a1,
            account,
            operation,
            kind,
            CLASSES[kind],
            Money(minor, currency),
            moment,
            moment,
            parent_operation_id=parent,
            **extra,
        )
        append(w, [item], intake="csv_import")

    def associate(assertion_id, operation, *, account="shop", client=None, expected=None):
        response = idw.ingest.post(
            f"{idw.base}/clients/{client or w.a1}/revenue/identity-associations",
            json={
                "request_id": str(uuid4()),
                "source_account_id": account,
                "sale_operation_id": operation,
                "assertion_id": str(assertion_id),
                "expected_revision": expected,
            },
        )
        assert response.status_code == 201, response.text
        return response

    def consent(token, purpose, state, *, client=None):
        """Record one consent choice of a browser subject (granted, withdrawn or denied)."""
        return idw.browser_subject({purpose: state}, client_id=client or w.a1, token=token)

    def versions_of(*people):
        found = dict(
            rows_of(
                select(IdentitySubject.id, IdentitySubject.version).where(
                    IdentitySubject.id.in_(people)
                )
            )
        )
        return [found[item] for item in people]

    def rows_of(query):
        with Session(w.db.migration) as session:
            return [tuple(row) for row in session.execute(query)]

    def merge(survivor, merged, *, client=None):
        survivor_version, merged_version = versions_of(survivor, merged)
        response = idw.owner.post(
            f"{idw.base}/clients/{client or w.a1}/identity/merges",
            json={
                "operation_id": str(uuid4()),
                "survivor_id": str(survivor),
                "merged_id": str(merged),
                "survivor_version": survivor_version,
                "merged_version": merged_version,
                "reason_code": "same_person_confirmed_by_client",
            },
        )
        assert response.status_code == 201, response.text
        return SimpleNamespace(id=response.json()["merge_id"], survivor=survivor, merged=merged)

    def unmerge(edge, *, client=None):
        survivor_version, merged_version = versions_of(edge.survivor, edge.merged)
        response = idw.owner.post(
            f"{idw.base}/clients/{client or w.a1}/identity/merges/{edge.id}/reversal",
            json={
                "operation_id": str(uuid4()),
                "survivor_version": survivor_version,
                "merged_version": merged_version,
                "reason_code": "data_correction",
            },
        )
        assert response.status_code == 201, response.text

    def detach(operation, *, account="shop", client=None):
        client = client or w.a1
        association = association_id(client, account, operation)
        (revision,) = rows(
            w.db,
            select(func.max(RevenueIdentityBinding.revision)).where(
                RevenueIdentityBinding.client_id == client,
                RevenueIdentityBinding.association_id == association,
            ),
        )
        response = idw.owner.post(
            f"{idw.base}/clients/{client}/revenue/identity-associations/{association}/detach",
            json={
                "operation_id": str(uuid4()),
                "expected_revision": revision,
                "reason_code": "data_correction",
            },
        )
        assert response.status_code == 201, response.text

    def erase(person_id, *, client=None):
        response = idw.owner.post(
            f"{idw.base}/clients/{client or w.a1}/identity/erasures",
            json={"subject_id": str(person_id)},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def run(client=None, **options):
        return store.process_client(w.db.runtime, w.a, client or w.a1, **options)

    def settle(client=None):
        """Run passes until the client is caught up; return the summed counts."""
        totals: Counter = Counter()
        for _ in range(20):
            result = run(client)
            outcome = result.pop("outcome")
            totals.update(result)
            if outcome == "caught_up":
                return totals
            assert outcome == "bounded", outcome
        raise AssertionError("the client never caught up")

    def conversions(client=None, *, every=False):
        query = select(AttributionConversion).where(
            AttributionConversion.client_id == (client or w.a1)
        )
        if not every:
            query = query.where(AttributionConversion.status == "active")
        return rows(
            w.db, query.order_by(AttributionConversion.created_at, AttributionConversion.id)
        )

    def conversion(operation=None, *, event=None, client=None):
        found = [
            row
            for row in conversions(client)
            if (operation is not None and row.sale_operation_id == operation)
            or (event is not None and row.lead_event_id == event)
        ]
        assert len(found) == 1, found
        return found[0]

    def versions(client=None):
        return {
            row.version_key: row
            for row in rows(
                w.db,
                select(AttributionModelVersion).where(
                    AttributionModelVersion.client_id == (client or w.a1)
                ),
            )
        }

    def latest(conversion_id, client=None):
        """The latest stored values of one conversion per version key."""
        keys = {row.id: key for key, row in versions(client).items()}
        with Session(w.db.migration) as session:
            found = store.latest_runs(session, [conversion_id]).get(conversion_id, {})
            return {keys[version_id]: item.values for version_id, item in found.items()}

    def revisions(conversion_id, version_key, client=None):
        version = versions(client)[version_key]
        with Session(w.db.migration, expire_on_commit=False) as session:
            runs = list(
                session.scalars(
                    select(AttributionRun)
                    .where(
                        AttributionRun.conversion_id == conversion_id,
                        AttributionRun.model_version_id == version.id,
                    )
                    .order_by(AttributionRun.revision)
                )
            )
            return [
                store.stored_values(
                    run,
                    session.scalars(
                        select(AttributionAllocation).where(AttributionAllocation.run_id == run.id)
                    ).all(),
                )
                for run in runs
            ]

    def credit(values):
        """Campaign (or recipient) to (share, minor) of a run's credited allocations."""
        return {
            row.campaign_ref or row.recipient: (row.share, row.amount_minor)
            for row in values.allocations
            if row.credited
        }

    def ledger(version_key, client=None, *, conversion_id=None):
        """The reporting ledger summed by campaign (or recipient) and currency."""
        version = versions(client)[version_key]
        query = (
            select(AttributionCreditChange)
            .join(AttributionRun, AttributionRun.id == AttributionCreditChange.run_id)
            .where(AttributionCreditChange.model_version_id == version.id)
        )
        if conversion_id is not None:
            query = query.where(AttributionRun.conversion_id == conversion_id)
        totals: dict = {}
        for row in rows(w.db, query):
            key = (row.campaign_ref or row.recipient, row.currency)
            entry = totals.setdefault(key, [Fraction(0), 0])
            entry[0] += Fraction(row.delta_share_numerator, row.delta_share_denominator)
            entry[1] += row.delta_minor or 0
        return {key: tuple(value) for key, value in totals.items() if value[0] or value[1]}

    def counts(client=None):
        with Session(w.db.migration) as session:
            return {
                table.__tablename__: session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(table.client_id == (client or w.a1))
                )
                for table in TABLES
            }

    def state(client=None):
        (row,) = rows(
            w.db,
            select(AttributionConsumerState).where(
                AttributionConsumerState.client_id == (client or w.a1)
            ),
        )
        return row

    def snapshot(client=None):
        """Every stored attribution row of the client, for byte-identical comparisons."""
        with w.db.migration.connect() as connection:
            return {
                table.__tablename__: sorted(
                    tuple(tuple(value) if isinstance(value, list) else value for value in row)
                    for row in connection.execute(
                        text(
                            f"SELECT * FROM {table.__tablename__} WHERE client_id = :c ORDER BY id"
                        ),
                        {"c": client or w.a1},
                    )
                )
                for table in TABLES
            }

    def assert_fresh(client=None):
        """The stored state equals a from-scratch calculation over the current inputs."""
        client = client or w.a1
        assert store.pending_changes(w.db.runtime, w.a, client) == 0
        with Session(w.db.runtime) as session, session.begin():
            begin_snapshot(session.connection())
            captured = store._capture(session.get(AttributionConsumerState, client))
            ctx = store._Context(session, w.a, client, captured)
            expected = {}
            for slot in ctx.all_slots().values():
                candidate = ctx.candidate(slot)
                if candidate is not None:
                    expected[slot.key] = (slot, candidate)
            stored, runs, _ = ctx.stored(list(ctx.all_slots()))
            assert set(stored) == set(expected)
            for key, (slot, candidate) in expected.items():
                row = stored[key]
                assert row.owner_person_id == candidate.owner
                touches = ctx.journey(candidate.owner)[0] if candidate.owner else []
                engine_conversion = records.engine_conversion(
                    row.id,
                    w.a,
                    client,
                    slot.kind,
                    candidate.owner,
                    row.effective_at,
                    slot.source_account_id,
                    slot.sale_operation_id,
                )
                position = ctx.ledger_ordinal if candidate.sale else None
                for version in ctx.version_rows:
                    engine_version = ctx.engine_versions[version.id]
                    fresh = attribute(
                        engine_conversion,
                        touches,
                        engine_version,
                        sale=candidate.sale,
                        ledger_position=position,
                    )
                    kept = records.reconstruct(
                        engine_conversion,
                        engine_version,
                        runs[row.id][version.id].values,
                        ledger_position=position,
                    )
                    assert kept.outcome == fresh.outcome
        # The reporting ledger equals the latest credited allocations of the open conversions,
        # and every superseded conversion sums to nothing.
        open_ids = {row.id for row in conversions(client)}
        for key, version in versions(client).items():
            if version.status != "active":
                continue  # a retired version keeps its history and receives no closing revision
            for row in conversions(client, every=True):
                booked = ledger(key, client, conversion_id=row.id)
                if row.id not in open_ids:
                    assert booked == {}, (key, row.superseded_reason, booked)
                    continue
                values = latest(row.id, client).get(key)
                if values is None:
                    continue
                current: dict = {}
                for item in values.allocations:
                    if item.credited:
                        code = values.currency.code if item.amount_minor is not None else None
                        entry = current.setdefault(
                            (item.campaign_ref or item.recipient, code), [Fraction(0), 0]
                        )
                        entry[0] += item.share
                        entry[1] += item.amount_minor or 0
                assert booked == {k: tuple(v) for k, v in current.items() if v[0] or v[1]}

    return SimpleNamespace(
        w=w,
        idw=idw,
        person=person,
        link=link,
        touch=touch,
        lead=lead,
        sale=sale,
        associate=associate,
        consent=consent,
        merge=merge,
        unmerge=unmerge,
        detach=detach,
        erase=erase,
        run=run,
        settle=settle,
        conversions=conversions,
        conversion=conversion,
        versions=versions,
        latest=latest,
        revisions=revisions,
        credit=credit,
        ledger=ledger,
        counts=counts,
        state=state,
        snapshot=snapshot,
        assert_fresh=assert_fresh,
    )


def money(values, key) -> int:
    return values[key][1]


def new_id() -> UUID:
    return uuid4()
