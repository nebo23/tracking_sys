"""Pure 016-A reporting contracts (specification 016-A, D-072; verification matrix V04-V11, V16).

Catalog, period arithmetic, aggregation, comparison and CSV serialization, tested in memory with
synthetic inputs. The database, permission, pagination, race and bound cases run against the
disposable PostgreSQL service in tests/integration/test_reports.py.
"""

import csv
import io
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from app.connectors import instagram, synthetic_instagram, synthetic_youtube, youtube
from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind, calculate
from app.reporting import csv_export
from app.reporting.catalog import (
    CATALOG,
    FAMILIES,
    INSTAGRAM,
    YOUTUBE,
    MetricClass,
    family_of,
)
from app.reporting.common import PageRequest, ReportError, compare_values, page_of, percent_change
from app.reporting.digest import canonical, digest_of
from app.reporting.periods import Period, local_date
from app.reporting.revenue import RevenueInputs, revenue_report
from app.reporting.social import SocialInputs, SocialRecord, StreamState, social_report
from app.reporting.spend import SpendFactInput, SpendInputs, spend_report

AGENCY = UUID("00000000-0000-4000-8000-00000000a016")
CLIENT = UUID("00000000-0000-4000-8000-00000000c016")
CONNECTION = UUID("00000000-0000-4000-8000-00000000d016")
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
NOVEMBER = Period(date(2026, 11, 1), date(2026, 11, 3))
EGP = Currency("EGP", 2)
USD = Currency("USD", 2)


# --- catalog (V04, V05) -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("family", "capability"),
    [
        (INSTAGRAM, synthetic_instagram.CAPABILITY),
        (INSTAGRAM, instagram.CAPABILITY),
        (YOUTUBE, synthetic_youtube.CAPABILITY),
        (YOUTUBE, youtube.CAPABILITY),
    ],
)
def test_catalog_covers_every_declared_metric_exactly(family, capability):
    declared = set()
    for spec in capability.stream_specs():
        for metric in capability.stream_metrics(spec.name):
            entry = CATALOG[(family.name, spec.name, metric.name)]
            declared.add((family.name, spec.name, metric.name))
            assert entry.unit == metric.unit
            assert entry.product_types == metric.product_types
            assert entry.definition_changes == metric.definition_changes
            if not metric.additive:
                assert entry.metric_class is MetricClass.RATIO
        assert family.delay_hours(spec.name) == capability.stream_delay_hours(spec.name)
    assert declared == {key for key in CATALOG if key[0] == family.name}
    assert family.freshness_hours == capability.freshness_hours
    assert family.day_zone == (capability.day_zone or "UTC")
    assert family_of(capability.provider) is family


def test_catalog_classes_follow_the_reviewed_semantics():
    def kind(*key):
        return CATALOG[key].metric_class

    assert kind("instagram", "account", "reach") is MetricClass.DAILY_NON_ADDITIVE
    assert kind("instagram", "account", "accounts_engaged") is MetricClass.DAILY_NON_ADDITIVE
    assert kind("instagram", "account", "views") is MetricClass.DAILY_ADDITIVE
    assert kind("instagram", "account", "follows_and_unfollows") is MetricClass.UNREVIEWED
    assert kind("instagram", "media", "reach") is MetricClass.LIFETIME_NON_ADDITIVE
    assert kind("instagram", "media", "reels_skip_rate") is MetricClass.RATIO
    assert kind("youtube", "channel", "subscriberCount") is MetricClass.SNAPSHOT
    assert kind("youtube", "videos", "viewCount") is MetricClass.SNAPSHOT
    assert kind("youtube", "channel_daily", "averageViewDuration") is MetricClass.RATIO
    assert kind("youtube", "video_totals", "views") is MetricClass.LIFETIME_ADDITIVE
    assert family_of("synthetic") is None and family_of("meta_ads") is None
    assert set(FAMILIES) == {"instagram", "youtube"}


# --- periods (V06) ------------------------------------------------------------------------------


