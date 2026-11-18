"""Pure parts of the 011-A runtime extensions and the YouTube-shaped synthetic adapter.

No database and no network: Pacific day arithmetic across the 2026 daylight-saving changes, the
D-060 completeness bound, the content-type mapping, rounded counts, the capability that the
integration tests rely on, and the merge review corrections (D-061) that need no database: the
synthetic day cursor (R011-15) and the authorization check's need for quota buckets (R011-13).
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.connectors.contracts import ErrorKind, ProviderError
from app.connectors.synthetic_youtube import (
    ANALYTICS,
    CAPABILITY,
    DATA,
    VIDEO_ATTRIBUTES,
    SyntheticYouTubeProvider,
    complete_through,
    pacific_start,
    product_type,
    rounded_count,
)
from app.services.connectors import bucket_day, local_days_before, next_reset

PACIFIC = "America/Los_Angeles"


def test_pacific_days_follow_the_zone_across_both_changes():
    # 2026-03-08 has 23 hours and 2026-11-01 has 25.
    assert pacific_start(date(2026, 3, 9)) - pacific_start(date(2026, 3, 8)) == timedelta(hours=23)
    assert pacific_start(date(2026, 11, 2)) - pacific_start(date(2026, 11, 1)) == timedelta(
        hours=25
    )
    watermark = datetime(2026, 11, 3, 8, tzinfo=UTC)  # 2026-11-03 00:00 PST
    assert local_days_before(watermark, 4, PACIFIC) == datetime(2026, 10, 30, 7, tzinfo=UTC)
    assert watermark - timedelta(days=4) == datetime(2026, 10, 30, 8, tzinfo=UTC)  # 01:00 PDT
    assert local_days_before(watermark, 0, PACIFIC) == watermark


def test_completeness_is_the_last_pacific_day_ended_72_hours_before_the_read():
    assert complete_through(datetime(2026, 11, 6, 20, tzinfo=UTC)) == datetime(
        2026, 11, 3, 8, tzinfo=UTC
    )
    # 72 hours before 2026-11-04 07:30 UTC is 2026-10-31 23:30 PDT: complete through 2026-10-30.
    assert complete_through(datetime(2026, 11, 4, 6, 30, tzinfo=UTC)) == datetime(
        2026, 10, 31, 7, tzinfo=UTC
    )


def test_quota_days_and_resets_follow_the_bucket_zone():
    data = CAPABILITY.bucket(DATA)
    late = datetime(2026, 11, 6, 7, 59, tzinfo=UTC)
    assert bucket_day(late, data) == date(2026, 11, 5)
    assert next_reset(late, data) == datetime(2026, 11, 6, 8, tzinfo=UTC)
    assert bucket_day(late, None) == date(2026, 11, 6)
    assert next_reset(late, None) == datetime(2026, 11, 7, tzinfo=UTC)


def test_content_types_and_rounded_counts():
    assert product_type("shorts") == "SHORTS"
    assert product_type("videoOnDemand") == "VIDEO_ON_DEMAND"
    assert product_type("creatorContentTypeUnspecified") == "UNSPECIFIED"
    assert product_type("liveStream") == "UNSPECIFIED"
    assert product_type("SHORTS") == "UNSPECIFIED"
    assert [rounded_count(value) for value in (0, 999, 12345, 1234567)] == [0, 999, 12300, 1230000]


def test_capability_declares_the_approved_rules():
    capability = CAPABILITY
    assert (capability.pkce, capability.revocation_scope, capability.require_all_scopes) == (
        "S256",
        "account",
        True,
    )
    assert (
        capability.refresh_ahead_seconds,
        capability.authorization_check_days,
        capability.reconnect_grace_days,
        capability.label_refresh_days,
    ) == (300, 7, 14, 30)
    assert capability.day_zone == PACIFIC and capability.agent_disclosure == "dev-agent-approval-1"
    buckets = {item.name: item for item in capability.buckets}
    assert (buckets[DATA].daily_quota, buckets[DATA].connection_daily) == (9000, 100)
    assert (buckets[ANALYTICS].daily_quota, buckets[ANALYTICS].connection_daily) == (90000, 30)
    assert {item.zone for item in capability.buckets} == {PACIFIC}
    assert [spec.name for spec in capability.stream_specs()] == [
        "channel",
        "channel_daily",
        "videos",
        "video_totals",
    ]
    assert capability.bucket_costs("fetch", "videos") == {DATA: 2}
    assert capability.bucket_costs("confirm", "videos") == {DATA: 1}
    assert capability.bucket_costs("fetch", "video_totals") == {DATA: 1, ANALYTICS: 1}
    assert capability.bucket_costs("refresh", "videos") == {}
    videos = capability.stream_spec("videos")
    assert videos.inventory and videos.attributes == VIDEO_ATTRIBUTES
    assert "title" not in videos.attributes
    assert capability.stream_delay_hours("channel_daily") == 193
    assert capability.stream_delay_hours("videos") == 0
    averages = {spec.name for spec in capability.metrics if not spec.additive}
    assert averages == {"averageViewDuration", "averageViewPercentage"}


# R011-15: a channel_daily cursor carries the read's first day with the offset; a bare offset,
# as written before the correction, is refused rather than read against a moved first day.
# The cursor is checked before any token or state is read.
def test_r011_15_the_synthetic_day_cursor_carries_the_first_day(tmp_path):
    provider = SyntheticYouTubeProvider(tmp_path / "synthetic-youtube.sqlite3")
    for malformed in ("syt_cursor_31", "syt_cursor_2026-08-04", "syt_cursor_2026-08-04:x", "31"):
        with pytest.raises(ProviderError) as invalid:
            provider.fetch_page("unused", stream="channel_daily", cursor=malformed)
        assert (invalid.value.kind, invalid.value.provider_code) == (
            ErrorKind.PERMANENT,
            "invalid_cursor",
        )
    # Inventory cursors keep their plain offset.
    with pytest.raises(ProviderError) as invalid:
        provider.fetch_page("unused", stream="videos", cursor="syt_cursor_2026-08-04:31")
    assert invalid.value.provider_code == "invalid_cursor"


# R011-13: the scheduling step that checks authorization has no run to charge, so a provider
# that declares the check must have quota buckets, which leave refreshes unmetered (D10).
def test_r011_13_an_authorization_check_period_needs_quota_buckets():
    assert CAPABILITY.bucket_costs("refresh", "channel") == {}
    with pytest.raises(ValueError, match="quota buckets"):
        replace(CAPABILITY, buckets=())
    assert replace(CAPABILITY, buckets=(), authorization_check_days=None).buckets == ()
