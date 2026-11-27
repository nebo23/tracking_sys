"""Migrations 0026-0028 and remaining matrix cases on disposable PostgreSQL (D-075).

JV01: a database at 0025 with synthetic 004/015 data upgrades to one head, keeps its rows and
privileges, gives legacy subjects unknown issuance, and each new revision's downgrade refuses
its populated state. JV04: rewrapping the matching key under a new key-encryption key keeps
its bytes, so matching continues. JV07: a still-held event stays out of every journey. JV08:
token-holder erasure of a merge participant's last evidence closes the edge first. JV12/JV19:
an association racing an attribution withdrawal never leaves an active binding. JV04/logs: no
raw identifier, token or code reaches the application log. Synthetic values only.
"""

import logging
import threading
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from identity_support import ALL, IDENTITY, make_identity_world, rows
from report_support import append
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.ledger import Currency, Evidence, EvidenceClass, Money, OperationKind
from app.models import (
    CollectedEvent,
    CollectionSubject,
    IdentityChange,
    IdentityErasureHold,
    IdentityKeySecret,
    IdentityMerge,
    IdentitySubject,
    RevenueEvidence,
    RevenueIdentityBinding,
)
from app.privacy.token_secrets import LocalKeyring, SealedSecret, rewrap
from app.security import digest

pytestmark = pytest.mark.integration
CONFIG = Config(str(BACKEND_ROOT / "alembic.ini"))


@pytest.fixture
def idw(authenticated_world, api):
    return make_identity_world(authenticated_world, api)


def _version(db) -> str:
    with db.migration.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_populated_upgrade_from_0025_and_guarded_downgrades(world):
    w = world
    assert ScriptDirectory.from_config(CONFIG).get_heads() == ["0033_agency_offboarding"]
    command.downgrade(CONFIG, "0025_whatsapp")
    token_digest = digest("sbj_synthetic-legacy-subject-token-000000000000")
    with Session(w.db.migration) as session, session.begin():
        session.execute(
            text(
                "INSERT INTO collection_subjects (id, agency_id, client_id, token_digest) "
                "VALUES (:id, :agency, :client, :digest)"
            ),
            {"id": uuid4(), "agency": w.a, "client": w.a1, "digest": token_digest},
        )
        session.execute(
            text(
                "INSERT INTO revenue_evidence (id, agency_id, client_id, delivery_id, "
                "source_account_id, operation_id, kind, classification, currency, "
                "currency_exponent, amount_minor, effective_at, received_at, intake, intake_id, "
                "content_digest) VALUES (:id, :agency, :client, 'legacy:1', 'shop', 'L1', 'sale', "
                "'confirmed_capture', 'EGP', 2, 1000, now(), now(), 'csv_import', :intake, :digest)"
            ),
            {"id": uuid4(), "agency": w.a, "client": w.a1, "intake": uuid4(), "digest": "a" * 64},
        )
    command.upgrade(CONFIG, "head")
    assert _version(w.db) == "0033_agency_offboarding"
    legacy = rows(
        w.db, select(CollectionSubject).where(CollectionSubject.token_digest == token_digest)
    )
    assert [item.issuance_channel for item in legacy] == ["unknown"]
    assert len(rows(w.db, select(RevenueEvidence))) == 1
    with w.db.migration.connect() as connection:
        for table, privilege in (
            ("collected_events", "INSERT"),
            ("revenue_evidence", "INSERT"),
            ("identity_assertions", "INSERT"),
            ("ledger_receipts", "INSERT"),
        ):
            assert connection.execute(
                text("SELECT has_table_privilege('tracking_app', :t, :p)"),
                {"t": table, "p": privilege},
            ).scalar_one()
        for table, privilege in (("ledger_receipts", "UPDATE"), ("ledger_movements", "DELETE")):
            assert not connection.execute(
                text("SELECT has_table_privilege('tracking_app', :t, :p)"),
                {"t": table, "p": privilege},
            ).scalar_one()
    # Each new revision refuses to drop its own populated state; a refused downgrade rolls back
    # and the version stays at head.
    statements = [
        (
            "0027_ledger_persistence",
            "INSERT INTO revenue_identity_bindings (id, agency_id, client_id, association_id, "
            "revision, source_account_id, sale_operation_id, state, received_at) VALUES "
            "(:id, :agency, :client, :id, 1, 'shop', 'L1', 'pending', now())",
            "sale associations",
            "DELETE FROM revenue_identity_bindings",
        ),
        (
            "0026_identity_journey",
            "INSERT INTO ledger_projection_state (client_id, agency_id, algorithm, status, "
            "receipt_digest) VALUES (:client, :agency, 'test', 'building', "
            "decode(repeat('00', 32), 'hex'))",
            "persisted ledger",
            "DELETE FROM ledger_projection_state",
        ),
        (
            "0025_whatsapp",
            "INSERT INTO collection_subjects (id, agency_id, client_id, token_digest, "
            "issuance_channel) VALUES (:id, :agency, :client, :digest, 'browser')",
            "identity state",
            "DELETE FROM collection_subjects WHERE issuance_channel = 'browser'",
        ),
    ]
    try:
        for target, insert, message, cleanup in statements:
            with w.db.migration.begin() as connection:
                connection.execute(
                    text(insert),
                    {"id": uuid4(), "agency": w.a, "client": w.a1, "digest": "b" * 64},
                )
            with pytest.raises(RuntimeError, match=message):
                command.downgrade(CONFIG, target)
            assert _version(w.db) == "0033_agency_offboarding"
            with w.db.migration.begin() as connection:
                connection.execute(text(cleanup))
    finally:
        command.upgrade(CONFIG, "head")


