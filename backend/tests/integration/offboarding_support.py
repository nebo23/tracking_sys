"""Synthetic fixtures for the 017-B offboarding, export and purge tests (D-098).

Agencies are closed through the real closure route and completed by the lifecycle runner after
their grace period is moved into the past. Rows that no cheap flow creates are inserted directly
with the migration engine, with synthetic values that satisfy each table's checks: payment,
integration, booking, CRM, WhatsApp, conversion delivery, webhook source, template, domain,
form, diagnostic, report, branding, invitation and offboarding export rows. Every identity,
number, hostname, key and amount is synthetic; only the guarded disposable database is used.
"""

import secrets
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Agency, AgencyMembership
from app.services.lifecycle import run_lifecycle

NAMES = {"a": "Synthetic Agency A", "b": "Synthetic Agency B"}
ZERO12, ZERO48 = "decode(repeat('00', 12), 'hex')", "decode(repeat('00', 48), 'hex')"
SEALED = f"'k1', {ZERO12}, {ZERO48}, {ZERO12}, decode(repeat('ab', 40), 'hex')"


def digest() -> str:
    return secrets.token_hex(32)


def owner_membership(db, agency: UUID) -> UUID:
    with Session(db.migration) as session:
        member = session.scalar(
            select(AgencyMembership.id)
            .where(AgencyMembership.agency_id == agency, AgencyMembership.role == "owner")
            .order_by(AgencyMembership.created_at)
            .limit(1)
        )
    assert member is not None
    return member


def status_of(db, agency: UUID) -> str:
    with Session(db.migration) as session:
        return session.scalar(select(Agency.status).where(Agency.id == agency))


# Request the closure through the route (exact name and password) and return the response body.
def request_closure(w, api, agency: UUID, owner: str = "owner_a", name: str | None = None):
    client = w.signed_in(owner)
    response = client.post(
        f"/agencies/{agency}/closure",
        json={
            "confirm_name": name or NAMES["a" if agency == w.a else "b"],
            "password": api.password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def end_grace_period(db, agency: UUID) -> None:
    with db.migration.begin() as connection:
        connection.execute(
            text(
                "UPDATE agency_closures SET requested_at = now() - interval '31 days', "
                "closes_at = now() - interval '1 day' "
                "WHERE agency_id = :agency AND cancelled_at IS NULL AND completed_at IS NULL"
            ),
            {"agency": agency},
        )


# Close an agency for good: the request, the end of its grace period and the lifecycle step.
def close_agency(w, api, lifecycle_engine, lifecycle_settings, agency: UUID, **options) -> None:
    request_closure(w, api, agency, **options)
    end_grace_period(w.db, agency)
    result = run_lifecycle(lifecycle_engine, lifecycle_settings)
    assert result["deleted"].get("agency_closures_completed") == 1, result
    assert status_of(w.db, agency) == "closed"


def scoped_tables(db) -> dict[str, set[str]]:
    """Every table that carries agency_id or client_id, with which of the two it carries."""
    with db.migration.connect() as connection:
        found = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name IN ('agency_id', 'client_id')"
            )
        ).all()
    tables: dict[str, set[str]] = {}
    for table, column in found:
        tables.setdefault(table, set()).add(column)
    return tables


def rows_of(db, agency: UUID, clients: list[UUID]) -> dict[str, int]:
    """Rows of the agency or of one of its clients, by scoped table."""
    counts = {}
    with db.migration.connect() as connection:
        for table, columns in sorted(scoped_tables(db).items()):
            conditions = []
            if "agency_id" in columns:
                conditions.append("agency_id = :agency")
            if "client_id" in columns:
                conditions.append("client_id = ANY (:clients)")
            counts[table] = connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE {' OR '.join(conditions)}"),
                {"agency": agency, "clients": clients},
            ).scalar_one()
    return counts


def insert(db, statements: list[tuple[str, dict]]) -> None:
    with db.migration.begin() as connection:
        for statement, values in statements:
            connection.execute(text(statement), values)