def test_periods_are_half_open_bounded_calendar_dates():
    period = Period(date(2026, 11, 1), date(2026, 12, 2))
    assert period.days == 31 and period.dates()[-1] == date(2026, 12, 1)
    assert period.previous() == Period(date(2026, 10, 1), date(2026, 11, 1))
    for start, end in (
        (date(2026, 11, 2), date(2026, 11, 2)),
        (date(2026, 11, 3), date(2026, 11, 2)),
        (date(2026, 11, 1), date(2026, 12, 3)),
        (date(1999, 12, 31), date(2000, 1, 2)),
        (date(2100, 1, 1), date(2100, 1, 2)),
    ):
        with pytest.raises(ReportError) as error:
            Period(start, end)
        assert error.value.code == "invalid_period"
    with pytest.raises(ReportError):
        Period(datetime(2026, 11, 1, tzinfo=UTC), date(2026, 11, 2))


def test_pacific_daylight_saving_days_stay_calendar_days():
    spring = Period(date(2026, 3, 8), date(2026, 3, 9))
    start, end = spring.bounds("America/Los_Angeles")
    assert end - start == timedelta(hours=23)
    assert start == datetime(2026, 3, 8, 8, tzinfo=UTC)
    fall = Period(date(2026, 11, 1), date(2026, 11, 2))
    start, end = fall.bounds("America/Los_Angeles")
    assert end - start == timedelta(hours=25)
    assert start == datetime(2026, 11, 1, 7, tzinfo=UTC)
    assert local_date(datetime(2026, 11, 2, 7, 59, tzinfo=UTC), "America/Los_Angeles") == date(
        2026, 11, 1
    )
    with pytest.raises(ReportError) as error:
        spring.bounds("Mars/Olympus")
    assert error.value.code == "invalid_zone"


# --- social helpers -----------------------------------------------------------------------------


def _ig_day(day: date, fetched: datetime | None = None, **metrics) -> SocialRecord:
    observed = datetime.combine(day, datetime.min.time(), UTC)
    return SocialRecord(
        "account", f"day-{day}", observed, fetched or observed + timedelta(days=3), metrics
    )


def _social(records, family=INSTAGRAM, streams=None, **extra) -> SocialInputs:
    if streams is None:
        streams = {
            family.daily_stream: StreamState(
                family.daily_stream,
                datetime(2026, 10, 1, tzinfo=UTC),
                datetime(2026, 11, 15, tzinfo=UTC),
                last_success_at=NOW - timedelta(hours=1),
            )
        }
    values = {
        "family": family,
        "connection_id": CONNECTION,
        "provider": family.providers[1],
        "status": "active",
        "generation": 1,
        "adapter_available": True,
        "adapter_version": "synthetic",
        "connection_last_success": NOW - timedelta(hours=1),
        "streams": streams,
        "records": tuple(records),
        "source_rows": len(records),
        "digest": "0" * 64,
    }
    values.update(extra)
    return SocialInputs(**values)


def _total(result, metric, period="current"):
    return next(
        item for item in result.totals if item["metric"] == metric and item["period"] == period
    )


# --- social daily (V04, V07, V08) ---------------------------------------------------------------


def test_reach_stays_two_observations_while_views_total_twenty_two():
    records = [
        _ig_day(date(2026, 11, 1), reach=10, views=10),
        _ig_day(date(2026, 11, 2), reach=12, views=12),
    ]
    result = social_report(_social(records), "daily", NOVEMBER, None, None, NOW)
    reach = _total(result, "reach")
    assert reach["value"] is None and reach["reason"] == "non_additive"
    assert reach["available_days"] == 2
    views = _total(result, "views")
    assert (views["value"], views["status"], views["reason"]) == (22, "complete", None)
    rows = [row for row in result.rows() if row["metric"] == "reach"]
    assert [row["value"] for row in rows] == [10, 12]
    assert result.total_rows == len(result.totals) * 2
    assert result.basis == "native_daily_activity" and result.day_zone == "UTC"


