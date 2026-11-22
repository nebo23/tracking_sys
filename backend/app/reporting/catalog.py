"""The closed reporting catalog (specification 016-A, D-072 decision D3).

Every metric an Instagram or YouTube adapter can store has exactly one entry here, keyed by
source family, stream and metric, with its unit, the media product types that offer it and the
dates on which the provider changed its definition. The metric class decides what a report may
do with the values; the adapters' generic MetricSpec.additive default is never used for that.

| Class | Report behavior |
|---|---|
| daily_additive | daily values; a period total sums them within one connection and definition |
| daily_non_additive | daily unique-audience observations only; no period total or percentage |
| lifetime_additive | per-content lifetime values for a publication cohort; a cohort sum of counts |
| lifetime_non_additive | per-content unique audience; no aggregate across content |
| ratio | source averages and rates as observed; no sum and no average of averages |
| snapshot | point-in-time counters; not reported by 016-A (snapshot_not_reported) |
| unreviewed | semantics not approved for reporting; unsupported (semantics_unreviewed) |

Instagram follows_and_unfollows is unreviewed: without the follow_type breakdown one total mixes
follows and unfollows. YouTube channel statistics and the public video counters are snapshots.
A metric without an entry, or one of the last two classes, is unsupported in reporting even if a
connector stores it. The unit tests compare this catalog with every adapter's declared metrics.

Families also fix their day zone (Instagram UTC, YouTube America/Los_Angeles), their daily and
content streams, each stream's provisional data delay and the freshness window, the same values
the adapters declare, so stored data stays reportable with its labels while an adapter is
switched off.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType

from app.reporting.periods import Period

CATALOG_VERSION = "016a.1"


class MetricClass(StrEnum):
    DAILY_ADDITIVE = "daily_additive"
    DAILY_NON_ADDITIVE = "daily_non_additive"
    LIFETIME_ADDITIVE = "lifetime_additive"
    LIFETIME_NON_ADDITIVE = "lifetime_non_additive"
    RATIO = "ratio"
    SNAPSHOT = "snapshot"
    UNREVIEWED = "unreviewed"


EXCLUDED = MappingProxyType(
    {
        MetricClass.SNAPSHOT: "snapshot_not_reported",
        MetricClass.UNREVIEWED: "semantics_unreviewed",
    }
)
DAILY_CLASSES = frozenset(
    {MetricClass.DAILY_ADDITIVE, MetricClass.DAILY_NON_ADDITIVE, MetricClass.RATIO}
)
CONTENT_CLASSES = frozenset(
    {MetricClass.LIFETIME_ADDITIVE, MetricClass.LIFETIME_NON_ADDITIVE, MetricClass.RATIO}
)


@dataclass(frozen=True)
class Entry:
    family: str
    stream: str
    metric: str
    unit: str
    metric_class: MetricClass
    product_types: tuple[str, ...] | None = None
    definition_changes: tuple[date, ...] = ()

    @property
    def reportable(self) -> bool:
        return self.metric_class not in EXCLUDED

    @property
    def summable(self) -> bool:
        return self.metric_class in {MetricClass.DAILY_ADDITIVE, MetricClass.LIFETIME_ADDITIVE}

    # Whether the metric applies to a record's media product type. A metric restricted to
    # product types is unsupported for a record without one (an unknown product type).
    def offered(self, product_type: str | None) -> bool:
        return self.product_types is None or product_type in self.product_types

    # The latest definition change on or before the day, or None for the original definition.
    def definition_since(self, day: date) -> date | None:
        changes = [item for item in self.definition_changes if item <= day]
        return max(changes) if changes else None

    # Whether the definition changes inside the dates from start (exclusive) to end (exclusive).
    def changes_between(self, start: date, end: date) -> bool:
        return any(start < item < end for item in self.definition_changes)

    def changes_within(self, period: Period) -> bool:
        return self.changes_between(period.start, period.end)


@dataclass(frozen=True)
class Family:
    name: str
    providers: tuple[str, ...]
    day_zone: str
    daily_stream: str
    content_streams: tuple[str, ...]
    stream_delay_hours: MappingProxyType
    freshness_hours: int
    # A stream whose records carry the publication time of content as an attribute (YouTube
    # videos); None when the content record's observed time is its publication time.
    publication_stream: str | None = None

    def delay_hours(self, stream: str) -> int:
        return int(self.stream_delay_hours.get(stream, 0))


INSTAGRAM = Family(
    name="instagram",
    providers=("instagram", "synthetic_instagram"),
    day_zone="UTC",
    daily_stream="account",
    content_streams=("media", "stories"),
    stream_delay_hours=MappingProxyType({"account": 48, "media": 48, "stories": 48}),
    freshness_hours=24,
)
YOUTUBE = Family(
    name="youtube",
    providers=("youtube", "synthetic_youtube"),
    day_zone="America/Los_Angeles",
    daily_stream="channel_daily",
    content_streams=("video_totals",),
    stream_delay_hours=MappingProxyType(
        {"channel": 0, "channel_daily": 193, "videos": 0, "video_totals": 0}
    ),
    freshness_hours=36,
    publication_stream="videos",
)
FAMILIES = MappingProxyType({family.name: family for family in (INSTAGRAM, YOUTUBE)})
PROVIDER_FAMILIES = MappingProxyType(
    {provider: family for family in FAMILIES.values() for provider in family.providers}
)

D, DN = MetricClass.DAILY_ADDITIVE, MetricClass.DAILY_NON_ADDITIVE
L, LN = MetricClass.LIFETIME_ADDITIVE, MetricClass.LIFETIME_NON_ADDITIVE
R, S, U = MetricClass.RATIO, MetricClass.SNAPSHOT, MetricClass.UNREVIEWED
FEED_REELS_STORY = ("FEED", "REELS", "STORY")
FEED_REELS = ("FEED", "REELS")
FEED_STORY = ("FEED", "STORY")
REELS = ("REELS",)
STORY = ("STORY",)
# Dates on which YouTube changed how views count, as the 011 entry review records them.
ANALYTICS_VIEW_CHANGES = (date(2025, 4, 30), date(2026, 8, 27), date(2026, 11, 16))
PUBLIC_VIEW_CHANGES = (date(2025, 3, 31), date(2026, 8, 27), date(2026, 11, 16))


def _instagram() -> list[Entry]:
    account = [
        ("reach", DN),
        ("views", D),
        ("accounts_engaged", DN),
        ("total_interactions", D),
        ("likes", D),
        ("comments", D),
        ("shares", D),
        ("saves", D),
        ("replies", D),
        ("follows_and_unfollows", U),
        ("profile_links_taps", D),
    ]
    media = [
        ("reach", "count", LN, FEED_REELS_STORY),
        ("views", "count", L, FEED_REELS_STORY),
        ("likes", "count", L, FEED_REELS),
        ("comments", "count", L, FEED_REELS),
        ("saved", "count", L, FEED_REELS),
        ("shares", "count", L, FEED_REELS_STORY),
        ("total_interactions", "count", L, FEED_REELS_STORY),
        ("profile_visits", "count", L, FEED_STORY),
        ("follows", "count", L, FEED_STORY),
        ("ig_reels_avg_watch_time", "milliseconds", R, REELS),
        ("ig_reels_video_view_total_time", "milliseconds", L, REELS),
        ("reels_skip_rate", "percent", R, REELS),
    ]
    stories = [
        ("reach", "count", LN, FEED_REELS_STORY),
        ("views", "count", L, FEED_REELS_STORY),
        ("shares", "count", L, FEED_REELS_STORY),
        ("total_interactions", "count", L, FEED_REELS_STORY),
        ("profile_visits", "count", L, FEED_STORY),
        ("follows", "count", L, FEED_STORY),
        ("replies", "count", L, STORY),
        ("navigation", "count", L, STORY),
    ]
    entries = [Entry("instagram", "account", name, "count", kind) for name, kind in account]
    entries += [Entry("instagram", "media", *item) for item in media]
    entries += [Entry("instagram", "stories", *item) for item in stories]
    return entries


def _youtube() -> list[Entry]:
    analytics = [
        ("views", "count", ANALYTICS_VIEW_CHANGES),
        ("engagedViews", "count", ()),
        ("estimatedMinutesWatched", "minutes", ()),
        ("averageViewDuration", "seconds", ()),
        ("averageViewPercentage", "percent", ()),
        ("likes", "count", ()),
        ("dislikes", "count", ()),
        ("comments", "count", ()),
        ("shares", "count", ()),
        ("subscribersGained", "count", ()),
        ("subscribersLost", "count", ()),
        ("videosAddedToPlaylists", "count", ()),
        ("videosRemovedFromPlaylists", "count", ()),
    ]
    averages = {"averageViewDuration", "averageViewPercentage"}
    entries = []
    for name, unit, changes in analytics:
        daily = R if name in averages else D
        lifetime = R if name in averages else L
        entries.append(Entry("youtube", "channel_daily", name, unit, daily, None, changes))
        entries.append(Entry("youtube", "video_totals", name, unit, lifetime, None, changes))
    entries += [
        Entry("youtube", "channel", "subscriberCount", "rounded_count", S),
        Entry("youtube", "channel", "viewCount", "count", S, None, PUBLIC_VIEW_CHANGES),
        Entry("youtube", "channel", "videoCount", "count", S),
        Entry("youtube", "videos", "viewCount", "count", S, None, PUBLIC_VIEW_CHANGES),
        Entry("youtube", "videos", "likeCount", "count", S),
        Entry("youtube", "videos", "commentCount", "count", S),
    ]
    return entries


ENTRIES: tuple[Entry, ...] = tuple(_instagram() + _youtube())
CATALOG = MappingProxyType({(item.family, item.stream, item.metric): item for item in ENTRIES})
if len(CATALOG) != len(ENTRIES):  # pragma: no cover - a duplicate key is a coding error
    raise RuntimeError("Duplicate reporting catalog entry.")


def family_of(provider: str) -> Family | None:
    return PROVIDER_FAMILIES.get(provider)


def stream_entries(family: str, stream: str) -> tuple[Entry, ...]:
    return tuple(
        sorted(
            (item for item in ENTRIES if item.family == family and item.stream == stream),
            key=lambda item: item.metric,
        )
    )


# The reportable entries of a view's streams, in (stream, metric) order.
def view_entries(family: Family, view: str) -> tuple[Entry, ...]:
    streams = (family.daily_stream,) if view == "daily" else family.content_streams
    classes = DAILY_CLASSES if view == "daily" else CONTENT_CLASSES
    return tuple(
        item
        for stream in sorted(streams)
        for item in stream_entries(family.name, stream)
        if item.metric_class in classes
    )


# Entries of the view's streams that 016-A does not report, with their closed reason.
def excluded_entries(family: Family, view: str) -> list[dict[str, str]]:
    streams: tuple[str, ...] = (family.daily_stream,)
    if view != "daily":
        streams = family.content_streams + (
            (family.publication_stream,) if family.publication_stream else ()
        )
    return [
        {"stream": item.stream, "metric": item.metric, "reason": EXCLUDED[item.metric_class]}
        for stream in sorted(streams)
        for item in stream_entries(family.name, stream)
        if not item.reportable
    ]
