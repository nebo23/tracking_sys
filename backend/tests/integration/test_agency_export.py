"""The offboarding export of a closing agency (017-B, D-098 D2 to D5).

Cases OV01 to OV06 of the entry review's verification matrix and the sequenced part of OV17 (a
completion between the build and its store), on synthetic data in the disposable database only.
The concurrent cases of OV17 are in test_agency_offboarding_journey.py.
"""

import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from attribution_support import make_attribution_world
from cryptography.exceptions import InvalidTag
from identity_support import make_identity_world
from offboarding_support import (
    end_grace_period,
    owner_membership,
    populate_direct,
    request_closure,
)
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app import agency_plans
from app.models import (
    AgencyExport,
    AgencyExportPart,
    AuditEvent,
    AuthRateLimit,
    CollectionSubject,
)
from app.privacy.token_secrets import SealedSecret, open_bytes
from app.services import agency_exports
from app.services.agency_exports import CATALOG, build_pending, seal_context
from app.services.agency_offboarding import run_offboarding
from app.services.lifecycle import run_lifecycle
from app.services.tenancy import Role, tenancy_transaction

pytestmark = pytest.mark.integration


def _url(agency, suffix=""):
    return f"/agencies/{agency}/closure/export{suffix}"


def _forget_throttles(db) -> None:
    with Session(db.migration) as session, session.begin():
        session.execute(delete(AuthRateLimit))


def _request(client, agency, password):
    body = {} if password is None else {"password": password}
    return client.post(_url(agency), json=body)


def _requested(w, api, agency=None, owner="owner_a") -> dict:
    response = _request(w.signed_in(owner), agency or w.a, api.password)
    assert response.status_code == 202, response.text
    return response.json()


def _export(db, export_id) -> AgencyExport:
    with Session(db.migration) as session:
        return session.get(AgencyExport, export_id)


def _parts(db, export_id) -> list[AgencyExportPart]:
    with Session(db.migration) as session:
        return list(
            session.scalars(
                select(AgencyExportPart)
                .where(AgencyExportPart.export_id == export_id)
                .order_by(AgencyExportPart.part)
            )
        )


def _opened(api, part: AgencyExportPart, *, agency=None, export=None, number=None) -> bytes:
    sealed = SealedSecret(
        part.kek_id,
        part.wrap_nonce,
        part.wrapped_dek,
        part.nonce,
        part.ciphertext,
        part.alg,
        part.aad_version,
    )
    context = seal_context(agency or part.agency_id, export or part.export_id, number or part.part)
    return open_bytes(api.config.token_keys(), sealed, context)


def _audits(db, action) -> list[AuditEvent]:
    with Session(db.migration) as session:
        return list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id)
            )
        )


def _download(client, agency):
    return client.get(_url(agency, "/download"))