def test_absent_days_are_never_zero_and_partial_totals_are_labeled():
    records = [_ig_day(date(2026, 11, 1), views=10)]
    covered = social_report(_social(records), "daily", NOVEMBER, None, None, NOW)
    views = _total(covered, "views")
    assert (views["value"], views["status"], views["reason"]) == (10, "partial", "incomplete_days")
    second = [row for row in covered.rows() if row["metric"] == "views"][1]
    assert (second["value"], second["availability"], second["reason"]) == (
        None,
        "missing",
        "no_record",
    )
    likes = _total(covered, "likes")
    assert likes["value"] is None and likes["reason"] == "missing"
    uncovered = social_report(_social(records, streams={}), "daily", NOVEMBER, None, None, NOW)
    second = [row for row in uncovered.rows() if row["metric"] == "views"][1]
    assert (second["availability"], second["reason"]) == ("not_synced", "outside_coverage")
    stream = uncovered.source_status["streams"][0]
    assert stream["coverage"]["current"] == "not_synced"
    assert stream["freshness"]["state"] == "never_synced"
    nothing = social_report(_social([], streams={}), "daily", NOVEMBER, None, None, NOW)
    assert all(item["value"] is None for item in nothing.totals)
    assert {item["reason"] for item in nothing.totals} == {"not_synced", "non_additive"}


def test_stored_missing_reasons_and_invalid_values_stay_distinct():
    record = replace(
        _ig_day(date(2026, 11, 1), views=True, likes=-1, comments=3),
        unavailable={"follows_and_unfollows": "below_threshold", "saves": "not_returned"},
    )
    duplicate = replace(_ig_day(date(2026, 11, 2), views=4), object_id="other-day")
    result = social_report(
        _social([record, _ig_day(date(2026, 11, 2), views=5), duplicate]),
        "daily",
        NOVEMBER,
        None,
        None,
        NOW,
    )
    rows = {(row["metric"], row["date"]): row for row in result.rows()}
    first = date(2026, 11, 1)
    assert rows["views", first]["reason"] == "invalid_value"
    assert rows["likes", first]["reason"] == "invalid_value"
    assert rows["saves", first]["reason"] == "not_returned"
    assert rows["comments", first]["value"] == 3
    assert rows["views", date(2026, 11, 2)]["reason"] == "conflicting_records"
    excluded = result.source_status["excluded_metrics"]
    assert excluded == [
        {"stream": "account", "metric": "follows_and_unfollows", "reason": "semantics_unreviewed"}
    ]
    assert ("follows_and_unfollows", first) not in rows


def test_comparison_needs_complete_fresh_final_compatible_periods():
    days = Period(date(2026, 11, 3), date(2026, 11, 5))
    before = days.previous()
    records = [
        _ig_day(date(2026, 11, 1), views=10, likes=0),
        _ig_day(date(2026, 11, 2), views=10, likes=0),
        _ig_day(date(2026, 11, 3), views=15, likes=4),
        _ig_day(date(2026, 11, 4), views=15, likes=4),
    ]
    result = social_report(_social(records), "daily", days, before, None, NOW)
    by_metric = {item["metric"]: item for item in result.comparison}
    assert by_metric["views"]["difference"] == 10
    assert by_metric["views"]["percent_change"] == "50.00"
    assert by_metric["views"]["comparable"] is True
    assert by_metric["likes"]["difference"] == 8 and by_metric["likes"]["percent_change"] is None
    assert by_metric["likes"]["reason"] == "zero_baseline"
    assert by_metric["reach"]["reason"] == "non_additive"
    assert by_metric["comments"]["reason"] == "unavailable"
    assert _total(result, "views", "previous")["value"] == 20
    stale = _social(
        records,
        streams={
            "account": replace(
                _social([]).streams["account"], last_success_at=NOW - timedelta(days=3)
            )
        },
    )
    views = next(
        item
        for item in social_report(stale, "daily", days, before, None, NOW).comparison
        if item["metric"] == "views"
    )
    assert (views["current_value"], views["previous_value"]) == (30, 20)
    assert (views["difference"], views["percent_change"], views["reason"]) == (None, None, "stale")
    partial = social_report(_social(records[1:]), "daily", days, before, None, NOW)
    views = next(item for item in partial.comparison if item["metric"] == "views")
    assert views["reason"] == "partial" and views["previous_value"] == 10
    recent = social_report(
        _social(records), "daily", days, before, None, datetime(2026, 11, 5, 12, tzinfo=UTC)
    )
    views = next(item for item in recent.comparison if item["metric"] == "views")
    assert views["reason"] == "provisional"
    assert _total(recent, "views")["provisional"] is True
    assert _total(recent, "views")["status"] == "complete"


