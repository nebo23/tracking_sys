"""016-B report bounds on disposable PostgreSQL (D-089 D10; BV14 and BV19).

Synthetic rows are copied in bulk by the migration role so the bounds are reached exactly:
50,000 link-tagged page views pass the funnel and 50,001 are refused before any total.
Synthetic values only.
"""

import pytest
from attribution_support import make_attribution_world
from credit_support import get, managed_link, span, today, visit
from identity_support import make_identity_world
from sqlalchemy import text

pytestmark = pytest.mark.integration
COPY_EVENT = (
    "INSERT INTO collected_events (id, agency_id, client_id, event_id, event_type, subject_id, "
    "channel, source_id, credential_id, trust_rank, occurred_at, first_received_at, "
    "last_received_at, revision, payload, fingerprint, consent_basis, traffic_label, "
    "policy_version, conflict_count, expires_at, link_id) "
    "SELECT gen_random_uuid(), agency_id, client_id, gen_random_uuid(), event_type, subject_id, "
    "channel, source_id, credential_id, trust_rank, occurred_at, first_received_at, "
    "last_received_at, revision, payload, fingerprint, consent_basis, traffic_label, "
    "policy_version, conflict_count, expires_at, link_id "
    "FROM collected_events, generate_series(1, :n) WHERE event_id = :event"
)


@pytest.fixture
def aw(authenticated_world, api):
    return make_attribution_world(make_identity_world(authenticated_world, api))


def test_bv14_link_event_bound(aw):
    w = aw.w
    link = managed_link(aw.idw.owner, w, "bound-link")
    token = aw.idw.browser_subject()["subject_token"]
    seed = visit(aw, token, link)
    with w.db.migration.begin() as connection:
        connection.execute(text(COPY_EVENT), {"n": 49_999, "event": seed})
    owner = aw.idw.owner
    passed = get(owner, w, "funnel", group_by="link", **span(today()))
    assert passed.status_code == 200, passed.text
    (row,) = passed.json()["rows"]
    assert row["visits"] == {"state": "available", "count": 50_000}
    assert passed.json()["totals"][0]["link_page_views"] == 50_000
    with w.db.migration.begin() as connection:
        connection.execute(text(COPY_EVENT), {"n": 1, "event": seed})
    refused = get(owner, w, "funnel", group_by="link", **span(today()))
    assert (refused.status_code, refused.json()) == (422, {"error": "report_too_large"})
