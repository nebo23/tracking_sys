"""016-B funnel report on disposable PostgreSQL (D-089 D8).

Case BV14 and, for the funnel family, BV01, BV02, BV06 and BV16-BV18. Synthetic visitors open
managed links (page views that carry the link ID) and synthetic journeys go through the 008-B
worker; the report counts the consented link page views of the client on their received date
beside the stored credit. Synthetic values only.
"""

from datetime import timedelta
from fractions import Fraction

import pytest
from attribution_support import make_attribution_world
from credit_support import (
    campaign,
    content,
    fraction,
    get,
    managed_link,
    parse_csv,
    span,
    today,
    visit,
)
from identity_support import make_identity_world
from report_support import grant, key_client, service_key
from sqlalchemy import text

from app.services import reporting

pytestmark = pytest.mark.integration


@pytest.fixture
def aw(authenticated_world, api):
    return make_attribution_world(make_identity_world(authenticated_world, api))


def keys_of(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys_of(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys_of(item)}
    return set()


def funnel_world(aw):
    """Links, visitors, a credited sale through a link and a lead through a utm campaign."""
    w, owner = aw.w, aw.idw.owner
    spring, post = campaign(owner, w, "spring"), content(owner, w, "post-1")
    campaign(owner, w, "autumn")  # registered, but no managed link carries it
    tagged_link = managed_link(owner, w, "spring-post", campaign_id=spring, content_id=post)
    bare_link = managed_link(owner, w, "bare-link")
    buyer = aw.person("buyer@example.test")
    visit(aw, buyer.token, tagged_link)
    visit(aw, buyer.token, tagged_link)
    anonymous = aw.idw.browser_subject()["subject_token"]
    visit(aw, anonymous, tagged_link)
    marked = visit(aw, anonymous, tagged_link)
    with w.db.migration.begin() as connection:
        connection.execute(
            text("UPDATE collected_events SET identity_excluded_at = now() WHERE event_id = :e"),
            {"e": marked},
        )
    other = aw.idw.browser_subject()["subject_token"]
    visit(aw, other, bare_link)
    aw.idw.event(other, event_type="link_click", link_id=tagged_link)  # not a page view
    aw.touch(other, None)  # a page view without a link
    foreign_link = managed_link(owner, w, "foreign-link", client=w.a2)
    stranger = aw.idw.browser_subject(client_id=w.a2)["subject_token"]
    visit(aw, stranger, foreign_link, client=w.a2)
    aw.sale("S1", 9_000)
    aw.associate(buyer.assertion, "S1")
    asker = aw.person("asker@example.test")
    aw.touch(asker.token, "autumn")
    aw.lead(asker.token)
    aw.settle()
    return tagged_link, bare_link


def test_bv14_visits_are_consented_link_page_views_of_the_client(aw):
    w = aw.w
    tagged_link, bare_link = funnel_world(aw)
    owner = aw.idw.owner
    window = span(today())
    body = get(owner, w, "funnel", **window).json()
    rows = {(row["recipient"], row["group_ref"]): row for row in body["rows"]}
    assert set(rows) == {("campaign", "autumn"), ("campaign", "spring"), ("campaign", None)}
    assert rows[("campaign", "spring")]["visits"] == {"state": "available", "count": 3}
    assert rows[("campaign", None)]["visits"] == {"state": "available", "count": 1}
    assert rows[("campaign", "autumn")]["visits"] == {"state": "unsupported", "count": None}
    spring = rows[("campaign", "spring")]
    assert spring["sales"]["items"][0]["credited_revenue"]["minor"] == 9_000
    assert fraction(rows[("campaign", "autumn")]["leads"]["credited_leads"]) == 1
    (totals,) = body["totals"]
    # buyer x2, the anonymous visitor, the bare link and the page view without a link.
    assert (totals["page_views"], totals["link_page_views"]) == (6, 4)
    assert totals["leads"]["lead_conversions"] == 1
    (sales,) = totals["sales"]["items"]
    assert (sales["sale_conversions"], sales["associated"], sales["unassociated"]) == (1, 1, 0)
    assert sales["ledger_net"]["minor"] == 9_000
    assert body["bases"] == {
        "visits": "received_date",
        "leads": "conversion_date",
        "sales": "conversion_date",
        "revenue": "conversion_date",
    }
    assert not any(key == "rate" or key.endswith("_rate") for key in keys_of(body))
    by_link = get(owner, w, "funnel", group_by="link", **window).json()
    links = {row["group_ref"]: row["visits"] for row in by_link["rows"]}
    assert links[str(tagged_link)] == {"state": "available", "count": 3}
    assert links[str(bare_link)] == {"state": "available", "count": 1}
    assert links[None] == {"state": "unsupported", "count": None}  # utm-only credit
    by_content = get(owner, w, "funnel", group_by="content", **window).json()
    contents = {row["group_ref"]: row["visits"] for row in by_content["rows"]}
    assert contents == {
        "post-1": {"state": "available", "count": 3},
        None: {"state": "available", "count": 1},
    }
    # Another client's view and the marked view are not counted; a day without views is 0.
    other = get(owner, w, "funnel", client=w.a2, **window).json()
    assert other["totals"][0]["link_page_views"] == 1
    tomorrow = get(owner, w, "funnel", **span(today() + timedelta(days=1))).json()
    assert tomorrow["totals"][0]["page_views"] == 0 and tomorrow["rows"] == []


def test_funnel_isolation_permissions_and_comparison(aw, api):
    w = aw.w
    funnel_world(aw)
    window = {**span(today()), "compare": "previous"}
    for name in ("analyst", "viewer"):
        response = get(w.signed_in(name), w, "funnel", **window)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["finance"] == "permission_unavailable"
        assert body["totals"][0]["sales"] == {
            "state": "permission_unavailable",
            "ledger": None,
            "items": None,
        }
        assert {row["sales"]["state"] for row in body["rows"]} == {"permission_unavailable"}
        assert body["totals"][0]["link_page_views"] == 4
        assert "EGP" not in response.text and "9000" not in response.text
    assert get(w.signed_in("outsider"), w, "funnel", **window).status_code == 403
    assert get(w.signed_in("owner_b"), w, "funnel", **window).status_code == 403
    leads_key = key_client(api, service_key(w, api, [grant(w.a1)]))
    assert get(leads_key, w, "funnel", **window).json()["finance"] == "permission_unavailable"
    finance_key = key_client(api, service_key(w, api, [grant(w.a1, financial=True)]))
    assert get(finance_key, w, "funnel", **window).json()["finance"] == "available"
    assert get(aw.idw.ingest, w, "funnel", **window).status_code in {401, 403}
    # Comparison: visits compare on their own; credit is blocked while attribution is behind.
    owner = aw.idw.owner
    rows = {item["metric"]: item for item in get(owner, w, "funnel", **window).json()["comparison"]}
    assert rows["page_views"]["reason"] == "zero_baseline"
    assert rows["credited_leads"]["reason"] == "zero_baseline"
    assert rows["credited_revenue"]["current_value"]["minor"] == 9_000
    aw.touch(aw.idw.browser_subject()["subject_token"], None)
    buyer = aw.person("late@example.test")
    aw.touch(buyer.token, "late")
    behind = {
        item["metric"]: item for item in get(owner, w, "funnel", **window).json()["comparison"]
    }
    assert behind["credited_leads"]["reason"] == "attribution_behind"
    assert behind["page_views"]["comparable"] is True


def test_funnel_pages_release_and_csv(aw, monkeypatch):
    w = aw.w
    tagged_link, _ = funnel_world(aw)
    owner = aw.idw.owner
    window = span(today())
    first = get(owner, w, "funnel", page_size=2, **window).json()
    second = get(
        owner, w, "funnel", page_size=2, page=2, expected_revision=first["revision"], **window
    ).json()
    whole = get(owner, w, "funnel", page_size=500, **window).json()
    assert first["rows"] + second["rows"] == whole["rows"]
    assert first["totals"] == whole["totals"]

    # A new tracked visit changes the revision and refuses a release built before it.
    def new_visit():
        visit(aw, aw.idw.browser_subject()["subject_token"], tagged_link)

    calls: list[str] = []

    def hook(family):
        calls.append(family)
        new_visit()

    for output in ("json", "csv"):
        monkeypatch.setattr(reporting, "before_release", hook)
        response = get(owner, w, "funnel", format=output, **window)
        assert (response.status_code, response.json()) == (409, {"error": "report_changed"})
    assert calls == ["funnel", "funnel"]
    monkeypatch.setattr(reporting, "before_release", reporting._no_hook)
    stale = get(
        owner, w, "funnel", page_size=2, page=2, expected_revision=first["revision"], **window
    )
    assert (stale.status_code, stale.json()) == (409, {"error": "report_changed"})
    body = get(owner, w, "funnel", page_size=500, **window).json()
    response = get(owner, w, "funnel", format="csv", **window)
    assert response.headers["content-disposition"] == 'attachment; filename="report-funnel.csv"'
    cells = parse_csv(response)
    visits = {
        row["group_ref"]: (row["availability"], row["count"])
        for row in cells
        if row["row_type"] == "value" and row["metric"] == "tracked_visits"
    }
    assert visits == {
        (f"id:{row['group_ref']}" if row["group_ref"] else ""): (
            row["visits"]["state"],
            "" if row["visits"]["count"] is None else str(row["visits"]["count"]),
        )
        for row in body["rows"]
    }
    leads = [
        Fraction(int(row["numerator"]), int(row["denominator"]))
        for row in cells
        if row["row_type"] == "value" and row["metric"] == "credited_leads"
    ]
    assert sum(leads) == 1
    assert not any(row["metric"] == "rate" or row["metric"].endswith("_rate") for row in cells)
    assert "example.test" not in response.text