def test_youtube_days_follow_pacific_dates_and_definition_changes():
    def day(value: date, views: int) -> SocialRecord:
        observed = synthetic_youtube.pacific_start(value)
        return SocialRecord("channel_daily", f"day-{value}", observed, NOW, {"views": views})

    window = Period(date(2026, 11, 14), date(2026, 11, 18))
    records = [day(window.start + timedelta(days=offset), 100) for offset in range(4)]
    streams = {
        "channel_daily": StreamState(
            "channel_daily",
            synthetic_youtube.pacific_start(date(2026, 10, 1)),
            synthetic_youtube.pacific_start(date(2026, 11, 18)),
            last_success_at=NOW,
        )
    }
    inputs = _social(records, family=YOUTUBE, streams=streams)
    result = social_report(inputs, "daily", window, None, ["views"], NOW)
    views = _total(result, "views")
    assert views["value"] is None and views["reason"] == "definition_changed"
    rows = list(result.rows())
    assert [row["definition_since"] for row in rows] == [date(2026, 8, 27)] * 2 + [
        date(2026, 11, 16)
    ] * 2
    later = Period(date(2026, 11, 16), date(2026, 11, 18))
    result = social_report(inputs, "daily", later, later.previous(), ["views"], NOW)
    assert _total(result, "views")["value"] == 200
    assert result.comparison[0]["reason"] == "definition_changed"
    assert result.day_zone == "America/Los_Angeles"
    with pytest.raises(ReportError) as error:
        social_report(inputs, "daily", window, None, ["subscriberCount"], NOW)
    assert error.value.code == "unsupported_metric"


# --- social content cohort (V05) ----------------------------------------------------------------


def _media(object_id, published, product, fetched=NOW, **metrics) -> SocialRecord:
    return SocialRecord(
        "media", object_id, published, fetched, metrics, {}, product, None, published
    )


def test_content_cohort_reports_lifetime_values_without_period_claims():
    published = datetime(2026, 11, 1, 10, tzinfo=UTC)
    records = [
        _media("901", published, "FEED", views=500, reach=300, profile_visits=7),
        _media(
            "902",
            published + timedelta(hours=5),
            "REELS",
            views=700,
            reach=400,
            ig_reels_avg_watch_time=1200,
        ),
        _media("903", published + timedelta(days=1), "UNSPECIFIED", views=1),
        _media("904", datetime(2026, 11, 3, tzinfo=UTC), "FEED", views=99),
    ]
    streams = {
        "media": StreamState(
            "media",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 11, 19, tzinfo=UTC),
            last_success_at=NOW,
        )
    }
    result = social_report(
        _social(records, streams=streams), "content_cohort", NOVEMBER, None, None, NOW
    )
    assert result.basis == "published_cohort_lifetime" and result.comparison is None
    views = next(i for i in result.totals if i["stream"] == "media" and i["metric"] == "views")
    assert (views["value"], views["status"], views["applicable_contents"]) == (1200, "complete", 2)
    rows = list(result.rows())
    assert {row["content_id"] for row in rows} == {"901", "902", "903"}
    unknown = [row for row in rows if row["content_id"] == "903"]
    assert {row["availability"] for row in unknown} == {"unsupported"}
    assert {row["reason"] for row in unknown} == {"product_type"}
    reach = next(i for i in result.totals if i["stream"] == "media" and i["metric"] == "reach")
    assert reach["value"] is None and reach["reason"] == "non_additive"
    watch = next(
        i
        for i in result.totals
        if i["stream"] == "media" and i["metric"] == "ig_reels_avg_watch_time"
    )
    assert watch["value"] is None and watch["reason"] == "non_additive"
    visits = next(
        i for i in result.totals if i["stream"] == "media" and i["metric"] == "profile_visits"
    )
    assert (visits["value"], visits["unsupported_contents"]) == (7, 2)
    stories = next(i for i in result.totals if i["stream"] == "stories")
    assert stories["reason"] == "no_content" and stories["value"] is None
    with pytest.raises(ReportError) as error:
        social_report(
            _social(records, streams=streams),
            "content_cohort",
            NOVEMBER,
            NOVEMBER.previous(),
            None,
            NOW,
        )
    assert error.value.code == "comparison_unsupported"
    uncovered = social_report(
        _social(records, streams={}), "content_cohort", NOVEMBER, None, None, NOW
    )
    views = next(i for i in uncovered.totals if i["stream"] == "media" and i["metric"] == "views")
    assert (views["value"], views["status"], views["reason"]) == (
        1200,
        "partial",
        "inventory_unproven",
    )


