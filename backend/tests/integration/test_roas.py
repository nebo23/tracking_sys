"""ROAS over stored spend facts on disposable PostgreSQL (specification 014-C, D-064 decision D11).

Spend facts come from the 014-A synthetic sync and are read back from ad_spend_facts; credit
comes from 008-A runs over synthetic journeys whose touches carry Meta's dynamic URL parameters
(utm_source=meta, utm_campaign={{campaign.id}}, utm_content={{ad.id}}) on real 007-A ledger
transactions. Cases T-40 to T-47 of the entry review section 7.3. No case contacts Meta.
"""

from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_ad_spend import (
    ACCOUNT,
    NEW_YORK,
    OTHER,
    TODAY,
    _connected,
    _sync,
    _work,
    make_ads_lab,
)

from app.advertising.roas import Period, facts_from_rows, roas_report
from app.attribution import (
    Association,
    AttributionModel,
    EvidenceClass,
    ModelVersion,
    Touchpoint,
    attribute,
    sale_conversion,
    sale_state,
)
from app.connectors.synthetic_meta_ads import CLOCK
from app.ledger import Currency, Evidence, Money, OperationKind, calculate
from app.ledger import EvidenceClass as LedgerClass
from app.models import AdObject, AdSpendFact, ConnectorCheckpoint
from app.privacy.consent import ConsentState

pytestmark = pytest.mark.integration


@pytest.fixture
def ads(authenticated_world, api, tmp_path):
    return make_ads_lab(authenticated_world, api, tmp_path)


PERIOD = Period(date(2026, 11, 1), date(2026, 11, 7))
CAMPAIGN, ADSET, AD, SECOND = "111001", "211001", "311001", "321001"
VERSIONS = (
    ModelVersion("first-v1", AttributionModel.FIRST_CLICK),
    ModelVersion("last-v1", AttributionModel.LAST_CLICK),
    ModelVersion("linear-v1", AttributionModel.LINEAR),
)
LOCAL = ZoneInfo(NEW_YORK)


def _touch(world, identifier, when, *, source="meta", campaign=CAMPAIGN, content=AD):
    return Touchpoint(
        identifier,
        world.a,
        world.a1,
        "person-1",
        EvidenceClass.CAMPAIGN_INTERACTION,
        when,
        Association.ASSIGNED,
        ConsentState.GRANTED,
        source,
        campaign,
        content,
    )


def _ledger(world, operation, sale_at, amount=4000, currency="USD", refund=0):
    unit = Currency(currency, 2)
    records = [
        Evidence(
            f"d-{operation}",
            world.a,
            world.a1,
            "acct_shop",
            operation,
            OperationKind.SALE,
            LedgerClass.CONFIRMED_CAPTURE,
            Money(amount, unit),
            sale_at,
            sale_at,
        )
    ]
    if refund:
        records.append(
            Evidence(
                f"r-{operation}",
                world.a,
                world.a1,
                "acct_shop",
                f"refund-{operation}",
                OperationKind.REFUND,
                LedgerClass.CONFIRMED_ADJUSTMENT,
                Money(refund, unit),
                sale_at + timedelta(hours=2),
                sale_at + timedelta(hours=2),
                parent_operation_id=operation,
            )
        )
    return calculate(records)


def _run(world, operation, sale_at, touches, version, **ledger):
    calculated = _ledger(world, operation, sale_at, **ledger)
    (transaction,) = calculated.transactions
    conversion = sale_conversion(transaction, conversion_id=f"c-{operation}", person_id="person-1")
    return attribute(conversion, touches, version, sale=sale_state(calculated, conversion))


def _stored(lab, connection):
    with Session(lab.w.db.migration) as session:
        facts = facts_from_rows(
            session.scalars(select(AdSpendFact).where(AdSpendFact.connection_id == connection))
        )
        objects = {
            row.object_id: (row.campaign_id, row.adset_id)
            for row in session.scalars(
                select(AdObject).where(AdObject.connection_id == connection, AdObject.level == "ad")
            )
        }
        checkpoint = session.scalar(
            select(ConnectorCheckpoint).where(
                ConnectorCheckpoint.connection_id == connection,
                ConnectorCheckpoint.stream == "ad_daily",
            )
        )
    covered = (
        checkpoint.covered_from.astimezone(LOCAL).date(),
        checkpoint.complete_through.astimezone(LOCAL).date() - timedelta(days=1),
    )
    return facts, objects, covered


def _report(lab, connection, runs, version, as_of=CLOCK + timedelta(days=60), **extra):
    facts, objects, covered = _stored(lab, connection)
    return roas_report(
        facts,
        runs,
        agency_id=lab.w.a,
        client_id=lab.w.a1,
        connection_id=connection,
        period=PERIOD,
        zone=NEW_YORK,
        model_version=version,
        as_of=as_of,
        covered=covered,
        objects=objects,
        **extra,
    )


def _ad_rows(report):
    return {row.object_id: row for row in report.rows if row.level == "ad"}


SALE = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)


