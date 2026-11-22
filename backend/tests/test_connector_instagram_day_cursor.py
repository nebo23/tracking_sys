"""The Instagram account-stream day cursor across UTC midnights (review finding R011, D-069).

The history limit (729 days back) is recomputed from the provider clock on every page. The cursor
names the read's first day and the absolute next day, so a resumed read never shifts onto a later
day, and the reported coverage starts only where the read was gapless. Everything runs against
the in-memory fake Graph; nothing calls Meta.
"""

from datetime import UTC, datetime, timedelta

import pytest
from instagram_graph import APP_ID, APP_SECRET, FakeGraph

from app.connectors.contracts import ErrorKind, ProviderError
from app.connectors.instagram import InstagramProvider, day_cursor, parse_day_cursor

REDIRECT = "https://tracking.example.test/connectors/oauth/callback"
EVENING = datetime(2026, 11, 21, 23, 59, tzinfo=UTC)
HISTORY = timedelta(days=729)


def _day(year, month, day):
    return datetime(year, month, day, tzinfo=UTC)


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


def _setup():
    clock = Clock(EVENING)
    graph = FakeGraph(clock=clock)
    provider = InstagramProvider(APP_ID, APP_SECRET, transport=graph, clock=clock)
    token = provider.exchange(
        code=graph.issue_code(), code_verifier=None, redirect_uri=REDIRECT
    ).access_token
    return clock, graph, token


def _read(graph, clock, token, cursor, since, until):
    # A new provider object per page: the cursor alone carries the read's position.
    provider = InstagramProvider(APP_ID, APP_SECRET, transport=graph, clock=clock)
    return provider.fetch_page(token, stream="account", since=since, until=until, cursor=cursor)


def test_one_midnight_continues_with_the_next_day():
    # The demonstrated boundary: the first page reads 2024-11-22 at 23:59; after midnight the
    # next pages continue with 23, 24 and 25 without a gap, and the read covers from the 22nd.
    clock, graph, token = _setup()
    since, until = EVENING - HISTORY, EVENING - HISTORY + timedelta(days=4)
    page = _read(graph, clock, token, None, since, until)
    days = [record.observed_at for record in page.records]
    assert days == [_day(2024, 11, 22)]
    assert page.next_cursor == "day:2024-11-22:2024-11-23"
    clock.moment += timedelta(minutes=2)
    while page.next_cursor is not None:
        page = _read(graph, clock, token, page.next_cursor, since, until)
        days.extend(record.observed_at for record in page.records)
    assert days == [_day(2024, 11, day) for day in (22, 23, 24, 25)]
    assert (page.covered_from, page.complete_through) == (_day(2024, 11, 22), _day(2024, 11, 26))


def test_several_midnights_restart_coverage_at_the_history_limit():
    # A deferral of three days leaves 23 and 24 November 2024 behind the moving history limit.
    # They can no longer be read, so the read continues at the limit (the 25th) and reports its
    # coverage from there, never from the 22nd, which would claim days it did not read.
    clock, graph, token = _setup()
    since, until = EVENING - HISTORY, EVENING - HISTORY + timedelta(days=6)
    first = _read(graph, clock, token, None, since, until)
    assert [record.observed_at for record in first.records] == [_day(2024, 11, 22)]
    clock.moment += timedelta(days=3)
    days, page = [], first
    while page.next_cursor is not None:
        page = _read(graph, clock, token, page.next_cursor, since, until)
        days.extend(record.observed_at for record in page.records)
    assert days == [_day(2024, 11, day) for day in (25, 26, 27)]
    assert page.covered_from == _day(2024, 11, 25)
    assert page.complete_through == _day(2024, 11, 28)


def test_resume_within_the_limit_keeps_the_fixed_first_day():
    # A pause that stays inside the limit changes nothing but the time of the read.
    clock, graph, token = _setup()
    since = EVENING - timedelta(days=10)
    page = _read(graph, clock, token, None, since, None)
    cursor = page.next_cursor
    assert cursor == "day:2026-11-11:2026-11-12"
    clock.moment += timedelta(days=2)
    resumed = _read(graph, clock, token, cursor, since, None)
    assert [record.observed_at for record in resumed.records] == [_day(2026, 11, 12)]
    assert resumed.covered_from == _day(2026, 11, 11)
    # The end follows the latest complete day: two more days became complete meanwhile.
    assert resumed.complete_through == _day(2026, 11, 23)


def test_an_exhausted_window_ends_the_read():
    clock, graph, token = _setup()
    until = EVENING - timedelta(days=2)
    cursor = day_cursor(_day(2026, 11, 15), _day(2026, 11, 19))
    page = _read(graph, clock, token, cursor, None, until)
    assert (page.records, page.next_cursor) == ((), None)
    assert (page.covered_from, page.complete_through) == (_day(2026, 11, 15), _day(2026, 11, 19))


@pytest.mark.parametrize(
    "cursor",
    [
        "day:1",
        "day:2024-11-23",
        "day:2024-11-23:2024-11-22",
        "day:2024-13-01:2024-11-23",
        "day:2024-11-1:2024-11-23",
        "day:2024-11-21:2024-11-23:2024-11-24",
        "page:2024-11-21:2024-11-23",
        "",
    ],
)
def test_malformed_cursors_are_refused(cursor):
    with pytest.raises(ProviderError) as refused:
        parse_day_cursor(cursor)
    assert (refused.value.kind, refused.value.provider_code) == (
        ErrorKind.PERMANENT,
        "invalid_cursor",
    )