def test_content_cohort_total_is_complete_only_with_proven_inventory():
    published = datetime(2026, 11, 1, 10, tzinfo=UTC)
    records = [
        _media("901", published, "FEED", views=500, likes=3),
        _media("902", published, "FEED", views=700, likes=4),
    ]
    proven = {
        "media": StreamState(
            "media", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 11, 19, tzinfo=UTC)
        )
    }
    result = social_report(
        _social(records, streams=proven), "content_cohort", NOVEMBER, None, ["views"], NOW
    )
    views = next(i for i in result.totals if i["stream"] == "media")
    assert (views["value"], views["status"]) == (1200, "complete")
    short = {
        "media": StreamState(
            "media", datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 19, tzinfo=UTC)
        )
    }
    result = social_report(
        _social(records, streams=short), "content_cohort", NOVEMBER, None, ["views"], NOW
    )
    views = next(i for i in result.totals if i["stream"] == "media")
    assert (views["value"], views["status"], views["reason"]) == (
        1200,
        "partial",
        "inventory_unproven",
    )


def test_youtube_cohort_uses_publication_times_and_keeps_averages_apart():
    published = datetime(2026, 11, 1, 18, tzinfo=UTC)
    totals = SocialRecord(
        "video_totals",
        "v1",
        datetime(2026, 11, 15, 8, tzinfo=UTC),
        NOW,
        {"views": 1000, "averageViewDuration": 61},
        {},
        "SHORTS",
        None,
        published,
    )
    absent = SocialRecord("video_totals", "v2", None, None, published_at=published, present=False)
    streams = {
        name: StreamState(name, NOW - timedelta(days=1), NOW - timedelta(hours=1))
        for name in ("videos", "video_totals")
    }
    result = social_report(
        _social([totals, absent], family=YOUTUBE, streams=streams, publication_unknown=1),
        "content_cohort",
        Period(date(2026, 11, 1), date(2026, 11, 2)),
        None,
        None,
        NOW,
    )
    views = next(item for item in result.totals if item["metric"] == "views")
    assert (views["value"], views["status"], views["reason"]) == (
        1000,
        "partial",
        "incomplete_contents",
    )
    duration = next(item for item in result.totals if item["metric"] == "averageViewDuration")
    assert duration["value"] is None and duration["reason"] == "non_additive"
    missing = [row for row in result.rows() if row["content_id"] == "v2"]
    assert {row["reason"] for row in missing} == {"no_record"}
    assert result.source_status["publication_unknown"] == 1
    assert [item["stream"] for item in result.source_status["streams"]] == [
        "video_totals",
        "videos",
    ]


# --- spend (V11) --------------------------------------------------------------------------------


def _fact(ad, day, currency, minor, **extra) -> SpendFactInput:
    values = {
        "ad_id": ad,
        "adset_id": extra.pop("adset", None),
        "campaign_id": extra.pop("campaign", None),
        "spend_date": day,
        "time_zone": "Africa/Cairo",
        "currency": currency,
        "spend_minor": minor,
        "impressions": 10,
        "clicks": 1,
        "refusal": None,
        "provisional_until": NOW - timedelta(days=1),
    }
    values.update(extra)
    return SpendFactInput(**values)


def _spend(facts, **extra) -> SpendInputs:
    values = {
        "connection_id": CONNECTION,
        "provider": "synthetic_meta_ads",
        "status": "active",
        "generation": 1,
        "adapter_available": True,
        "adapter_version": "synthetic",
        "zone": "Africa/Cairo",
        "account": None,
        "covered_from": date(2026, 10, 1),
        "complete_through": date(2026, 11, 10),
        "in_progress": False,
        "last_success_at": NOW,
        "sync": {"state": "idle", "reason": None},
        "connection_last_success": NOW,
        "facts": tuple(facts),
        "source_rows": len(facts),
        "digest": "0" * 64,
    }
    values.update(extra)
    return SpendInputs(**values)