def test_roas_rows_per_model_over_stored_spend(ads):
    # T-40, T-42, T-45: rows per ad, ad set and campaign for each model separately with their
    # labels; spend without credit gives 0; credit without the convention or for another
    # account's ad is unmatched.
    w = ads.w
    connection = _connected(ads)
    touches = [
        _touch(w, "t-first", SALE - timedelta(days=3)),
        _touch(w, "t-last", SALE - timedelta(days=1), content=SECOND),
    ]
    for version in VERSIONS:
        runs = [
            _run(w, "s1", SALE, touches, version),
            _run(
                w, "s2", SALE, [_touch(w, "t-name", SALE, campaign="Synthetic campaign")], version
            ),
            _run(
                w,
                "s3",
                SALE,
                [_touch(w, "t-other", SALE, content="311002", campaign="111002")],
                version,
            ),
        ]
        report = _report(ads, connection, runs, version)
        rows = _ad_rows(report)
        # Seven local days of 10.00 for each ad.
        assert {ad: row.spend.minor for ad, row in rows.items()} == {AD: 7000, SECOND: 7000}
        credit = {
            AttributionModel.FIRST_CLICK: (4000, 0),
            AttributionModel.LAST_CLICK: (0, 4000),
            AttributionModel.LINEAR: (2000, 2000),
        }[version.model]
        assert (rows[AD].credited.minor, rows[SECOND].credited.minor) == credit
        assert rows[AD].roas == Fraction(credit[0], 7000)
        assert all(
            (row.model, row.model_version, row.period, row.basis, row.currency)
            == (version.model, version.version_id, PERIOD, "conversion_date", "USD")
            for row in report.rows
        )
        levels = {(row.level, row.object_id) for row in report.rows}
        assert levels == {("ad", AD), ("ad", SECOND), ("adset", ADSET), ("campaign", CAMPAIGN)}
        assert next(row for row in report.rows if row.level == "campaign").roas == Fraction(
            4000, 14000
        )
        assert [(item.minor, item.currency.code) for item in report.unmatched] == [(8000, "USD")]
    zero = _ad_rows(_report(ads, connection, [], VERSIONS[0]))
    assert (zero[AD].roas, zero[AD].roas_text) == (Fraction(0), "0.0000")


def test_zero_spend_currency_mismatch_and_spend_states(ads):
    # T-41, T-43, T-44: zero spend has no value; a currency mismatch has no value; provisional
    # and incomplete spend are marked.
    w = ads.w
    connection = _connected(ads)
    for offset in range(7):
        ads.meta.override(ACCOUNT, SECOND, PERIOD.since + timedelta(days=offset), spend="0.00")
    ads.meta.override(ACCOUNT, AD, PERIOD.until, spend="10.001")
    # The incremental re-read covers the last 28 days, the period included.
    _sync(ads, "owner_a", w.a, w.a1, connection, "ad_daily")
    _work(ads)
    version = VERSIONS[0]
    runs = [
        _run(w, "s1", SALE, [_touch(w, "t1", SALE - timedelta(days=1), content=SECOND)], version),
        _run(w, "s2", SALE, [_touch(w, "t2", SALE - timedelta(days=1))], version, currency="EUR"),
    ]
    rows = _ad_rows(_report(ads, connection, runs, version))
    assert (rows[SECOND].roas, rows[SECOND].reason, rows[SECOND].credited.minor) == (
        None,
        "zero_spend",
        4000,
    )
    assert (rows[AD].roas, rows[AD].reason) == (None, "currency_mismatch")
    # The refused fact of 2026-11-07 makes the ad's spend incomplete.
    assert rows[AD].spend_state == "incomplete"
    assert rows[SECOND].spend_state == "complete"
    # At the synthetic clock the period is inside the 28-day re-read: provisional.
    early = _ad_rows(_report(ads, connection, [], version, as_of=CLOCK))
    assert early[SECOND].spend_state == "provisional"


def test_refund_and_local_period_bounds(ads):
    # T-46, T-47: a refund lowers the credited net through the 008-A revision; a sale at 23:30
    # local time on the last day falls in the period, one at 00:30 the next day does not.
    w = ads.w
    connection = _connected(ads)
    version = VERSIONS[0]
    touch = [_touch(w, "t1", SALE - timedelta(days=2))]
    before = _ad_rows(_report(ads, connection, [_run(w, "s1", SALE, touch, version)], version))
    after = _ad_rows(
        _report(ads, connection, [_run(w, "s1", SALE, touch, version, refund=1500)], version)
    )
    assert (before[AD].roas, after[AD].roas) == (Fraction(4000, 7000), Fraction(2500, 7000))
    last_evening = datetime(2026, 11, 7, 23, 30, tzinfo=LOCAL)
    next_morning = datetime(2026, 11, 8, 0, 30, tzinfo=LOCAL)
    runs = [
        _run(
            w, "late", last_evening, [_touch(w, "ta", last_evening - timedelta(hours=5))], version
        ),
        _run(
            w, "next", next_morning, [_touch(w, "tb", next_morning - timedelta(hours=5))], version
        ),
    ]
    rows = _ad_rows(_report(ads, connection, runs, version))
    assert rows[AD].credited.minor == 4000
    assert TODAY > PERIOD.until and OTHER != ACCOUNT