def test_matching_key_rewrap_keeps_matching(idw, api):
    w = idw.w
    first = idw.server_subject()
    assert (
        idw.via_server(
            first, ALL, [idw.identifier("email", "wrap@example.test", "email_code")]
        ).status_code
        == 201
    )
    secret = rows(w.db, select(IdentityKeySecret))[0]
    old = api.config.token_keys()
    context = __import__("app.services.identity", fromlist=["_context"])._context(
        secret.agency_id, secret.client_id, secret.id, secret.version
    )
    sealed = SealedSecret(
        secret.kek_id, secret.wrap_nonce, secret.wrapped_dek, secret.nonce, secret.ciphertext
    )
    import base64
    import secrets as random_bytes

    new_key = base64.urlsafe_b64encode(random_bytes.token_bytes(32)).decode().rstrip("=")
    old_text = api.config.token_keyring.get_secret_value()
    keyring = LocalKeyring.from_text(f"{old_text},rewrap:{new_key}", "rewrap")
    rewrapped = rewrap(keyring, sealed, context)
    assert rewrapped.kek_id == "rewrap" and old is not None
    with Session(w.db.migration) as session, session.begin():
        row = session.get(IdentityKeySecret, secret.id)
        row.kek_id, row.wrap_nonce, row.wrapped_dek = (
            rewrapped.kek_id,
            rewrapped.wrap_nonce,
            rewrapped.wrapped_dek,
        )
    from pydantic import SecretStr

    settings = api.config.model_copy(
        update={
            "token_keyring": SecretStr(f"{old_text},rewrap:{new_key}"),
            "token_keyring_active": "rewrap",
        }
    )
    client = api.new_client(settings)
    client.headers["Authorization"] = idw.ingest.headers["Authorization"]
    second = idw.server_subject()
    response = client.post(
        f"{idw.base}/clients/{w.a1}/identity-assertions",
        json={
            "assertion_id": str(uuid4()),
            "subject_token": second["subject_token"],
            "identity_consent_receipt_id": second["receipts"][sorted(ALL).index(IDENTITY)],
            "identifiers": [idw.identifier("email", "wrap@example.test", "email_code")],
        },
    )
    assert response.status_code == 201, response.text
    assert len(rows(w.db, select(IdentitySubject))) == 1  # the same keyed identifier matched