def test_spend_keeps_currencies_and_missing_objects_apart():
    first, second = date(2026, 11, 1), date(2026, 11, 2)
    facts = [
        _fact("31", first, "EGP", 1000, adset="21"),
        _fact("31", second, "USD", 250, adset="21"),
        _fact("32", first, "EGP", 500),
    ]
    result = spend_report(_spend(facts), "adset", NOVEMBER, None, NOW)
    rows = list(result.rows())
    assert [(row["object_id"], row["currency"]) for row in rows] == [
        (None, "EGP"),
        ("21", "EGP"),
        ("21", "USD"),
    ]
    assert result.total_rows == 3
    totals = {item["currency"]: item for item in result.totals}
    assert totals["EGP"]["spend"] == {"minor": 1500, "decimal": "15.00"}
    assert totals["USD"]["spend"] == {"minor": 250, "decimal": "2.50"}
    assert totals["EGP"]["status"] == "complete"
    page, info = page_of(result.rows(), result.total_rows, PageRequest(2, 1))
    assert page[0]["currency"] == "EGP" and page[0]["object_id"] == "21"
    assert info["total_pages"] == 3


def test_spend_refusals_coverage_and_empty_periods_are_explicit():
    facts = [
        _fact("31", date(2026, 11, 1), "EGP", 1000),
        _fact("32", date(2026, 11, 1), None, None, refusal="unsupported_currency"),
    ]
    result = spend_report(_spend(facts), "ad", NOVEMBER, None, NOW)
    current = result.source_status["periods"][0]
    assert current["refused"] == {"unparseable_amount": 0, "unsupported_currency": 1}
    assert result.totals[0]["status"] == "partial"
    assert result.totals[0]["reason"] == "refused_facts"
    empty = spend_report(_spend([]), "ad", NOVEMBER, NOVEMBER.previous(), NOW)
    assert empty.totals == [] and empty.comparison == []
    assert empty.source_status["periods"][0]["reason"] == "no_spend_facts"
    late = spend_report(
        _spend([_fact("31", date(2026, 11, 1), "EGP", 1)], complete_through=date(2026, 11, 1)),
        "ad",
        NOVEMBER,
        None,
        NOW,
    )
    assert late.totals[0]["reason"] == "coverage_incomplete"


def test_spend_comparison_per_currency():
    days = Period(date(2026, 11, 3), date(2026, 11, 4))
    facts = [
        _fact("31", date(2026, 11, 2), "EGP", 1000),
        _fact("31", date(2026, 11, 3), "EGP", 1500),
        _fact("31", date(2026, 11, 3), "USD", 100),
    ]
    result = spend_report(_spend(facts), "ad", days, days.previous(), NOW)
    spend = [item for item in result.comparison if item["metric"] == "spend"]
    assert spend[0]["currency"] == "EGP"
    assert spend[0]["difference"] == {"minor": 500, "decimal": "5.00"}
    assert spend[0]["percent_change"] == "50.00"
    assert spend[1]["currency"] == "USD" and spend[1]["reason"] == "no_spend_facts"
    assert spend[1]["previous_value"] is None


# --- revenue (V09-V11) --------------------------------------------------------------------------


def _evidence(number, kind, minor, effective, parent=None, currency=EGP, klass=None, received=None):
    classes = {
        OperationKind.SALE: EvidenceClass.CONFIRMED_CAPTURE,
        OperationKind.REFUND: EvidenceClass.CONFIRMED_ADJUSTMENT,
    }
    return Evidence(
        delivery_id=f"d-{number}",
        agency_id=AGENCY,
        client_id=CLIENT,
        source_account_id="acct",
        operation_id=f"op-{number}" if kind is OperationKind.SALE or parent else f"op-{number}",
        kind=kind,
        classification=klass or classes[kind],
        amount=Money(minor, currency),
        effective_at=effective,
        received_at=received or effective + timedelta(hours=1),
        parent_operation_id=parent,
    )


def _revenue(records, held=()) -> RevenueInputs:
    return RevenueInputs(calculate(records), held, len(records), "0" * 64, AGENCY, CLIENT)


