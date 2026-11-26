"""016-B report bounds and measurements on disposable PostgreSQL (D-089 D10; BV14 and BV19).

Synthetic rows are copied or generated in bulk by the migration role so the bounds are reached
exactly: 50,000 link-tagged page views pass the funnel and 50,001 are refused, and 10,000
groups pass the attribution report and 10,001 are refused, each before any total. The number
of statements of a report does not grow with the number of stored credit rows. The opt-in
measurements (TRACKING_REPORT_MEASURE=1) time one report of each family at 1,000, 10,000 and
100,000 stored credit rows; they are observations, not limits (A3 stays open). Synthetic values
only.
"""

import json
import os
import time
from uuid import uuid4

import pytest
from attribution_support import make_attribution_world
from credit_support import at, get, managed_link, sale_day, span, today, visit
from identity_support import make_identity_world
from report_support import ad_account, connection
from sqlalchemy import event, text

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
    world = make_attribution_world(make_identity_world(authenticated_world, api))
    yield world
    # The bulk rows go at once, before the shared teardown deletes every table row by row
    # (50,000 events with their foreign key checks can outlast its statement timeout).
    with world.w.db.migration.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE collected_events, attribution_credit_changes, "
                "attribution_allocations, attribution_runs, attribution_conversions CASCADE"
            )
        )


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


SERIES = " FROM generate_series(CAST(:first AS integer), CAST(:last AS integer)) AS i"
STORED_CREDIT = (
    # One sale conversion, one complete run, one credited allocation and one credit change per
    # synthetic slot i, all at generation 1 of one model version (written by the migrator).
    "INSERT INTO attribution_conversions (id, agency_id, client_id, generation, slot_key, "
    "conversion_key, kind, source_account_id, sale_operation_id, effective_at, status) "
    "SELECT md5(:salt || 'c' || i)::uuid, :agency, :client, 1, lpad(to_hex(i), 64, '0'), "
    "lpad(to_hex(i), 64, '0') || '.1', 'sale', 'shop', 'M' || i, :at, 'active'" + SERIES,
    "INSERT INTO attribution_runs (id, agency_id, client_id, generation, conversion_id, "
    "model_version_id, revision, status, basis, causes, currency, currency_exponent, "
    "verified_net_minor, window_start, window_end, ledger_generation, receipt_ordinal, "
    "identity_seq) SELECT md5(:salt || 'r' || i)::uuid, :agency, :client, 1, "
    "md5(:salt || 'c' || i)::uuid, :version, 1, 'complete', 'campaign', ARRAY['initial'], "
    "'EGP', 2, 100, :at - interval '30 days', :at, 1, 1, 0" + SERIES,
    "INSERT INTO attribution_allocations (id, agency_id, client_id, run_id, ordinal, credited, "
    "recipient, basis, position, share_numerator, share_denominator, amount_minor, "
    "touchpoint_id, evidence_class, occurred_at, source, campaign_ref) SELECT "
    "md5(:salt || 'a' || i)::uuid, :agency, :client, md5(:salt || 'r' || i)::uuid, 1, true, "
    "'campaign', 'campaign', 1, 1, 1, 100, md5(:salt || 't' || i)::uuid, "
    "'campaign_interaction', :at - interval '1 day', 'tracker', "
    "'g' || (i % CAST(:groups AS integer))" + SERIES,
    "INSERT INTO attribution_credit_changes (id, agency_id, client_id, run_id, "
    "model_version_id, generation, ordinal, conversion_kind, effective_at, recipient, source, "
    "campaign_ref, delta_share_numerator, delta_share_denominator, delta_minor, currency, "
    "currency_exponent) SELECT md5(:salt || 'x' || i)::uuid, :agency, :client, "
    "md5(:salt || 'r' || i)::uuid, :version, 1, 1, 'sale', :at, 'campaign', 'tracker', "
    "'g' || (i % CAST(:groups AS integer)), 1, 1, 100, 'EGP', 2" + SERIES,
)