# Rows of one client that no cheap flow creates. `connection_id` adds a conversion destination,
# a delivery and an acknowledgement on that connection. Returns the identifiers it created.
def populate_direct(
    db,
    agency: UUID,
    client: UUID,
    member: UUID,
    *,
    connection_id: UUID | None = None,
    phone: str = "2010001",
    hostname: str = "go.agency-a.example.test",
) -> SimpleNamespace:
    ids = SimpleNamespace(
        **{
            name: uuid4()
            for name in (
                "payment",
                "integration",
                "booking",
                "number",
                "pending_number",
                "webhook",
                "domain",
                "schedule",
                "report_export",
                "invitation",
                "destination",
                "delivery",
                "agency_export",
            )
        }
    )
    base = {"agency": agency, "client": client, "member": member}
    common = "gen_random_uuid(), :agency, :client"
    statements = [
        (
            "INSERT INTO payment_sources (id, agency_id, client_id, provider, region, name, "
            "public_key, live_integration_ids, created_by_membership_id) VALUES (:payment, "
            ":agency, :client, 'paymob', 'egypt', 'Synthetic Paymob', :ppk, ARRAY[1001]::bigint[], "
            ":member)",
            {"ppk": "ppk_" + secrets.token_urlsafe(32)},
        ),
        (
            "INSERT INTO payment_source_secrets (id, agency_id, client_id, source_id, version, "
            f"kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext) VALUES ({common}, :payment, 1, "
            f"{SEALED})",
            {},
        ),
        (
            "INSERT INTO payment_callback_diagnostics (id, agency_id, client_id, source_id, "
            f"delivery_digest, received_at, outcome) VALUES ({common}, :payment, :digest, now(), "
            "'unmapped')",
            {"digest": digest()},
        ),
        (
            "INSERT INTO revenue_imports (id, agency_id, client_id, file_digest, total_rows, "
            "stored_rows, duplicate_rows, rejected_rows, committed_by_membership_id, committed_at) "
            f"VALUES ({common}, :digest, 1, 1, 0, 0, :member, now())",
            {"digest": digest()},
        ),
        (
            "INSERT INTO integration_sources (id, agency_id, client_id, kind, name, public_key, "
            "created_by_membership_id) VALUES (:integration, :agency, :client, 'cal_com', "
            "'Synthetic Cal', :isk, :member)",
            {"isk": "isk_" + secrets.token_urlsafe(32)},
        ),
        (
            "INSERT INTO integration_source_secrets (id, agency_id, client_id, source_id, "
            f"version, kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext) VALUES ({common}, "
            f":integration, 1, {SEALED})",
            {},
        ),
        (
            "INSERT INTO integration_deliveries (id, agency_id, client_id, source_id, "
            f"delivery_digest, received_at, outcome) VALUES ({common}, :integration, :digest, "
            "now(), 'applied')",
            {"digest": digest()},
        ),
        (
            "INSERT INTO bookings (id, agency_id, client_id, source_id, provider, status, "
            "first_received_at, updated_at) VALUES (:booking, :agency, :client, :integration, "
            "'cal_com', 'scheduled', now(), now())",
            {},
        ),
        (
            "INSERT INTO booking_events (id, agency_id, client_id, booking_id, source_id, "
            f"provider, kind, ref, occurred_at) VALUES ({common}, :booking, :integration, "
            "'cal_com', 'created', 'synthetic-booking-1', now())",
            {},
        ),
        (
            "INSERT INTO crm_stage_rules (id, agency_id, client_id, pipeline, stage, outcome, "
            f"created_by_membership_id) VALUES ({common}, 'sales', 'won', 'won', :member)",
            {},
        ),
        (
            "INSERT INTO crm_deals (id, agency_id, client_id, source_id, deal_ref, pipeline, "
            f"stage, stage_at, first_received_at, updated_at) VALUES ({common}, :integration, "
            "'synthetic-deal-1', 'sales', 'won', now(), now(), now())",
            {},
        ),
        (
            "INSERT INTO whatsapp_numbers (id, agency_id, client_id, phone_number_id, name, "
            "status, verified_at, created_by_membership_id) VALUES (:number, :agency, :client, "
            ":phone, 'Synthetic line', 'active', now(), :member)",
            {"phone": phone},
        ),
        (
            "INSERT INTO whatsapp_numbers (id, agency_id, client_id, phone_number_id, name, "
            "created_by_membership_id) VALUES (:pending_number, :agency, :client, :phone, "
            "'Synthetic pending line', :member)",
            {"phone": phone + "9"},
        ),
        (
            "INSERT INTO whatsapp_messages (id, agency_id, client_id, number_id, "
            f"message_digest, received_at, has_referral) VALUES ({common}, :number, :digest, "
            "now(), false)",
            {"digest": digest()},
        ),
        (
            "INSERT INTO ingestion_sources (id, agency_id, client_id, creator_membership_id, "
            "kind, name) VALUES (:webhook, :agency, :client, :member, 'webhook', "
            "'Synthetic webhook')",
            {},
        ),
        (
            "INSERT INTO ingestion_source_secrets (id, agency_id, client_id, source_id, version, "
            f"kek_id, wrap_nonce, wrapped_dek, nonce, ciphertext) VALUES ({common}, :webhook, 1, "
            f"{SEALED})",
            {},
        ),
        (
            "INSERT INTO link_utm_templates (id, agency_id, client_id, name, parameters) VALUES "
            f"({common}, 'Synthetic template', '{{}}'::jsonb)",
            {},
        ),
        (
            "INSERT INTO link_domains (id, agency_id, client_id, hostname) VALUES (:domain, "
            ":agency, :client, :hostname)",
            {"hostname": hostname},
        ),
        (
            "INSERT INTO collection_forms (id, agency_id, client_id, form_key, fields) VALUES "
            f"({common}, 'synthetic-contact', '[]'::jsonb)",
            {},
        ),
        (
            "INSERT INTO event_diagnostics (id, agency_id, client_id, day, channel, outcome, "
            f"reason, count) VALUES ({common}, current_date, 'webhook', 'rejected', "
            "'synthetic_case', 1)",
            {},
        ),
        (
            "INSERT INTO report_schedules (id, agency_id, client_id, name, family, parameters, "
            "cadence, hour, time_zone, owner_membership_id, next_run_at) VALUES (:schedule, "
            ":agency, :client, 'Synthetic schedule', 'revenue', '{}'::jsonb, 'daily', 6, 'UTC', "
            ":member, now() + interval '1 day')",
            {},
        ),
        (
            "INSERT INTO report_schedule_recipients (schedule_id, membership_id, agency_id, "
            "client_id) VALUES (:schedule, :member, :agency, :client)",
            {},
        ),
        (
            "INSERT INTO report_exports (id, agency_id, client_id, family, parameters, "
            "period_start, period_end, includes_financials, source, requested_by_membership_id, "
            "status, stored_at, row_count, byte_size, report_revision, expires_at) VALUES "
            "(:report_export, :agency, :client, 'revenue', '{}'::jsonb, '2026-11-01', "
            "'2026-11-03', true, 'manual', :member, 'ready', now(), 1, 10, repeat('a', 64), "
            "now() + interval '6 days')",
            {},
        ),
        (
            "INSERT INTO report_export_contents (export_id, agency_id, client_id, kek_id, "
            "wrap_nonce, wrapped_dek, nonce, ciphertext, alg, aad_version) VALUES "
            f"(:report_export, :agency, :client, {SEALED}, 'A256GCM-ENV-v1', 1)",
            {},
        ),
        (
            "INSERT INTO agency_invitations (id, agency_id, inviter_membership_id, "
            "email_normalized, role, token_digest, expires_at) VALUES (:invitation, :agency, "
            ":member, :email, 'analyst', :digest, now() + interval '7 days')",
            {"email": f"invitee-{secrets.token_hex(4)}@example.test", "digest": digest()},
        ),
        (
            "INSERT INTO invitation_client_grants (agency_id, invitation_id, client_id) VALUES "
            "(:agency, :invitation, :client)",
            {},
        ),
    ]
    if connection_id is not None:
        statements += [
            (
                "INSERT INTO conversion_destinations (id, agency_id, client_id, connection_id, "
                "enabled, created_by_membership_id) VALUES (:destination, :agency, :client, "
                ":connection, true, :member)",
                {"connection": connection_id},
            ),
            (
                "INSERT INTO conversion_deliveries (id, agency_id, client_id, destination_id, "
                "connection_id, event_id, event_name, action_source, event_time, deadline, "
                "currency, currency_exponent, value_minor, consent_basis, policy_version, status, "
                "reason, ended_at) VALUES (:delivery, :agency, :client, :destination, "
                ":connection, :digest, 'Purchase', 'website', now() - interval '1 hour', "
                "now() + interval '1 day', 'EGP', 2, 1000, '{}'::uuid[], "
                "'synthetic-1', 'cancelled', 'connection_ended', now())",
                {"connection": connection_id, "digest": digest()},
            ),
            (
                "INSERT INTO conversion_acknowledgements (id, agency_id, client_id, delivery_id, "
                f"attempt, outcome) VALUES ({common}, :delivery, 1, 'accepted')",
                {},
            ),
        ]
    insert(db, [(statement, {**base, **vars(ids), **extra}) for statement, extra in statements])
    return ids