def test_refund_activity_follows_its_own_date_with_the_sale_outside_the_period():
    sale = _evidence(1, OperationKind.SALE, 10000, datetime(2026, 1, 15, 9, tzinfo=UTC))
    refund = _evidence(
        2, OperationKind.REFUND, 2000, datetime(2026, 2, 10, 9, tzinfo=UTC), parent="op-1"
    )
    inputs = _revenue([sale, refund])
    february = Period(date(2026, 2, 1), date(2026, 2, 28))
    result = revenue_report(inputs, february, None)
    verified = result.totals[0]
    assert verified["net"] == {"minor": -2000, "decimal": "-20.00"}
    assert verified["refunded"]["minor"] == 2000 and verified["captured"]["minor"] == 0
    rows = list(result.rows())
    assert [(row["kind"], row["amount"]["minor"]) for row in rows] == [("refund", -2000)]
    january = revenue_report(inputs, Period(date(2026, 1, 1), date(2026, 2, 1)), None)
    assert january.totals[0]["net"]["minor"] == 10000
    compared = revenue_report(inputs, february, Period(date(2026, 1, 4), date(2026, 2, 1)))
    net = next(item for item in compared.comparison if item["metric"] == "net")
    assert net["difference"]["minor"] == -12000 and net["percent_change"] == "-120.00"


def test_duplicates_declarations_and_unresolved_items_stay_separate():
    effective = datetime(2026, 11, 1, 9, tzinfo=UTC)
    sale = _evidence(1, OperationKind.SALE, 10000, effective)
    again = replace(sale, delivery_id="d-1b", received_at=effective + timedelta(hours=2))
    declared = _evidence(
        3, OperationKind.SALE, 5000, effective, klass=EvidenceClass.MANUAL_DECLARATION
    )
    orphan = _evidence(4, OperationKind.REFUND, 100, effective, parent="op-missing")
    held = _evidence(5, OperationKind.REFUND, 300, effective, parent="op-1")
    result = revenue_report(_revenue([sale, again, declared, orphan], held=[held]), NOVEMBER, None)
    verified = next(item for item in result.totals if item["block"] == "verified")
    assert verified["captured"]["minor"] == 10000 and verified["postings"] == 1
    declared_total = next(item for item in result.totals if item["block"] == "declared")
    assert declared_total["sales"]["minor"] == 5000
    assert result.unresolved["pending_reasons"] == {
        "parent_missing": 1,
        "parent_order_mismatch": 1,
    }
    assert result.unresolved["held"] == 1 and result.unresolved["scope"] == "all_evidence"
    assert result.unresolved["external_completeness"] == "unknown"
    assert [row["block"] for row in result.rows()] == ["verified", "declared"]


def test_currencies_stay_apart_and_conflicting_exponents_fail():
    effective = datetime(2026, 11, 1, 9, tzinfo=UTC)
    records = [
        _evidence(1, OperationKind.SALE, 100, effective),
        _evidence(2, OperationKind.SALE, 200, effective, currency=USD),
    ]
    result = revenue_report(_revenue(records), NOVEMBER, None)
    assert [item["currency"] for item in result.totals] == ["EGP", "USD"]
    quiet = revenue_report(_revenue(records), Period(date(2026, 10, 1), date(2026, 10, 2)), None)
    assert [item["net"]["minor"] for item in quiet.totals] == [0, 0]
    assert list(quiet.rows()) == []
    conflict = records + [
        _evidence(3, OperationKind.SALE, 100, effective, currency=Currency("EGP", 3))
    ]
    with pytest.raises(ReportError) as error:
        revenue_report(_revenue(conflict), NOVEMBER, None)
    assert error.value.code == "currency_exponent_conflict"


# --- common helpers -----------------------------------------------------------------------------


def test_percentages_are_exact_and_never_infinite():
    assert percent_change(3, 2) == "50.00"
    assert percent_change(1, 3) == "-66.67"
    assert percent_change(2, 3) == "-33.33"
    assert percent_change(5, 0) is None
    assert compare_values(5, 0, None) == {
        "difference": 5,
        "percent_change": None,
        "comparable": True,
        "reason": "zero_baseline",
    }
    assert compare_values(5, None, None)["reason"] == "unavailable"
    with pytest.raises(ReportError):
        PageRequest(0, 10)
    with pytest.raises(ReportError):
        PageRequest(1, 501)
    with pytest.raises(ReportError) as error:
        page_of(iter([]), 0, PageRequest(2, 10))
    assert error.value.code == "invalid_page"
    assert page_of(iter([]), 0, PageRequest(1, 10))[1]["total_pages"] == 1


