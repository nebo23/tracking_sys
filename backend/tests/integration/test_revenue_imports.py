"""Transaction CSV imports and manual declarations on disposable PostgreSQL (specification 015-C).

D-067 decisions D8 to D10 and D14; cases T-30 to T-36 of the entry review section 7.3. Every
file and declaration is synthetic. Declared rows are unverified manual_declaration evidence.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.declarations import MAX_ROWS
from app.ledger import LedgerScope
from app.models import AuditEvent, RevenueEvidence, RevenueImport
from app.services.delivery import ClickIdentifier, SyntheticJourney, candidates_from_ledger
from app.services.lifecycle import run_lifecycle
from app.services.revenue import client_ledger

pytestmark = pytest.mark.integration

HEADER = (
    "operation_id,kind,amount,currency,effective_at,parent_operation_id,source_reference,reason"
)
CSV = {"Content-Type": "text/csv"}


@pytest.fixture
def lab(authenticated_world, api):
    w = authenticated_world
    clients = {}

    def browser(name):
        if name not in clients:
            clients[name] = w.signed_in(name)
        return clients[name]

    def base(agency=None, client=None):
        return f"/agencies/{agency or w.a}/clients/{client or w.a1}"

    def preview(body, name="owner_a", **scope):
        return browser(name).post(
            base(**scope) + "/revenue-imports/preview", content=body, headers=CSV
        )

    def commit(body, name="owner_a", import_id=None, **scope):
        digest = import_id or hashlib.sha256(body).hexdigest()
        return browser(name).post(
            base(**scope) + f"/revenue-imports/{digest}", content=body, headers=CSV
        )

    def declare(name="owner_a", **values):
        data = {
            "operation_id": "M-1",
            "kind": "sale",
            "amount": "75.00",
            "currency": "EGP",
            "effective_at": "2026-11-20T09:00:00+02:00",
            "reason": "Paid in cash at the office",
        }
        data.update(values)
        return browser(name).post(base() + "/revenue-declarations", json=data)

    return SimpleNamespace(
        w=w, api=api, browser=browser, base=base, preview=preview, commit=commit, declare=declare
    )


def _file(*rows):
    return ("\r\n".join((HEADER, *rows)) + "\r\n").encode()


SAMPLE = _file(
    "INV-1,sale,1500.00,EGP,2026-11-10T10:00:00+02:00,,order 1,",
    "INV-2,refund,250.00,EGP,2026-11-11T10:00:00+02:00,INV-1,,partial",
    "INV-3,sale,ten,EGP,2026-11-12T10:00:00+02:00,,,",
    "INV-4,sale,20.00,EGP,2026-11-12T10:00:00+02:00,,,=1+1",
)


def _evidence(w, client_id=None):
    with Session(w.db.migration) as session:
        return list(
            session.scalars(
                select(RevenueEvidence)
                .where(RevenueEvidence.client_id == (client_id or w.a1))
                .order_by(RevenueEvidence.received_at, RevenueEvidence.sequence)
            )
        )


def _imports(w):
    with Session(w.db.migration) as session:
        return session.scalar(select(func.count()).select_from(RevenueImport))


def test_preview_reports_rows_and_stores_nothing(lab):
    # T-30: a preview validates every row and reports closed row codes; nothing is stored.
    response = lab.preview(SAMPLE)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["import_id"] == hashlib.sha256(SAMPLE).hexdigest()
    assert (body["total_rows"], body["valid_rows"], body["rejected_rows"]) == (4, 2, 2)
    assert [(row["row"], row["status"], row["errors"]) for row in body["rows"]] == [
        (1, "valid", []),
        (2, "valid", []),
        (3, "rejected", ["invalid_amount"]),
        (4, "rejected", ["formula_cell"]),
    ]
    assert "ten" not in response.text and "=1+1" not in response.text
    assert _evidence(lab.w) == [] and _imports(lab.w) == 0
    refused = lab.preview(_file().replace(b"operation_id", b"email", 1))
    assert (refused.status_code, refused.json()) == (422, {"error": "personal_data_column"})


def test_commit_stores_once_and_repeats_as_no_op(lab):
    # T-31 (M): a commit stores the valid rows as manual_declaration evidence; a repeated commit
    # with the same import ID is a no-op; the same rows in another file are exact redeliveries.
    first = lab.commit(SAMPLE)
    assert first.status_code == 201, first.text
    record = first.json()["import"]
    assert (record["total_rows"], record["stored_rows"], record["duplicate_rows"]) == (4, 2, 0)
    assert (
        record["rejected_rows"] == 2 and record["import_id"] == hashlib.sha256(SAMPLE).hexdigest()
    )
    rows = _evidence(lab.w)
    assert [(row.operation_id, row.kind, row.classification, row.intake) for row in rows] == [
        ("INV-1", "sale", "manual_declaration", "csv_import"),
        ("INV-2", "refund", "manual_declaration", "csv_import"),
    ]
    assert {str(row.intake_id) for row in rows} == {record["id"]}
    assert {row.actor for row in rows} == {str(lab.w.users.owner_a)}
    again = lab.commit(SAMPLE)
    assert again.status_code == 200 and again.json()["import"] == record
    assert len(_evidence(lab.w)) == 2 and _imports(lab.w) == 1
    other = SAMPLE + b"INV-5,sale,5.00,EGP,2026-11-13T10:00:00+02:00,,,\r\n"
    later = lab.commit(other)
    assert later.status_code == 201
    assert (later.json()["import"]["stored_rows"], later.json()["import"]["duplicate_rows"]) == (
        1,
        2,
    )
    assert len(_evidence(lab.w)) == 3
    mismatch = lab.commit(SAMPLE, import_id="0" * 64)
    assert (mismatch.status_code, mismatch.json()) == (422, {"error": "import_mismatch"})


def test_declared_rows_stay_out_of_verified_totals_and_delivery(lab):
    # T-32 (M): declared rows never enter verified totals and are never enqueued by 014.
    assert lab.commit(SAMPLE).status_code == 201
    assert lab.declare().status_code == 201
    w = lab.w
    report = lab.browser("owner_a").get(lab.base() + "/revenue").json()
    assert report["verified"] == {"totals": [], "transactions": []}
    assert report["declared"]["totals"] == [
        {"currency": "EGP", "sales": "1575.00", "refunds": "250.00"}
    ]
    assert {item["operation_id"] for item in report["declared"]["items"]} == {
        "INV-1",
        "INV-2",
        "M-1",
    }
    assert report["pending"] == [] and report["reconciliation"] == []
    with Session(w.db.runtime) as session:
        ledger = client_ledger(session, w.a, w.a1)
    assert ledger.calculation.transactions == ()
    click = ClickIdentifier("synthetic-fbclid-0002", datetime(2026, 11, 9, tzinfo=UTC), uuid4())
    journeys = {
        (LedgerScope(w.a, w.a1, "declared"), operation): SyntheticJourney("person-1", (), (click,))
        for operation in ("INV-1", "M-1")
    }
    assert candidates_from_ledger(ledger.calculation, journeys) == ()


def test_size_and_row_limits(lab):
    # T-34: files above 2 MiB are answered 413 before parsing, and above 10,000 rows are refused.
    row = "A-{},sale,1.00,EGP,2026-11-01T00:00:00Z,,,"
    allowed = _file(*(row.format(index) for index in range(MAX_ROWS)))
    assert len(allowed) < 2 * 1024 * 1024
    response = lab.preview(allowed)
    assert response.status_code == 200 and response.json()["valid_rows"] == MAX_ROWS
    too_many = _file(*(row.format(index) for index in range(MAX_ROWS + 1)))
    refused = lab.preview(too_many)
    assert (refused.status_code, refused.json()) == (422, {"error": "too_many_rows"})
    large = _file(row.format(1)) + b"#" * (2 * 1024 * 1024)
    for response in (lab.preview(large), lab.commit(large)):
        assert (response.status_code, response.json()) == (413, {"error": "request_too_large"})
    assert _evidence(lab.w) == [] and _imports(lab.w) == 0


def test_permissions_audit_and_isolation(lab):
    # T-35: only an Owner or Admin may preview, commit or declare; each commit and declaration
    # has an audit event; clients are isolated.
    w = lab.w
    for name in ("analyst", "viewer", "owner_b"):
        assert lab.preview(SAMPLE, name).status_code == 403, name
        assert lab.commit(SAMPLE, name).status_code == 403, name
        assert lab.declare(name).status_code == 403, name
    assert lab.preview(SAMPLE, "owner_a", client=w.b1).status_code == 403
    assert lab.commit(SAMPLE, "admin").status_code == 201
    assert lab.commit(SAMPLE, "owner_a", client=w.a2).status_code == 201
    assert lab.declare("admin").status_code == 201
    assert {row.client_id for row in _evidence(w)} == {w.a1}
    assert len(_evidence(w, w.a2)) == 2
    with Session(w.db.migration) as session:
        actions = sorted(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.action.in_(("revenue_import.committed", "revenue.declared"))
                )
            )
        )
        imports = session.scalars(select(RevenueImport.client_id)).all()
    assert actions == ["revenue.declared", "revenue_import.committed", "revenue_import.committed"]
    assert sorted(map(str, imports)) == sorted([str(w.a1), str(w.a2)])
    assert lab.browser("owner_a").get(lab.base(client=w.a2) + "/revenue").json()["declared"][
        "totals"
    ] == [{"currency": "EGP", "sales": "1500.00", "refunds": "250.00"}]


def test_manual_declaration_records_actor_and_reason(lab):
    # T-36: a manual declaration records its actor and reason and stays unverified.
    response = lab.declare()
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "stored"
    assert response.json()["declaration"]["amount"] == "75.00"
    (row,) = _evidence(lab.w)
    assert (row.intake, row.intake_id, row.classification) == (
        "manual_entry",
        None,
        "manual_declaration",
    )
    assert (row.actor, row.reason) == (str(lab.w.users.owner_a), "Paid in cash at the office")
    assert lab.declare().json()["status"] == "duplicate"
    for values, code in (
        ({"reason": None}, "missing_value"),
        ({"amount": "-1"}, "formula_cell"),
        ({"reason": "call +20 100 000 0931"}, "prohibited_value"),
        ({"kind": "refund"}, "invalid_parent"),
    ):
        refused = lab.declare(**values)
        assert (refused.status_code, refused.json()) == (422, {"error": code}), values
    assert len(_evidence(lab.w)) == 1


def test_lifecycle_deletes_import_records_after_13_months(
    lab, lifecycle_engine, lifecycle_settings
):
    # D14: import records 395 days after the commit; the evidence stays.
    assert lab.commit(SAMPLE).status_code == 201
    other = _file("INV-9,sale,9.00,EGP,2026-11-13T10:00:00+02:00,,,")
    assert lab.commit(other).status_code == 201
    w = lab.w
    with Session(w.db.migration) as session, session.begin():
        first = session.scalars(
            select(RevenueImport.id).order_by(RevenueImport.committed_at)
        ).first()
        session.execute(
            update(RevenueImport)
            .where(RevenueImport.id == first)
            .values(committed_at=datetime.now(UTC) - timedelta(days=396))
        )
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["status"] == "completed" and result["deleted"]["revenue_imports"] == 1
    assert _imports(w) == 1 and len(_evidence(w)) == 3