def branding(db, agency: UUID, member: UUID) -> None:
    insert(
        db,
        [
            (
                "INSERT INTO agency_branding (agency_id, display_name, accent_color, "
                "updated_by_membership_id) VALUES (:agency, 'Synthetic brand', '#112233', "
                ":member)",
                {"agency": agency, "member": member},
            )
        ],
    )


# An offboarding export row with one sealed-shaped part, inserted directly (the real build is
# tested in test_agency_export); status ready or pending.
def agency_export(db, agency: UUID, member: UUID, *, ready: bool = True) -> UUID:
    export_id = uuid4()
    statements = [
        (
            "INSERT INTO agency_exports (id, agency_id, requested_by_membership_id, expires_at) "
            "VALUES (:export, :agency, :member, now() + interval '7 days')",
            {},
        )
    ]
    if ready:
        statements += [
            (
                "UPDATE agency_exports SET status = 'ready', ready_at = now(), part_count = 1, "
                "byte_size = 40, row_count = 0, row_counts = '{}'::jsonb, "
                "manifest_sha256 = repeat('b', 64) WHERE id = :export",
                {},
            ),
            (
                "INSERT INTO agency_export_parts (export_id, part, agency_id, kek_id, wrap_nonce, "
                f"wrapped_dek, nonce, ciphertext, alg, aad_version) VALUES (:export, 1, :agency, "
                f"{SEALED}, 'A256GCM-ENV-v1', 1)",
                {},
            ),
        ]
    insert(
        db,
        [
            (statement, {"export": export_id, "agency": agency, "member": member, **extra})
            for statement, extra in statements
        ],
    )
    return export_id