def test_digests_are_canonical():
    first = digest_of("x", {"b": 1, "a": [date(2026, 1, 1), CLIENT]})
    second = digest_of("x", {"a": [date(2026, 1, 1), CLIENT], "b": 1})
    assert first == second and first != digest_of("y", {"a": 1})
    assert canonical(datetime(2026, 1, 1, 2, tzinfo=UTC)) == '"2026-01-01T02:00:00.000000+00:00"'
    with pytest.raises(TypeError):
        canonical(datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        canonical(float("nan"))


# --- CSV (V15, V16) -----------------------------------------------------------------------------


def _parse(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"), newline="")))


HOSTILE = [
    "=1+2",
    "+SUM(A1)",
    "-2+3",
    "@cmd",
    "a,b;c\td",
    "line\r\nbreak",
    "\uff1dfull",
    "\u2212minus",
    '"quoted"',
]


@pytest.mark.parametrize("identifier", HOSTILE)
def test_identifiers_are_prefixed_and_quoted(identifier):
    builder = csv_export.CsvBuilder("social", {})
    builder.add("value", object_id=identifier, value="-20.00", value_minor=-2000)
    data = builder.encode()
    row = _parse(data)[0]
    assert row["object_id"] == f"id:{identifier}"
    assert row["value"] == "-20.00" and row["value_minor"] == "-2000"
    texts = [value for key, value in row.items() if key not in {"value", "value_minor"}]
    assert all(value[:1] not in {"=", "+", "-", "@", "\t", "\r"} for value in texts)
    assert data.split(b"\r\n")[1].startswith(b'"value","social"')


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("metric", "=cmd"),
        ("metric", "-x"),
        ("metric", "name with space"),
        ("metric", 5),
        ("value", "12abc"),
        ("value", "=1"),
        ("value", float("inf")),
        ("value", True),
        ("value", object()),
        ("value_minor", 1.5),
        ("date", datetime(2026, 1, 1, tzinfo=UTC)),
        ("timestamp", datetime(2026, 1, 1)),
        ("day_zone", "Not/AZone"),
        ("object_id", ""),
        ("object_id", 5),
        ("provisional", "true"),
        ("unknown_column", "x"),
    ],
)
def test_unexpected_cells_are_refused_not_coerced(column, value):
    builder = csv_export.CsvBuilder("social", {})
    with pytest.raises(csv_export.ExportRefused):
        builder.add("value", **{column: value})


def test_csv_row_and_byte_bounds_refuse_whole_files(monkeypatch):
    builder = csv_export.CsvBuilder("spend", {})
    for _ in range(csv_export.MAX_ROWS):
        builder.add("value", value=1)
    assert len(_parse(builder.encode())) == csv_export.MAX_ROWS
    with pytest.raises(ReportError) as error:
        builder.add("value", value=1)
    assert error.value.code == "export_too_large"
    with pytest.raises(ReportError):
        csv_export.CsvBuilder("spend", {}).reserve(csv_export.MAX_ROWS + 1)

    def sized(identifier: str) -> bytes:
        item = csv_export.CsvBuilder("social", {})
        item.add("value", object_id=identifier)
        return item.encode()

    base = len(sized("x"))
    # Two-byte characters: the bound counts encoded bytes, not characters.
    monkeypatch.setattr(csv_export, "MAX_BYTES", base + 9)
    assert len(sized("x" + "\u00e9" * 4 + "y")) == base + 9
    with pytest.raises(ReportError) as error:
        sized("x" + "\u00e9" * 5)
    assert error.value.code == "export_too_large"


def test_default_csv_bounds_are_the_approved_values():
    assert csv_export.MAX_ROWS == 5000
    assert csv_export.MAX_BYTES == 2_097_152
    assert csv_export.NAMES[0] == "row_type" and len(set(csv_export.NAMES)) == len(csv_export.NAMES)