def test_ov01_export_request_is_owner_only_reauthenticated_and_audited(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    refused = _request(owner, w.a, api.password)
    assert (refused.status_code, refused.json()) == (409, {"error": "agency_not_closing"})
    closure = request_closure(w, api, w.a)["closure"]
    for name in ("admin", "analyst", "viewer", "outsider", "owner_b"):
        denied = _request(w.signed_in(name), w.a, api.password)
        assert (denied.status_code, denied.json()) == (403, {"error": "access_denied"})
    _forget_throttles(w.db)
    for password in ("Wrong password for tests 1", None):
        wrong = _request(owner, w.a, password)
        assert (wrong.status_code, wrong.json()) == (401, {"error": "invalid_credentials"})
    _forget_throttles(w.db)
    first = _request(owner, w.a, api.password)
    assert first.status_code == 202, first.text
    body = first.json()
    assert body["export"]["status"] == "pending" and body["export"]["download_count"] == 0
    window = body["window_ends_at"]
    assert window is not None
    assert _iso(window) == _iso(closure["closes_at"]) - timedelta(hours=24), (
        "the window ends 24 hours before the closing time"
    )
    (requested,) = _audits(w.db, "agency.export_requested")
    assert (requested.actor_user_id, requested.resource_type) == (w.users.owner_a, "agency_export")
    assert requested.resource_id == UUID(body["export"]["id"])
    # A new request replaces the open export: the first one is revoked and audited.
    second = _request(owner, w.a, api.password).json()["export"]
    assert _export(w.db, UUID(body["export"]["id"])).status == "revoked"
    (revoked,) = _audits(w.db, "agency.export_revoked")
    assert revoked.resource_id == UUID(body["export"]["id"])
    assert owner.get(_url(w.a)).json()["export"]["id"] == second["id"]
    # Bearer keys never reach the routes; the request is throttled three times an hour.
    key = api.new_client()
    key.headers["Authorization"] = "Bearer trk_synthetic_not_a_key"
    assert key.post(_url(w.a), json={"password": api.password}).status_code == 401
    assert key.get(_url(w.a)).status_code == 401
    assert _request(owner, w.a, api.password).status_code == 202
    throttled = _request(owner, w.a, api.password)
    assert (throttled.status_code, throttled.json()["error"]) == (429, "rate_limited")
    assert len(_audits(w.db, "agency.export_requested")) == 3


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_ov01_export_window_and_agency_status(
    authenticated_world, api, lifecycle_engine, lifecycle_settings
):
    w = authenticated_world
    request_closure(w, api, w.a)
    owner = w.signed_in("owner_a")
    for hours, status in ((23, 409), (25, 202)):
        with w.db.migration.begin() as connection:
            connection.execute(
                text(
                    "UPDATE agency_closures SET closes_at = now() + make_interval(hours => :h) "
                    "WHERE agency_id = :a"
                ),
                {"h": hours, "a": w.a},
            )
        _forget_throttles(w.db)
        response = _request(owner, w.a, api.password)
        assert response.status_code == status, response.text
        if status == 409:
            assert response.json() == {"error": "export_window_ended"}
    # A suspended agency, and a closed one, are refused like any other route.
    assert agency_plans.run(w.db.runtime, "suspend", agency=w.b)[0] == 0
    _forget_throttles(w.db)
    assert _request(w.signed_in("owner_b"), w.b, api.password).status_code == 403
    end_grace_period(w.db, w.a)
    assert (
        run_lifecycle(lifecycle_engine, lifecycle_settings)["deleted"]["agency_closures_completed"]
        == 1
    )
    _forget_throttles(w.db)
    for response in (
        _request(owner, w.a, api.password),
        owner.get(_url(w.a)),
        _download(owner, w.a),
    ):
        assert (response.status_code, response.json()) == (403, {"error": "access_denied"})


def _populated(w, api):
    aw = make_attribution_world(make_identity_world(w, api))
    alice = aw.person("alice@example.test")
    bob = aw.person("bob@example.test")
    aw.person("carol@example.test", client=w.a2)
    aw.touch(alice.token, "spring")
    aw.lead(alice.token)
    aw.sale("op-2001")
    aw.associate(alice.assertion, "op-2001")
    aw.merge(alice.id, bob.id)
    aw.settle()
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    populate_direct(
        w.db,
        w.b,
        w.b1,
        owner_membership(w.db, w.b),
        phone="2010002",
        hostname="go.agency-b.example.test",
    )
    return aw


def _client_rows(db, table, client) -> int:
    column = "id" if table == "client_workspaces" else "client_id"
    with db.migration.connect() as connection:
        return connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :c"), {"c": UUID(client)}
        ).scalar_one()


def _excluded_values(db, agency) -> set[str]:
    """Values of excluded digest and key columns of the agency, which must never be exported."""
    statements = (
        "SELECT token_digest FROM collection_subjects WHERE agency_id = :a",
        "SELECT fingerprint FROM collected_events WHERE agency_id = :a",
        "SELECT notice_sha256 FROM consent_records WHERE agency_id = :a",
        "SELECT public_key FROM ingestion_sources WHERE agency_id = :a AND public_key IS NOT NULL",
        "SELECT public_key FROM payment_sources WHERE agency_id = :a",
        "SELECT public_key FROM integration_sources WHERE agency_id = :a",
        "SELECT content_digest FROM revenue_evidence WHERE agency_id = :a",
        "SELECT encode(receipt_digest, 'hex') FROM ledger_receipts WHERE agency_id = :a",
        "SELECT slot_key FROM attribution_conversions WHERE agency_id = :a",
        "SELECT message_digest FROM whatsapp_messages WHERE agency_id = :a",
        "SELECT token_digest FROM service_credentials WHERE agency_id = :a",
        "SELECT token_digest FROM agency_invitations WHERE agency_id = :a",
        "SELECT encode(key_bytes, 'hex') FROM identity_keys WHERE agency_id = :a",
        "SELECT email_normalized FROM agency_invitations WHERE agency_id = :a",
    )
    found: set[str] = set()
    with db.migration.connect() as connection:
        for statement in statements:
            found |= {
                value for value in connection.execute(text(statement), {"a": agency}).scalars()
            }
    return found