def test_held_event_and_token_erasure_of_a_merge_participant(idw):
    w = idw.w
    tablet = idw.browser_subject()["subject_token"]
    early = idw.event(tablet)
    assert (
        idw.via_browser(
            tablet, [idw.identifier("email", "h1@example.test", "email_code")]
        ).status_code
        == 201
    )
    assert (
        idw.via_browser(
            tablet, [idw.identifier("email", "h2@example.test", "email_code")]
        ).status_code
        == 201
    )
    first, second = rows(w.db, select(IdentitySubject.id).order_by(IdentitySubject.created_at))
    request = idw.owner.post(
        f"{idw.base}/clients/{w.a1}/identity/erasures", json={"subject_id": str(first)}
    )
    assert request.json()["status"] == "on_hold"
    assert (
        len(rows(w.db, select(IdentityErasureHold).where(IdentityErasureHold.state == "held"))) >= 1
    )
    for person in rows(w.db, select(IdentitySubject.id)):
        assert early not in idw.journey(person)  # still held: in nobody's journey
    # Token-holder erasure of the merged member's only device closes the edge first (R006-25).
    d1 = idw.browser_subject()["subject_token"]
    assert (
        idw.via_browser(
            d1, [idw.identifier("email", "keep2@example.test", "email_code")]
        ).status_code
        == 201
    )
    d2 = idw.browser_subject()["subject_token"]
    assert (
        idw.via_browser(d2, [idw.identifier("phone", "+20 10 0000 0404", "phone_code")]).status_code
        == 201
    )
    people = rows(w.db, select(IdentitySubject.id).order_by(IdentitySubject.created_at))
    survivor, lost = people[-2], people[-1]
    merged = idw.owner.post(
        f"{idw.base}/clients/{w.a1}/identity/merges",
        json={
            "operation_id": str(uuid4()),
            "survivor_id": str(survivor),
            "merged_id": str(lost),
            "survivor_version": 1,
            "merged_version": 1,
            "reason_code": "duplicate_account",
        },
    )
    assert merged.status_code == 201
    erased = idw.public_post("erasure", {"subject_token": d2})
    assert erased.status_code == 202
    # The edge was closed first (the survivor's version and change record show it); as an
    # erasure, the closed ledger row naming the erased participant is then deleted (7.2).
    assert (
        rows(w.db, select(IdentityMerge).where(IdentityMerge.id == UUID(merged.json()["merge_id"])))
        == []
    )
    remaining = rows(w.db, select(IdentitySubject).where(IdentitySubject.id == survivor))[0]
    assert (remaining.status, remaining.version) == ("active", 3)
    kinds = rows(w.db, select(IdentityChange.kind).where(IdentityChange.person_id == survivor))
    assert "merge_closed" in kinds
    erased_kinds = rows(w.db, select(IdentityChange.kind).where(IdentityChange.person_id == lost))
    assert erased_kinds[-1] == "erased"
    assert lost not in rows(w.db, select(IdentitySubject.id))
    assert second in rows(w.db, select(IdentitySubject.id))


def test_association_racing_attribution_withdrawal_never_stays_active(idw):
    w = idw.w
    moment = datetime(2026, 11, 20, tzinfo=UTC)
    for round_ in range(3):
        subject = idw.server_subject()
        assertion = uuid4()
        assert (
            idw.via_server(
                subject,
                ALL,
                [idw.identifier("email", f"race{round_}@example.test", "email_code")],
                assertion_id=assertion,
            ).status_code
            == 201
        )
        sale = f"RACE-{round_}"
        append(
            w,
            [
                Evidence(
                    f"d:{sale}",
                    w.a,
                    w.a1,
                    "shop",
                    sale,
                    OperationKind.SALE,
                    EvidenceClass.CONFIRMED_CAPTURE,
                    Money(100, Currency("EGP", 2)),
                    moment,
                    moment,
                )
            ],
            intake="csv_import",
        )
        barrier = threading.Barrier(2)
        results = []

        def link(barrier=barrier, results=results, sale=sale, assertion=assertion):
            barrier.wait()
            results.append(
                idw.ingest.post(
                    f"{idw.base}/clients/{w.a1}/revenue/identity-associations",
                    json={
                        "request_id": str(uuid4()),
                        "source_account_id": "shop",
                        "sale_operation_id": sale,
                        "assertion_id": str(assertion),
                        "expected_revision": None,
                    },
                ).status_code
            )

        def withdraw(barrier=barrier, subject=subject):
            barrier.wait()
            idw.server_subject({"attribution": "withdrawn"}, token=subject["subject_token"])

        threads = [threading.Thread(target=link), threading.Thread(target=withdraw)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results and results[0] in {201, 422}
        current = rows(
            w.db,
            select(RevenueIdentityBinding).where(RevenueIdentityBinding.sale_operation_id == sale),
        )
        assert all(item.state != "active" for item in current)


def test_no_identifier_token_or_code_reaches_the_log(idw, caplog):
    caplog.set_level(logging.DEBUG)
    token = idw.browser_subject()["subject_token"]
    code, challenge = idw.issued_handoff(token)
    response = idw.assertion(
        [
            idw.identifier("email", "logcheck@example.test", "email_code"),
            idw.identifier("phone", "+20 10 0000 0505", "phone_code"),
        ],
        proof={"handoff": code, "challenge": challenge},
    )
    assert response.status_code == 201
    text_log = caplog.text
    for secret in ("logcheck@example.test", "+201000000505", "0000 0505", token, code, challenge):
        assert secret not in text_log
    events = rows(idw.w.db, select(CollectedEvent))
    assert events == [] or all("logcheck" not in str(item.payload) for item in events)
