"""Synthetic fixtures for the 016-B attribution report tests (specification 016-B, D-089).

Builds on the 008-B attribution world: campaigns, content references and managed links made
through the links API, page views that carry a link ID, report requests and readers of the
JSON and CSV answers. Every value is synthetic (example.test origins, fictional codes).
"""

import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from fractions import Fraction
from uuid import UUID

from identity_support import ORIGIN

from app.security import now_utc


def sale_day(days_ahead: int = 2) -> date:
    """A future UTC date for sale instants. Touches and leads happen now: an event dated before
    its subject's identity link is never assigned to the person, and a lead cannot be dated
    more than a few minutes ahead, so sale dates are placed after the journey instead."""
    return (now_utc() + timedelta(days=days_ahead)).date()


def today() -> date:
    return now_utc().date()


def at(day: date, hours: int = 10, minutes: int = 0, seconds: int = 0) -> datetime:
    return datetime.combine(day, time(), UTC) + timedelta(
        hours=hours, minutes=minutes, seconds=seconds
    )


def span(day: date, days: int = 1) -> dict[str, str]:
    return {"start": day.isoformat(), "end": (day + timedelta(days=days)).isoformat()}


def report_url(w, family: str, client=None, agency=None) -> str:
    return f"/agencies/{agency or w.a}/clients/{client or w.a1}/reports/{family}"


def get(reader, w, family: str, *, client=None, agency=None, **params):
    return reader.get(report_url(w, family, client, agency), params=params)


def list_url(w, client=None, agency=None) -> str:
    return f"/agencies/{agency or w.a}/clients/{client or w.a1}/attribution/conversions"


def versions(reader, w, client=None) -> dict[str, str]:
    response = reader.get(f"/agencies/{w.a}/clients/{client or w.a1}/attribution/models")
    assert response.status_code == 200, response.text
    return {item["version_key"]: item["id"] for item in response.json()["versions"]}


def set_grant(aw, **flags) -> None:
    grant_url = f"{aw.idw.base}/members/{aw.w.analyst}/clients/{aw.w.a1}"
    assert aw.idw.owner.put(grant_url, json=flags).status_code == 204


def campaign(owner, w, code: str, client=None) -> UUID:
    response = owner.post(
        f"/agencies/{w.a}/clients/{client or w.a1}/link-campaigns",
        json={"public_code": code, "label": f"Synthetic {code}"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def content(owner, w, code: str, client=None) -> UUID:
    response = owner.post(
        f"/agencies/{w.a}/clients/{client or w.a1}/link-content-references",
        json={"external_code": code, "platform_label": "Synthetic"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def managed_link(owner, w, slug: str, *, campaign_id=None, content_id=None, client=None) -> UUID:
    path = f"/agencies/{w.a}/clients/{client or w.a1}"
    origin = owner.post(f"{path}/link-destination-origins", json={"origin": ORIGIN})
    assert origin.status_code in {201, 409}, origin.text
    body = {"slug": slug, "destination": f"{ORIGIN}/offer"}
    if campaign_id is not None:
        body["campaign_id"] = str(campaign_id)
    if content_id is not None:
        body["content_reference_id"] = str(content_id)
    response = owner.post(f"{path}/managed-links", json=body)
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def visit(aw, token, link_id, *, at_time=None, client=None, query: str = ""):
    """A consenting visitor's landing page view through a managed link."""
    return aw.idw.event(
        token,
        occurred_at=at_time,
        payload={"url": f"{ORIGIN}/offer{query}"},
        client_id=client or aw.w.a1,
        link_id=link_id,
    )


def tagged(aw, token, *, campaign: str | None = None, content: str | None = None, at_time=None):
    """A page view whose retained URL carries utm_campaign and utm_content values."""
    parts = []
    if campaign is not None:
        parts.append(f"utm_campaign={campaign}")
    if content is not None:
        parts.append(f"utm_content={content}")
    url = f"{ORIGIN}/p" + ("?" + "&".join(parts) if parts else "")
    return aw.idw.event(token, occurred_at=at_time, payload={"url": url})


def fraction(value) -> Fraction:
    return Fraction(value["numerator"], value["denominator"])


def credit_map(body) -> dict:
    """{(group_ref or recipient, currency or None): (share, minor)} of a groups report, the
    shape of attribution_support's ledger() helper."""
    found = {}
    for row in body["rows"]:
        key = row["group_ref"] or row["recipient"]
        for item in (row["sales"] or {}).get("items") or ():
            found[(key, item["currency"])] = (
                fraction(item["credited_sales"]),
                item["credited_revenue"]["minor"],
            )
        leads = row["leads"]
        if fraction(leads["credited_leads"]):
            found[(key, None)] = (fraction(leads["credited_leads"]), 0)
    return found


def total(body, *, currency="EGP", recipient="all", period="current"):
    for item in body["totals"]["sales"]["items"]:
        if (item["currency"], item["recipient"], item["period"]) == (currency, recipient, period):
            return item
    raise AssertionError((currency, recipient, period))


def lead_total(body, *, recipient="all", period="current"):
    for item in body["totals"]["leads"]["items"]:
        if (item["recipient"], item["period"]) == (recipient, period):
            return item
    raise AssertionError((recipient, period))


def parse_csv(response) -> list[dict[str, str]]:
    assert response.headers["content-type"].startswith("text/csv"), response.headers
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))