def test_ov02_export_contents_match_the_catalog_and_manifest(authenticated_world, api):
    w = authenticated_world
    _populated(w, api)
    request_closure(w, api, w.a)
    export_id = UUID(_requested(w, api)["export"]["id"])
    assert build_pending(w.db.runtime, api.config)["built"] == 1
    item = _export(w.db, export_id)
    response = _download(w.signed_in("owner_a"), w.a)
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest_bytes = archive.read("manifest.json")
    manifest = json.loads(manifest_bytes)
    assert hashlib.sha256(manifest_bytes).hexdigest() == item.manifest_sha256
    assert (manifest["format"], manifest["format_version"]) == ("tracking-agency-export", 1)
    assert manifest["schema_version"] == "0034_saas_billing"
    assert (manifest["agency_id"], manifest["export_id"]) == (str(w.a), str(export_id))
    expected = {f"clients/{c}/{table}.jsonl" for c in (w.a1, w.a2) for table, _ in CATALOG}
    assert set(archive.namelist()) == expected | {"manifest.json"}
    assert {item["path"] for item in manifest["files"]} == expected
    total = 0
    text_of_members = []
    for entry in manifest["files"]:
        content = archive.read(entry["path"])
        text_of_members.append(content.decode())
        lines = content.splitlines()
        _, client, name = entry["path"].split("/")
        table = name.removesuffix(".jsonl")
        columns = dict(CATALOG)[table]
        assert entry["rows"] == len(lines) == _client_rows(w.db, table, client), entry["path"]
        assert entry["bytes"] == len(content)
        assert entry["sha256"] == hashlib.sha256(content).hexdigest()
        for line in lines:
            assert list(json.loads(line)) == list(columns)
        total += entry["rows"]
    assert manifest["total_rows"] == total == item.row_count
    assert item.row_counts == {entry["path"]: entry["rows"] for entry in manifest["files"]}
    # The populated tables are really in the file, with their internal IDs.
    rows = {entry["path"].split("/")[2]: 0 for entry in manifest["files"]}
    for entry in manifest["files"]:
        rows[entry["path"].split("/")[2]] += entry["rows"]
    for table in (
        "client_workspaces",
        "collected_events",
        "consent_records",
        "identity_subjects",
        "identity_links",
        "identity_merges",
        "revenue_evidence",
        "ledger_transactions",
        "attribution_conversions",
        "attribution_allocations",
        "bookings",
        "crm_deals",
        "whatsapp_messages",
        "payment_sources",
        "report_schedules",
    ):
        assert rows[f"{table}.jsonl"] > 0, table
    # No excluded column, secret, digest, token or other agency's row is in the file.
    everything = "\n".join(text_of_members) + manifest_bytes.decode()
    for value in _excluded_values(w.db, w.a):
        assert value not in everything
    for other in (str(w.b), str(w.b1), str(w.b2)):
        assert other not in everything
    for absent in ("Synthetic Agency", "owner_a@example.test", "kek_id", "ciphertext"):
        assert absent not in everything
    assert "Synthetic" not in manifest_bytes.decode()
    with Session(w.db.migration) as session:
        subject = session.scalars(select(CollectionSubject.token_digest).limit(1)).first()
    assert subject is not None and subject not in everything


def test_ov03_export_beyond_the_bound_fails_without_storing(authenticated_world, api, monkeypatch):
    w = authenticated_world
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    request_closure(w, api, w.a)
    for bound, value in (("MAX_ROWS", 3), ("MAX_BYTES", 300)):
        with monkeypatch.context() as patch:
            patch.setattr(agency_exports, bound, value)
            _forget_throttles(w.db)
            export_id = UUID(_requested(w, api)["export"]["id"])
            assert build_pending(w.db.runtime, api.config) == {
                "built": 0,
                "failed": 1,
                "discarded": 0,
                "superseded": 0,
                "skipped": 0,
            }
        failed = _export(w.db, export_id)
        assert (failed.status, failed.error_code, failed.part_count) == (
            "failed",
            "export_too_large",
            None,
        )
        assert _parts(w.db, export_id) == []
        state = w.signed_in("owner_a").get(_url(w.a)).json()["export"]
        assert (state["status"], state["error_code"]) == ("failed", "export_too_large")
    _forget_throttles(w.db)
    export_id = UUID(_requested(w, api)["export"]["id"])
    assert build_pending(w.db.runtime, api.config)["built"] == 1
    assert _export(w.db, export_id).status == "ready"