def stored_credit(w, day, count, groups, *, first=1):
    """Synthetic stored credit of one published generation; returns the model version ID."""
    version = uuid4()
    with w.db.migration.begin() as connection_:
        exists = connection_.execute(
            text("SELECT id FROM attribution_model_versions WHERE client_id = :c"), {"c": w.a1}
        ).scalar()
        if exists is None:
            connection_.execute(
                text(
                    "INSERT INTO attribution_model_versions (id, agency_id, client_id, "
                    "version_key, model, window_seconds, rules, is_default, status) VALUES "
                    "(:v, :a, :c, 'linear_30d_v1', 'linear', 2592000, '008-A.1', true, 'active')"
                ),
                {"v": version, "a": w.a, "c": w.a1},
            )
            connection_.execute(
                text(
                    "INSERT INTO attribution_consumer_state (client_id, agency_id, version, "
                    "generation, status, published_at) VALUES (:c, :a, 1, 1, 'ready', now())"
                ),
                {"a": w.a, "c": w.a1},
            )
        else:
            version = exists
        for statement in STORED_CREDIT:
            connection_.execute(
                text(statement),
                {
                    "salt": "bv19",
                    "agency": w.a,
                    "client": w.a1,
                    "version": version,
                    "at": at(day, 10),
                    "first": first,
                    "last": first + count - 1,
                    "groups": groups,
                },
            )
    return version


class Statements:
    """Counts the statements one report request sends through the application engine."""

    def __init__(self, reader):
        self.engine = reader.app.state.engine
        self.count = 0

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._seen)
        return self

    def __exit__(self, *_):
        event.remove(self.engine, "before_cursor_execute", self._seen)

    def _seen(self, *_):
        self.count += 1


def test_bv19_group_bound(aw):
    w, day = aw.w, sale_day()
    stored_credit(w, day, 10_000, 10_000)
    owner = aw.idw.owner
    passed = get(owner, w, "attribution", page_size=500, **span(day))
    assert passed.status_code == 200, passed.text
    assert passed.json()["page"]["total_rows"] == 10_000
    assert passed.json()["attribution"]["published_generation"] == 1
    stored_credit(w, day, 1, 30_000, first=20_000)  # one more distinct group (g20000)
    refused = get(owner, w, "attribution", page_size=500, **span(day))
    assert (refused.status_code, refused.json()) == (422, {"error": "report_too_large"})
    assert "totals" not in refused.text


def test_bv19_statements_do_not_grow_with_credit_rows(aw):
    w, day = aw.w, sale_day()
    owner = aw.idw.owner
    spend = connection(w, w.a1, "synthetic_meta_ads")
    ad_account(w, spend, "EGP", "Africa/Cairo")
    seen = []
    for first, count in ((1, 1_000), (1_001, 4_000)):
        stored_credit(w, day, count, 50, first=first)
        counts = {}
        for family, params in (
            ("attribution", {}),
            ("funnel", {}),
            ("roas", {"connection_id": spend}),
        ):
            with Statements(owner) as statements:
                response = get(owner, w, family, **params, **span(day))
            assert response.status_code == 200, (family, response.text)
            counts[family] = statements.count
        seen.append(counts)
    assert seen[0] == seen[1], seen
    total = get(owner, w, "attribution", **span(day)).json()["totals"]["sales"]["items"][0]
    assert total["credited_revenue"]["minor"] == 5_000 * 100


@pytest.mark.skipif(
    os.environ.get("TRACKING_REPORT_MEASURE") != "1",
    reason="Set TRACKING_REPORT_MEASURE=1 to record the BV19 measurements.",
)
@pytest.mark.parametrize("size", [1_000, 10_000, 100_000])
def test_bv19_measurements(aw, size, capsys):
    """One report of each family over size stored credit rows; observations, not limits."""
    w, day = aw.w, sale_day()
    started = time.perf_counter()
    stored_credit(w, day, size, 200)
    seeded = time.perf_counter() - started
    owner = aw.idw.owner
    spend = connection(w, w.a1, "synthetic_meta_ads")
    ad_account(w, spend, "EGP", "Africa/Cairo")
    results = {"credit_rows": size, "seed_seconds": round(seeded, 2)}
    for family, params in (
        ("attribution", {}),
        ("attribution_models", {"view": "models"}),
        ("roas", {"connection_id": spend}),
        ("funnel", {}),
    ):
        name = family.split("_")[0]
        get(owner, w, name, **params, **span(day))  # warm the plan cache once
        with Statements(owner) as statements:
            begin = time.perf_counter()
            response = get(owner, w, name, **params, **span(day))
            elapsed = time.perf_counter() - begin
        assert response.status_code == 200, response.text
        results[family] = {"seconds": round(elapsed, 3), "statements": statements.count}
    with capsys.disabled():
        print("BV19 " + json.dumps(results, sort_keys=True))
