"""Regression for the account-day cursor at the rolling history boundary."""

from datetime import UTC, datetime, timedelta

from instagram_graph import APP_ID, APP_SECRET, FakeGraph

from app.connectors.instagram import InstagramProvider


def test_review_instagram_cursor_does_not_skip_day_at_midnight():
    moment = [datetime(2026, 11, 21, 23, 59, tzinfo=UTC)]
    graph = FakeGraph(clock=lambda: moment[0])
    provider = InstagramProvider(APP_ID, APP_SECRET, transport=graph, clock=lambda: moment[0])
    grant = provider.exchange(
        code=graph.issue_code(), code_verifier=None, redirect_uri="https://example.test/callback"
    )
    since = moment[0] - timedelta(days=729)
    until = moment[0]
    first = provider.fetch_page(grant.access_token, stream="account", since=since, until=until)
    moment[0] += timedelta(minutes=2)
    second = provider.fetch_page(
        grant.access_token, stream="account", since=since, until=until, cursor=first.next_cursor
    )
    assert second.records[0].observed_at == first.records[0].observed_at + timedelta(days=1)