def test_ov03_a_zip_that_fails_its_checks_is_not_stored(authenticated_world, api, monkeypatch):
    w = authenticated_world
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    request_closure(w, api, w.a)
    original = agency_exports.write_zip

    def miscounted(engine, handle, agency_id, export_id):
        files, manifest = original(engine, handle, agency_id, export_id)
        return [{**files[0], "rows": files[0]["rows"] + 1}, *files[1:]], manifest

    def damaged(engine, handle, agency_id, export_id):
        files, manifest = original(engine, handle, agency_id, export_id)
        handle.seek(-30, 2)
        handle.write(b"\x00" * 30)
        handle.flush()
        return files, manifest

    for tamper in (miscounted, damaged):
        with monkeypatch.context() as patch:
            patch.setattr(agency_exports, "write_zip", tamper)
            _forget_throttles(w.db)
            export_id = UUID(_requested(w, api)["export"]["id"])
            assert build_pending(w.db.runtime, api.config)["failed"] == 1
        failed = _export(w.db, export_id)
        assert (failed.status, failed.error_code) == ("failed", "build_failed"), tamper
        assert _parts(w.db, export_id) == []


def test_ov04_parts_are_sealed_and_bound_to_their_export(authenticated_world, api, monkeypatch):
    w = authenticated_world
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    monkeypatch.setattr(agency_exports, "PART_BYTES", 1024)
    request_closure(w, api, w.a)
    export_id = UUID(_requested(w, api)["export"]["id"])
    assert build_pending(w.db.runtime, api.config)["built"] == 1
    item = _export(w.db, export_id)
    parts = _parts(w.db, export_id)
    assert item.part_count == len(parts) >= 3
    assert [part.part for part in parts] == list(range(1, len(parts) + 1))
    opened = b"".join(_opened(api, part) for part in parts)
    assert len(opened) == item.byte_size
    assert all(len(_opened(api, part)) <= 1024 for part in parts)
    for part in parts:
        assert (part.agency_id, part.alg, part.aad_version) == (w.a, "A256GCM-ENV-v1", 1)
        for plaintext in (b"clients/", b"manifest", b"PK\x03\x04", b"Synthetic"):
            assert plaintext not in part.ciphertext
    # A part opens only for its agency, its export and its place.
    first = parts[0]
    for mismatch in ({"number": 2}, {"export": w.a1}, {"agency": w.b}):
        with pytest.raises(InvalidTag):
            _opened(api, first, **mismatch)
    response = _download(w.signed_in("owner_a"), w.a)
    assert response.status_code == 200 and response.content == opened


def test_ov05_download_streams_the_built_zip_for_owners_only(authenticated_world, api):
    w = authenticated_world
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    with tenancy_transaction(w.db.runtime, w.users.owner_a) as service:
        service.add_member(w.a, w.users.second_owner, Role.OWNER)
    request_closure(w, api, w.a)
    _requested(w, api)
    assert build_pending(w.db.runtime, api.config)["built"] == 1
    for name in ("admin", "analyst", "viewer", "outsider", "owner_b"):
        denied = _download(w.signed_in(name), w.a)
        assert (denied.status_code, denied.json()) == (403, {"error": "access_denied"})
    item = _export(w.db, UUID(w.signed_in("owner_a").get(_url(w.a)).json()["export"]["id"]))
    built = b"".join(_opened(api, part) for part in _parts(w.db, item.id))
    for name in ("owner_a", "second_owner"):
        response = _download(w.signed_in(name), w.a)
        assert response.status_code == 200
        assert response.content == built
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["content-length"] == str(item.byte_size)
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-disposition"] == (
            'attachment; filename="agency-export.zip"'
        )
    after = _export(w.db, item.id)
    assert after.download_count == 2 and after.last_downloaded_at is not None
    assert zipfile.ZipFile(io.BytesIO(built)).testzip() is None


def test_ov05_download_is_gone_after_expiry_revocation_or_purge(
    authenticated_world, api, lifecycle_engine, lifecycle_settings
):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    request_closure(w, api, w.a)
    # Expiry: the file is refused at once and its parts leave with the lifecycle runner.
    first = UUID(_requested(w, api)["export"]["id"])
    assert build_pending(w.db.runtime, api.config)["built"] == 1
    with w.db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE agency_exports SET requested_at = now() - interval '8 days', "
                "ready_at = now() - interval '8 days', expires_at = now() - interval '1 day' "
                "WHERE id = :e"
            ),
            {"e": first},
        )
    gone = _download(owner, w.a)
    assert (gone.status_code, gone.json()) == (410, {"error": "export_gone"})
    assert owner.get(_url(w.a)).json()["export"]["status"] == "expired"
    assert (
        run_lifecycle(lifecycle_engine, lifecycle_settings)["deleted"]["agency_export_parts"] >= 1
    )
    assert _parts(w.db, first) == [] and _export(w.db, first).status == "ready"
    # Revocation: a new request replaces the file; the new one is not ready yet.
    _forget_throttles(w.db)
    second = UUID(_requested(w, api)["export"]["id"])
    assert _export(w.db, first).status == "revoked"
    pending = _download(owner, w.a)
    assert (pending.status_code, pending.json()) == (409, {"error": "export_not_ready"})
    assert build_pending(w.db.runtime, api.config)["built"] == 1
    assert _download(owner, w.a).status_code == 200
    # A cancellation revokes the open export and deletes its parts at once.
    assert owner.delete(f"/agencies/{w.a}/closure").status_code == 204
    assert _export(w.db, second).status == "revoked" and _parts(w.db, second) == []
    cancelled = _download(owner, w.a)
    assert (cancelled.status_code, cancelled.json()) == (409, {"error": "agency_not_closing"})
    assert len(_audits(w.db, "agency.export_revoked")) == 2
    # Closure again and completion: nothing can be exported any more; the purge removes it.
    _forget_throttles(w.db)
    request_closure(w, api, w.a)
    third = UUID(_requested(w, api)["export"]["id"])
    assert build_pending(w.db.runtime, api.config)["built"] == 1
    end_grace_period(w.db, w.a)
    run_lifecycle(lifecycle_engine, lifecycle_settings)
    closed = _download(owner, w.a)
    assert (closed.status_code, closed.json()) == (403, {"error": "access_denied"})
    assert _export(w.db, third).status == "ready"
    run_offboarding(w.db.runtime, api.config)
    assert run_lifecycle(lifecycle_engine, lifecycle_settings)["deleted"]["agencies_purged"] == 1
    assert _export(w.db, third) is None and _parts(w.db, third) == []


def test_ov06_export_pending_at_completion_is_discarded(
    authenticated_world, api, lifecycle_engine, lifecycle_settings
):
    w = authenticated_world
    populate_direct(w.db, w.a, w.a1, owner_membership(w.db, w.a))
    request_closure(w, api, w.a)
    export_id = UUID(_requested(w, api)["export"]["id"])
    end_grace_period(w.db, w.a)
    run_lifecycle(lifecycle_engine, lifecycle_settings)
    result = build_pending(w.db.runtime, api.config)
    assert (result["built"], result["discarded"]) == (0, 1)
    failed = _export(w.db, export_id)
    assert (failed.status, failed.error_code) == ("failed", "closure_completed")
    assert _parts(w.db, export_id) == []


def test_ov17_a_completion_between_build_and_store_discards_the_export(
    authenticated_world, api, lifecycle_engine, lifecycle_settings, monkeypatch
):
    w = authenticated_world
    populate_direct(
        w.db,
        w.b,
        w.b1,
        owner_membership(w.db, w.b),
        phone="2010002",
        hostname="go.agency-b.example.test",
    )
    request_closure(w, api, w.b, owner="owner_b")
    export_id = UUID(_requested(w, api, agency=w.b, owner="owner_b")["export"]["id"])
    completed = []

    def complete(built: UUID) -> None:
        end_grace_period(w.db, w.b)
        completed.append(run_lifecycle(lifecycle_engine, lifecycle_settings))

    monkeypatch.setattr(agency_exports, "before_store", complete)
    assert build_pending(w.db.runtime, api.config)["discarded"] == 1
    assert completed[0]["deleted"]["agency_closures_completed"] == 1
    failed = _export(w.db, export_id)
    assert (failed.status, failed.error_code) == ("failed", "closure_completed")
    assert _parts(w.db, export_id) == []
