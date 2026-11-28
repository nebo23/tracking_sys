"""Platform billing: prices, standings, subscriptions, checkouts, events, payments, adjustments
and provider actions

Revision ID: 0034_saas_billing
Revises: 0033_agency_offboarding
Created: 2026-11-28

Specification 017-C (D-103, decisions D3, D5, D6, D7, D10, D11 and D13;
specs/017-saas-lifecycle/design-017c.md section 3). Adds billing_prices (the operator's price
catalog against the 017-A plans, in USD, monthly or annual, immutable apart from the offer
state), agency_billing (one standing per agency), agency_subscriptions (the agency's Paddle
subscriptions; at most one primary subscription has not ended), billing_checkouts (at most one
open checkout per agency, 24 hours), billing_events (each verified Paddle event stored once by
its event ID, with allowlisted fields), billing_payments and billing_adjustments (Paddle's
transactions and adjustments), and billing_actions (the provider actions of an agency closure).

Existing tables: saas_plans gains the seeded billing_hold plan, whose counted limits are all
zero; agency_plan_assignments accepts assignments by billing with the reasons subscription and
billing_hold; audit_events accepts the billing actions and resources, and platform-level
events of a billing price; mail_outbox accepts the trial_ending and billing_hold messages.
Every existing agency that is not purged receives a complimentary standing.

purge_agency_batch is replaced: it deletes the agency's standing, checkouts, events and
actions first and keeps its subscriptions, payments and adjustments as financial records, and
it keeps a waiting agency while one of its billing actions is pending. tracking_app may read
and insert the new tables and update only their mutable columns; it deletes none of them.
tracking_lifecycle may delete billing events and checkouts past their retention, and queue the
cancellation of a closed agency's subscriptions. The downgrade refuses every stored billing row
beyond the complimentary standings without billing state, and restores the 0033 function.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0034_saas_billing"
down_revision: str | Sequence[str] | None = "0033_agency_offboarding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRICES = "billing_prices"
STANDINGS = "agency_billing"
SUBSCRIPTIONS = "agency_subscriptions"
CHECKOUTS = "billing_checkouts"
EVENTS = "billing_events"
PAYMENTS = "billing_payments"
ADJUSTMENTS = "billing_adjustments"
ACTIONS = "billing_actions"
# Children first.
TABLES = (ACTIONS, ADJUSTMENTS, PAYMENTS, EVENTS, CHECKOUTS, SUBSCRIPTIONS, STANDINGS, PRICES)
PURGES = "agency_purges"
FUNCTION = "purge_agency_batch(uuid, integer)"
MAX_BUDGET = 10_000
MAX_AMOUNT_CENTS = 100_000_000
HOLD_PLAN = "billing_hold"

STANDING_REASONS = (
    ("complimentary", ("migration", "billing_disabled", "operator_grant")),
    ("trialing", ("new_agency",)),
    ("subscribed", ("subscription_active", "payment_recovered")),
    ("past_due", ("payment_failed",)),
    ("hold", ("trial_ended", "grant_ended", "subscription_canceled", "subscription_paused")),
)
ACTION_REASONS = (
    ("cancel_next_period", "closure_requested"),
    ("remove_scheduled_cancel", "closure_cancelled"),
    ("cancel_now", "closure_completed"),
)
NEW_ACTIONS = (
    "billing_price.registered",
    "billing_price.retired",
    "billing.granted",
    "billing.grant_ended",
    "billing.trial_extended",
    "billing.reconciled",
    "billing.checkout_created",
    "billing.plan_change_requested",
    "billing.cancel_scheduled",
    "billing.cancel_removed",
)
NEW_RESOURCES = ("billing_price", "agency_billing", "billing_checkout", "agency_subscription")
NEW_PURPOSES = ("trial_ending", "billing_hold")
PREVIOUS_ACTIONS = (
    "'agency.created', 'agency.updated', 'client.created', 'client.updated', "
    "'membership.created', 'membership.updated', 'grant.created', 'grant.updated', "
    "'grant.revoked', 'invitation.created', 'invitation.revoked', 'invitation.accepted', "
    "'credential.created', 'credential.revoked', 'source.created', 'source.updated', "
    "'source.secret_rotated', 'form.updated', 'deletion.requested', "
    "'campaign.created', 'campaign.updated', 'content.created', 'content.updated', "
    "'template.created', 'template.updated', 'origin.created', 'origin.updated', "
    "'domain.created', 'domain.updated', 'domain.challenge_issued', 'domain.checked', "
    "'link.created', 'link.updated', 'connector.connected', 'connector.reconnected', "
    "'connector.disconnect_requested', 'destination.created', 'destination.updated', "
    "'delivery.requeued', 'delivery.dismissed', 'payment_source.created', "
    "'payment_source.updated', 'payment_source.secret_replaced', "
    "'revenue_import.committed', 'revenue.declared', 'integration.created', "
    "'integration.updated', 'integration.secret_replaced', 'crm_rule.created', "
    "'crm_rule.updated', 'whatsapp_number.created', 'whatsapp_number.updated', "
    "'identity.merged', 'identity.unmerged', 'identity.erased', 'identity.erasure_resolved', "
    "'revenue.reconciliation_reviewed', 'revenue.association_detached', "
    "'attribution.model_created', 'attribution.model_default_set', "
    "'attribution.model_retired', 'agency.plan_assigned', 'agency.suspended', "
    "'agency.reactivated', 'agency.closure_requested', 'agency.closure_cancelled', "
    "'plan.created', 'plan.default_set', 'report_export.created', 'report_export.revoked', "
    "'report_schedule.created', 'report_schedule.updated', 'report_schedule.deleted', "
    "'branding.updated', 'agency.export_requested', 'agency.export_revoked'"
)
PREVIOUS_RESOURCES = (
    "'agency', 'client', 'membership', 'invitation', 'credential', "
    "'source', 'form', 'deletion_request', 'campaign', 'content_reference', "
    "'utm_template', 'destination_origin', 'domain', 'link', 'connection', "
    "'destination', 'delivery', 'payment_source', 'revenue_import', 'revenue_evidence', "
    "'integration_source', 'crm_rule', 'whatsapp_number', 'identity_subject', 'revenue_issue', "
    "'revenue_association', 'attribution_model', 'plan', 'plan_assignment', 'agency_closure', "
    "'report_export', 'report_schedule', 'agency_branding', 'agency_export'"
)
PREVIOUS_PURPOSES = "'verify', 'reset', 'invitation', 'report_ready'"
PREVIOUS_SCOPE = (
    "agency_id IS NOT NULL OR (actor_kind = 'platform_operator' AND resource_type = 'plan')"
)
SCOPE = (
    "agency_id IS NOT NULL OR (actor_kind = 'platform_operator' "
    "AND resource_type IN ('plan', 'billing_price'))"
)
PREVIOUS_ASSIGNED_BY = "assigned_by IN ('default', 'platform_operator')"
PREVIOUS_ASSIGNMENT_REASONS = "reason IN ('initial', 'new_agency', 'plan_change', 'correction')"
PREVIOUS_REASON_MATCHES = "(assigned_by = 'default') = (reason IN ('initial', 'new_agency'))"
ASSIGNED_BY = "assigned_by IN ('default', 'platform_operator', 'billing')"
ASSIGNMENT_REASONS = (
    "reason IN ('initial', 'new_agency', 'plan_change', 'correction', 'subscription', "
    "'billing_hold')"
)
REASON_MATCHES = (
    "(assigned_by = 'default' AND reason IN ('initial', 'new_agency')) "
    "OR (assigned_by = 'platform_operator' AND reason IN ('plan_change', 'correction')) "
    "OR (assigned_by = 'billing' AND reason IN ('subscription', 'billing_hold'))"
)

# The purge order of 0033 (design-017b.md section 1.2), unchanged. v_clients holds the
# agency's client IDs; p_agency is the agency.
CLIENTS = "client_id = ANY (v_clients)"
AGENCY = "agency_id = p_agency"


def _via(column: str, parent: str, scope: str) -> str:
    return f"{column} IN (SELECT id FROM public.{parent} WHERE {scope})"


PARTS = "agency_export_parts"
EXPORTS = "agency_exports"
PURGE_0033 = (
    (PARTS, _via("export_id", EXPORTS, AGENCY)),
    (EXPORTS, AGENCY),
    ("report_export_contents", _via("export_id", "report_exports", AGENCY)),
    ("report_exports", AGENCY),
    ("report_schedule_recipients", AGENCY),
    ("report_schedules", AGENCY),
    ("agency_branding", AGENCY),
    ("agency_closures", AGENCY),
    ("attribution_credit_changes", CLIENTS),
    ("attribution_allocations", _via("run_id", "attribution_runs", CLIENTS)),
    ("attribution_runs", CLIENTS),
    ("attribution_conversions", CLIENTS),
    ("attribution_model_versions", CLIENTS),
    ("attribution_consumer_state", CLIENTS),
    ("revenue_identity_bindings", CLIENTS),
    ("ledger_reconciliation_actions", CLIENTS),
    ("ledger_transactions", CLIENTS),
    ("ledger_movements", CLIENTS),
    ("ledger_receipts", CLIENTS),
    ("ledger_projection_state", CLIENTS),
    ("identity_erasure_holds", CLIENTS),
    ("identity_changes", CLIENTS),
    ("identity_feed_state", CLIENTS),
    ("identity_handoffs", CLIENTS),
    ("identity_links", _via("collection_subject_id", "collection_subjects", CLIENTS)),
    ("identity_assertion_receipts", CLIENTS),
    ("identity_assertions", CLIENTS),
    ("identity_keys", CLIENTS),
    ("identity_merges", CLIENTS),
    ("identity_subjects", CLIENTS),
    ("identity_key_secrets", CLIENTS),
    ("whatsapp_messages", CLIENTS),
    ("whatsapp_numbers", AGENCY),
    ("crm_deals", CLIENTS),
    ("crm_stage_rules", CLIENTS),
    ("booking_events", _via("source_id", "integration_sources", AGENCY)),
    ("bookings", CLIENTS),
    ("integration_deliveries", _via("source_id", "integration_sources", AGENCY)),
    ("integration_source_secrets", _via("source_id", "integration_sources", AGENCY)),
    ("integration_sources", AGENCY),
    ("revenue_imports", CLIENTS),
    ("payment_callback_diagnostics", CLIENTS),
    ("payment_source_secrets", _via("source_id", "payment_sources", AGENCY)),
    ("payment_sources", AGENCY),
    ("revenue_evidence", CLIENTS),
    ("conversion_acknowledgements", _via("delivery_id", "conversion_deliveries", AGENCY)),
    ("conversion_deliveries", AGENCY),
    ("conversion_destinations", AGENCY),
    ("ad_spend_facts", _via("connection_id", "connector_connections", AGENCY)),
    ("ad_objects", _via("connection_id", "connector_connections", AGENCY)),
    ("ad_accounts", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_records", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_usage_records", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_checkpoints", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_sync_runs", AGENCY),
    ("connector_token_secrets", _via("connection_id", "connector_connections", AGENCY)),
    ("connector_oauth_transactions", CLIENTS),
    ("connector_connections", AGENCY),
    ("deletion_tombstones", CLIENTS),
    ("deletion_requests", CLIENTS),
    ("event_diagnostics", CLIENTS),
    ("collected_events", CLIENTS),
    ("managed_links", CLIENTS),
    ("link_domains", AGENCY),
    ("link_destination_origins", CLIENTS),
    ("link_utm_templates", CLIENTS),
    ("link_content_references", CLIENTS),
    ("link_campaigns", CLIENTS),
    ("consent_records", _via("subject_id", "collection_subjects", CLIENTS)),
    ("collection_subjects", CLIENTS),
    ("collection_forms", CLIENTS),
    ("ingestion_source_secrets", _via("source_id", "ingestion_sources", AGENCY)),
    ("ingestion_sources", AGENCY),
    ("audit_events", AGENCY),
    ("service_client_grants", AGENCY),
    ("invitation_client_grants", AGENCY),
    ("service_credentials", AGENCY),
    ("agency_invitations", AGENCY),
    ("client_grants", AGENCY),
    ("agency_memberships", AGENCY),
    ("client_workspaces", AGENCY),
)
# Tables that reference themselves: their rows are deleted leaves first.
SELF_REFERENCES = {"identity_merges": "reverses_id", "identity_subjects": "merged_into_id"}

# 017-C (D10): the agency's standing, checkouts, events and actions are deleted first; its
# subscriptions, payments and adjustments stay as financial records.
PURGE_0034 = (
    (ACTIONS, AGENCY),
    (EVENTS, AGENCY),
    (CHECKOUTS, AGENCY),
    (STANDINGS, AGENCY),
    *PURGE_0033,
)

RUNTIME_GRANTS = (
    f"GRANT SELECT, INSERT ON {', '.join(TABLES)} TO tracking_app",
    f"GRANT UPDATE (offered, retired_at) ON {PRICES} TO tracking_app",
    "GRANT UPDATE (standing, reason, trial_ends_at, trial_reminded_at, grant_ends_at, "
    "hold_started_at, hold_notified_at, provider_customer_id, version, updated_at) "
    f"ON {STANDINGS} TO tracking_app",
    "GRANT UPDATE (price_id, provider_price_id, status, current_period_starts_at, "
    "current_period_ends_at, next_billed_at, scheduled_action, scheduled_at, cancel_origin, "
    f"canceled_at, last_event_at, reconciled_at, updated_at) ON {SUBSCRIPTIONS} TO tracking_app",
    f"GRANT UPDATE (status, completed_at) ON {CHECKOUTS} TO tracking_app",
    # An unmatched event is bound to its agency when its subscription is (design section 5.2).
    f"GRANT UPDATE (agency_id, subscription_id, outcome, error_code) ON {EVENTS} TO tracking_app",
    "GRANT UPDATE (subscription_id, status, origin, currency, subtotal_cents, tax_cents, "
    f"total_cents, billed_at, invoice_number, last_event_at, updated_at) ON {PAYMENTS} "
    "TO tracking_app",
    "GRANT UPDATE (payment_id, status, currency, total_cents, last_event_at, updated_at) "
    f"ON {ADJUSTMENTS} TO tracking_app",
    "GRANT UPDATE (status, attempts, next_attempt_at, last_error, completed_at) "
    f"ON {ACTIONS} TO tracking_app",
)
LIFECYCLE_GRANTS = (
    f"GRANT SELECT (id, received_at) ON {EVENTS} TO tracking_lifecycle",
    f"GRANT DELETE ON {EVENTS} TO tracking_lifecycle",
    f"GRANT SELECT (id, status, expires_at) ON {CHECKOUTS} TO tracking_lifecycle",
    f"GRANT DELETE ON {CHECKOUTS} TO tracking_lifecycle",
    f"GRANT SELECT (id, agency_id, status) ON {SUBSCRIPTIONS} TO tracking_lifecycle",
    f"GRANT INSERT ON {ACTIONS} TO tracking_lifecycle",
)


def _check(table: str, name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _swap(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)


def _listed(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _extended(column: str, previous: str, new: Sequence[str]) -> str:
    extra = "".join(f", '{value}'" for value in new)
    return f"{column} IN ({previous}{extra})"


def _paddle_id(column: str, prefix: str, *, nullable: bool = False) -> str:
    rule = column + " ~ '^" + prefix + "_[a-z0-9]{26}$'"
    return f"{column} IS NULL OR {rule}" if nullable else rule


def _time(name: str, *, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if default else None,
        nullable=nullable,
    )


def _fk(table: str, column: str, parent: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{parent}.id"], name=op.f(f"fk_{table}_{column}_{parent}")
    )


def _prices() -> None:
    op.create_table(
        PRICES,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_price_id", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("billing_interval", sa.String(length=8), nullable=False),
        sa.Column("offered", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _time("registered_at", nullable=False, default=True),
        _time("retired_at"),
        _check(PRICES, "valid_provider", "provider IN ('paddle')"),
        _check(PRICES, "valid_price_id", _paddle_id("provider_price_id", "pri")),
        _check(PRICES, "valid_currency", "currency = 'USD'"),
        _check(PRICES, "valid_amount", f"amount_cents BETWEEN 1 AND {MAX_AMOUNT_CENTS}"),
        _check(PRICES, "valid_interval", "billing_interval IN ('month', 'year')"),
        _check(
            PRICES,
            "retirement",
            "offered = (retired_at IS NULL) "
            "AND (retired_at IS NULL OR retired_at >= registered_at)",
        ),
        _fk(PRICES, "plan_id", "saas_plans"),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PRICES}")),
        sa.UniqueConstraint("provider", "provider_price_id", name=f"uq_{PRICES}_provider_price"),
    )
    op.create_index(
        f"uq_{PRICES}_offered",
        PRICES,
        ["plan_id", "billing_interval"],
        unique=True,
        postgresql_where=sa.text("offered"),
    )
    op.create_index(f"ix_{PRICES}_plan_id", PRICES, ["plan_id"])


def _standings() -> None:
    reasons = " OR ".join(
        f"(standing = '{standing}' AND {_listed('reason', values)})"
        for standing, values in STANDING_REASONS
    )
    op.create_table(
        STANDINGS,
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("standing", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        _time("trial_ends_at"),
        _time("trial_reminded_at"),
        _time("grant_ends_at"),
        _time("hold_started_at"),
        _time("hold_notified_at"),
        sa.Column("provider_customer_id", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _time("created_at", nullable=False, default=True),
        _time("updated_at", nullable=False, default=True),
        _check(
            STANDINGS,
            "valid_standing",
            _listed("standing", [standing for standing, _ in STANDING_REASONS]),
        ),
        _check(STANDINGS, "reason_matches", reasons),
        _check(
            STANDINGS,
            "trial",
            "(standing <> 'trialing' OR trial_ends_at IS NOT NULL) "
            "AND (trial_reminded_at IS NULL OR trial_ends_at IS NOT NULL)",
        ),
        _check(
            STANDINGS,
            "hold",
            "(standing = 'hold') = (hold_started_at IS NOT NULL) "
            "AND (hold_notified_at IS NULL OR hold_started_at IS NOT NULL)",
        ),
        _check(
            STANDINGS,
            "grant",
            "grant_ends_at IS NULL OR (standing = 'complimentary' AND reason = 'operator_grant')",
        ),
        _check(
            STANDINGS,
            "valid_customer_id",
            _paddle_id("provider_customer_id", "ctm", nullable=True),
        ),
        _check(STANDINGS, "positive_version", "version >= 1"),
        _fk(STANDINGS, "agency_id", "agencies"),
        sa.PrimaryKeyConstraint("agency_id", name=op.f(f"pk_{STANDINGS}")),
    )
    op.create_index(
        f"ix_{STANDINGS}_trial",
        STANDINGS,
        ["trial_ends_at"],
        postgresql_where=sa.text("standing = 'trialing'"),
    )
    op.create_index(
        f"ix_{STANDINGS}_grant",
        STANDINGS,
        ["grant_ends_at"],
        postgresql_where=sa.text("grant_ends_at IS NOT NULL"),
    )
    op.create_index(
        f"ix_{STANDINGS}_hold",
        STANDINGS,
        ["hold_started_at"],
        postgresql_where=sa.text("standing = 'hold'"),
    )


def _subscriptions() -> None:
    op.create_table(
        SUBSCRIPTIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=32), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=32), nullable=True),
        sa.Column("price_id", sa.Uuid(), nullable=True),
        sa.Column("provider_price_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        _time("current_period_starts_at"),
        _time("current_period_ends_at"),
        _time("next_billed_at"),
        sa.Column("scheduled_action", sa.String(length=8), nullable=True),
        _time("scheduled_at"),
        sa.Column("cancel_origin", sa.String(length=16), nullable=True),
        _time("canceled_at"),
        sa.Column("duplicate", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _time("last_event_at", nullable=False),
        _time("reconciled_at"),
        _time("created_at", nullable=False, default=True),
        _time("updated_at", nullable=False, default=True),
        _check(SUBSCRIPTIONS, "valid_provider", "provider IN ('paddle')"),
        _check(
            SUBSCRIPTIONS,
            "valid_subscription_id",
            _paddle_id("provider_subscription_id", "sub"),
        ),
        _check(
            SUBSCRIPTIONS,
            "valid_transaction_id",
            _paddle_id("provider_transaction_id", "txn", nullable=True),
        ),
        _check(
            SUBSCRIPTIONS,
            "valid_price_id",
            _paddle_id("provider_price_id", "pri", nullable=True),
        ),
        _check(
            SUBSCRIPTIONS,
            "valid_status",
            "status IN ('trialing', 'active', 'past_due', 'paused', 'canceled')",
        ),
        _check(
            SUBSCRIPTIONS,
            "valid_scheduled_action",
            "scheduled_action IS NULL OR scheduled_action IN ('cancel', 'pause', 'resume')",
        ),
        _check(SUBSCRIPTIONS, "scheduled", "(scheduled_action IS NULL) = (scheduled_at IS NULL)"),
        _check(
            SUBSCRIPTIONS,
            "valid_cancel_origin",
            "cancel_origin IS NULL OR cancel_origin IN ('owner', 'closure', 'provider')",
        ),
        _check(
            SUBSCRIPTIONS,
            "period",
            "current_period_ends_at IS NULL OR current_period_starts_at IS NULL "
            "OR current_period_ends_at >= current_period_starts_at",
        ),
        _fk(SUBSCRIPTIONS, "agency_id", "agencies"),
        _fk(SUBSCRIPTIONS, "price_id", PRICES),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{SUBSCRIPTIONS}")),
        sa.UniqueConstraint(
            "provider",
            "provider_subscription_id",
            name=f"uq_{SUBSCRIPTIONS}_provider_subscription",
        ),
        sa.UniqueConstraint("agency_id", "id", name=f"uq_{SUBSCRIPTIONS}_scope"),
    )
    op.create_index(
        f"uq_{SUBSCRIPTIONS}_primary",
        SUBSCRIPTIONS,
        ["agency_id"],
        unique=True,
        postgresql_where=sa.text("NOT duplicate AND status <> 'canceled'"),
    )
    op.create_index(f"ix_{SUBSCRIPTIONS}_agency", SUBSCRIPTIONS, ["agency_id", "created_at"])
    op.create_index(
        f"ix_{SUBSCRIPTIONS}_reconcile",
        SUBSCRIPTIONS,
        ["reconciled_at"],
        postgresql_where=sa.text("status <> 'canceled'"),
    )


def _checkouts() -> None:
    op.create_table(
        CHECKOUTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("price_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_membership_id", sa.Uuid(), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        _time("created_at", nullable=False, default=True),
        _time("expires_at", nullable=False),
        _time("completed_at"),
        _check(CHECKOUTS, "valid_transaction_id", _paddle_id("provider_transaction_id", "txn")),
        _check(CHECKOUTS, "valid_status", "status IN ('open', 'completed', 'expired')"),
        _check(
            CHECKOUTS,
            "lifetime",
            "expires_at > created_at AND expires_at <= created_at + interval '24 hours'",
        ),
        _check(CHECKOUTS, "completion", "(status = 'completed') = (completed_at IS NOT NULL)"),
        _fk(CHECKOUTS, "agency_id", "agencies"),
        _fk(CHECKOUTS, "price_id", PRICES),
        sa.ForeignKeyConstraint(
            ["agency_id", "requested_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
            name=f"fk_{CHECKOUTS}_requested_by_agency_memberships",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{CHECKOUTS}")),
        sa.UniqueConstraint("provider_transaction_id", name=f"uq_{CHECKOUTS}_provider_transaction"),
    )
    op.create_index(
        f"uq_{CHECKOUTS}_open",
        CHECKOUTS,
        ["agency_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(f"ix_{CHECKOUTS}_agency", CHECKOUTS, ["agency_id", "created_at"])
    op.create_index(f"ix_{CHECKOUTS}_expires_at", CHECKOUTS, ["expires_at"])


def _events() -> None:
    errors = (
        "'unknown_price', 'unsupported_items', 'binding_conflict', 'invalid_payload', "
        "'agency_closed'"
    )
    op.create_table(
        EVENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_event_id", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        _time("occurred_at", nullable=False),
        _time("received_at", nullable=False, default=True),
        sa.Column("agency_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=32), nullable=True),
        sa.Column("provider_transaction_id", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column(
            "fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _check(EVENTS, "valid_provider", "provider IN ('paddle')"),
        _check(
            EVENTS,
            "valid_event_id",
            "(source = 'webhook' AND provider_event_id ~ '^evt_[a-z0-9]{26}$') "
            "OR (source = 'reconciliation' AND provider_event_id ~ '^rec_[0-9a-f]{32}$')",
        ),
        _check(EVENTS, "valid_event_type", "event_type ~ '^[a-z_]{1,24}[.][a-z_]{1,23}$'"),
        _check(
            EVENTS,
            "valid_outcome",
            "outcome IN ('applied', 'stale', 'ignored', 'unmatched')",
        ),
        _check(EVENTS, "valid_error", f"error_code IS NULL OR error_code IN ({errors})"),
        _check(
            EVENTS,
            "agency",
            "(outcome <> 'unmatched' OR agency_id IS NULL) "
            "AND (outcome NOT IN ('applied', 'stale') OR agency_id IS NOT NULL)",
        ),
        _check(
            EVENTS,
            "valid_subscription_id",
            _paddle_id("provider_subscription_id", "sub", nullable=True),
        ),
        _check(
            EVENTS,
            "valid_transaction_id",
            _paddle_id("provider_transaction_id", "txn", nullable=True),
        ),
        _check(EVENTS, "fields_object", "jsonb_typeof(fields) = 'object'"),
        _fk(EVENTS, "agency_id", "agencies"),
        sa.ForeignKeyConstraint(
            ["agency_id", "subscription_id"],
            [f"{SUBSCRIPTIONS}.agency_id", f"{SUBSCRIPTIONS}.id"],
            name=f"fk_{EVENTS}_{SUBSCRIPTIONS}",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{EVENTS}")),
        sa.UniqueConstraint("provider", "provider_event_id", name=f"uq_{EVENTS}_provider_event"),
    )
    op.create_index(f"ix_{EVENTS}_received_at", EVENTS, ["received_at"])
    op.create_index(f"ix_{EVENTS}_agency", EVENTS, ["agency_id", "occurred_at"])
    op.create_index(
        f"ix_{EVENTS}_unmatched",
        EVENTS,
        ["received_at"],
        postgresql_where=sa.text("outcome = 'unmatched'"),
    )


def _payments() -> None:
    origins = (
        "'api', 'subscription_charge', 'subscription_payment_method_change', "
        "'subscription_recurring', 'subscription_update', 'web'"
    )
    op.create_table(
        PAYMENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("provider_transaction_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("origin", sa.String(length=40), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal_cents", sa.BigInteger(), nullable=False),
        sa.Column("tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        _time("billed_at"),
        sa.Column("invoice_number", sa.String(length=64), nullable=True),
        _time("last_event_at", nullable=False),
        _time("created_at", nullable=False, default=True),
        _time("updated_at", nullable=False, default=True),
        _check(PAYMENTS, "valid_transaction_id", _paddle_id("provider_transaction_id", "txn")),
        _check(
            PAYMENTS,
            "valid_status",
            "status IN ('draft', 'ready', 'billed', 'paid', 'completed', 'canceled', 'past_due')",
        ),
        _check(PAYMENTS, "valid_origin", f"origin IS NULL OR origin IN ({origins})"),
        _check(PAYMENTS, "valid_currency", "currency ~ '^[A-Z]{3}$'"),
        _check(PAYMENTS, "amounts", "subtotal_cents >= 0 AND tax_cents >= 0 AND total_cents >= 0"),
        _check(
            PAYMENTS,
            "valid_invoice_number",
            "invoice_number IS NULL OR invoice_number ~ '^[A-Za-z0-9-]{1,64}$'",
        ),
        _fk(PAYMENTS, "agency_id", "agencies"),
        sa.ForeignKeyConstraint(
            ["agency_id", "subscription_id"],
            [f"{SUBSCRIPTIONS}.agency_id", f"{SUBSCRIPTIONS}.id"],
            name=f"fk_{PAYMENTS}_{SUBSCRIPTIONS}",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{PAYMENTS}")),
        sa.UniqueConstraint("provider_transaction_id", name=f"uq_{PAYMENTS}_provider_transaction"),
        sa.UniqueConstraint("agency_id", "id", name=f"uq_{PAYMENTS}_scope"),
    )
    op.create_index(f"ix_{PAYMENTS}_agency", PAYMENTS, ["agency_id", "created_at", "id"])


def _adjustments() -> None:
    actions = (
        "'credit', 'refund', 'chargeback', 'chargeback_reverse', 'chargeback_warning', "
        "'chargeback_warning_reverse', 'credit_reverse'"
    )
    op.create_table(
        ADJUSTMENTS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("provider_adjustment_id", sa.String(length=32), nullable=False),
        sa.Column("provider_transaction_id", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        _time("last_event_at", nullable=False),
        _time("created_at", nullable=False, default=True),
        _time("updated_at", nullable=False, default=True),
        _check(ADJUSTMENTS, "valid_adjustment_id", _paddle_id("provider_adjustment_id", "adj")),
        _check(ADJUSTMENTS, "valid_transaction_id", _paddle_id("provider_transaction_id", "txn")),
        _check(ADJUSTMENTS, "valid_action", f"action IN ({actions})"),
        _check(
            ADJUSTMENTS,
            "valid_status",
            "status IN ('pending_approval', 'approved', 'rejected', 'reversed')",
        ),
        _check(ADJUSTMENTS, "valid_currency", "currency ~ '^[A-Z]{3}$'"),
        _check(ADJUSTMENTS, "amount", "total_cents >= 0"),
        _fk(ADJUSTMENTS, "agency_id", "agencies"),
        sa.ForeignKeyConstraint(
            ["agency_id", "payment_id"],
            [f"{PAYMENTS}.agency_id", f"{PAYMENTS}.id"],
            name=f"fk_{ADJUSTMENTS}_{PAYMENTS}",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ADJUSTMENTS}")),
        sa.UniqueConstraint("provider_adjustment_id", name=f"uq_{ADJUSTMENTS}_provider_adjustment"),
    )
    op.create_index(f"ix_{ADJUSTMENTS}_payment", ADJUSTMENTS, ["agency_id", "payment_id"])
    op.create_index(f"ix_{ADJUSTMENTS}_transaction", ADJUSTMENTS, ["provider_transaction_id"])


def _actions() -> None:
    pairs = " OR ".join(
        f"(action = '{action}' AND reason = '{reason}')" for action, reason in ACTION_REASONS
    )
    op.create_table(
        ACTIONS,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agency_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _time("next_attempt_at", nullable=False, default=True),
        sa.Column("last_error", sa.String(length=32), nullable=True),
        _time("created_at", nullable=False, default=True),
        _time("completed_at"),
        _check(ACTIONS, "valid_action", pairs),
        _check(ACTIONS, "valid_status", "status IN ('pending', 'done', 'failed', 'skipped')"),
        _check(ACTIONS, "attempts", "attempts BETWEEN 0 AND 20"),
        _check(ACTIONS, "completion", "(status = 'pending') = (completed_at IS NULL)"),
        _fk(ACTIONS, "agency_id", "agencies"),
        sa.ForeignKeyConstraint(
            ["agency_id", "subscription_id"],
            [f"{SUBSCRIPTIONS}.agency_id", f"{SUBSCRIPTIONS}.id"],
            name=f"fk_{ACTIONS}_{SUBSCRIPTIONS}",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ACTIONS}")),
    )
    op.create_index(
        f"ix_{ACTIONS}_due",
        ACTIONS,
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        f"ix_{ACTIONS}_subscription",
        ACTIONS,
        ["subscription_id", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(f"ix_{ACTIONS}_agency", ACTIONS, ["agency_id", "created_at"])


def _counted(table: str, indent: str) -> str:
    lines = (
        "GET DIAGNOSTICS v_count = ROW_COUNT;",
        "IF v_count > 0 THEN",
        f"    v_deleted := v_deleted || jsonb_build_object('{table}', "
        f"v_count + coalesce((v_deleted ->> '{table}')::integer, 0));",
        "    v_left := v_left - v_count;",
        "END IF;",
    )
    return "".join(f"{indent}{line}\n" for line in lines)


def _step(table: str, path: str) -> str:
    column = SELF_REFERENCES.get(table)
    if column is None:
        return (
            f"        DELETE FROM public.{table} WHERE ctid = ANY (ARRAY(\n"
            f"            SELECT ctid FROM public.{table} WHERE {path} LIMIT v_left));\n"
            + _counted(table, " " * 8)
        )
    leaf = (
        f"NOT EXISTS (SELECT 1 FROM public.{table} r WHERE r.agency_id = t.agency_id "
        f"AND r.client_id = t.client_id AND r.{column} = t.id)"
    )
    return (
        "        LOOP\n"
        f"            DELETE FROM public.{table} WHERE ctid = ANY (ARRAY(\n"
        f"                SELECT t.ctid FROM public.{table} t WHERE t.{path} AND {leaf}\n"
        "                LIMIT v_left));\n"
        + _counted(table, " " * 12)
        + "            EXIT WHEN v_count = 0 OR v_left <= 0;\n"
        "        END LOOP;\n"
        "        IF v_left > 0 THEN\n"
        f"            DELETE FROM public.{table} WHERE {path};\n"
        + _counted(table, " " * 12)
        + "        END IF;\n"
    )


# The function of 0033 for `steps`; with billing=True a pending billing action of the agency
# also keeps a waiting agency (teardown_pending). With PURGE_0033 and billing=False the text is
# exactly the body of 0033, which the downgrade restores.
def _function(steps: Sequence[tuple[str, str]], *, billing: bool) -> str:
    body = []
    for table, path in steps:
        body.append(_step(table, path))
        body.append("        IF v_left <= 0 THEN EXIT steps; END IF;\n")
    raise_pending = "            RAISE EXCEPTION 'teardown_pending' USING ERRCODE = 'P0001';\n"
    pending = (
        "\n                  AND purge_due_at > now()) OR EXISTS (\n"
        f"                SELECT 1 FROM public.{ACTIONS}\n"
        "                WHERE agency_id = p_agency AND status = 'pending') THEN\n"
        if billing
        else "\n                  AND purge_due_at > now()) THEN\n"
    ) + raise_pending
    return f"""
CREATE OR REPLACE FUNCTION public.purge_agency_batch(p_agency uuid, p_budget integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_status text;
    v_purge public.{PURGES}%ROWTYPE;
    v_clients uuid[];
    v_left integer := p_budget;
    v_count integer;
    v_done boolean := false;
    v_deleted jsonb := '{{}}'::jsonb;
BEGIN
    IF p_budget IS NULL OR p_budget < 1 OR p_budget > {MAX_BUDGET} THEN
        RAISE EXCEPTION 'invalid_budget' USING ERRCODE = 'P0001';
    END IF;
    SELECT status INTO v_status FROM public.agencies WHERE id = p_agency FOR UPDATE;
    IF v_status IS DISTINCT FROM 'closed' THEN
        RAISE EXCEPTION 'agency_not_closed' USING ERRCODE = 'P0001';
    END IF;
    SELECT * INTO v_purge FROM public.{PURGES} WHERE agency_id = p_agency FOR UPDATE;
    IF NOT FOUND OR v_purge.offboarding_completed_at IS NULL OR EXISTS (
            SELECT 1 FROM public.connector_connections
            WHERE agency_id = p_agency AND status IN ('active', 'reconnect_required')) THEN
        RAISE EXCEPTION 'offboarding_not_completed' USING ERRCODE = 'P0001';
    END IF;
    IF v_purge.state = 'purged' THEN
        RETURN jsonb_build_object('state', 'purged', 'deleted', '{{}}'::jsonb);
    END IF;
    IF v_purge.state = 'waiting' THEN
        IF EXISTS (
                SELECT 1 FROM public.connector_connections
                WHERE agency_id = p_agency AND status = 'disconnecting'{pending}        END IF;
        UPDATE public.{PURGES} SET state = 'purging', teardown_settled_at = now(),
            purge_started_at = now() WHERE agency_id = p_agency;
    END IF;
    v_clients := ARRAY(SELECT id FROM public.client_workspaces WHERE agency_id = p_agency);
    <<steps>>
    BEGIN
{"".join(body)}        v_done := true;
    END steps;
    UPDATE public.{PURGES} SET deleted_counts = (
        SELECT coalesce(jsonb_object_agg(item.key, item.total), '{{}}'::jsonb)
        FROM (
            SELECT entry.key, sum(entry.value::bigint) AS total
            FROM (
                SELECT key, value FROM jsonb_each_text(deleted_counts)
                UNION ALL
                SELECT key, value FROM jsonb_each_text(v_deleted)
            ) AS entry
            GROUP BY entry.key
        ) AS item
    ) WHERE agency_id = p_agency;
    IF NOT v_done THEN
        RETURN jsonb_build_object('state', 'purging', 'deleted', v_deleted);
    END IF;
    UPDATE public.agencies SET name = 'Closed agency ' || p_agency::text, purged_at = now(),
        updated_at = now() WHERE id = p_agency;
    UPDATE public.{PURGES} SET state = 'purged', purge_completed_at = now()
        WHERE agency_id = p_agency;
    RETURN jsonb_build_object('state', 'purged', 'deleted', v_deleted);
END;
$$
"""


def _seed() -> None:
    op.execute(
        "INSERT INTO saas_plans (id, key, name, clients_limit, seats_limit, connections_limit, "
        "managed_links_limit, tracked_events_limit, is_default, reason) "
        f"VALUES (gen_random_uuid(), '{HOLD_PLAN}', 'Billing hold', 0, 0, 0, 0, 0, false, 'seed')"
    )
    op.execute(
        f"INSERT INTO {STANDINGS} (agency_id, standing, reason) "
        "SELECT id, 'complimentary', 'migration' FROM agencies WHERE purged_at IS NULL"
    )


def upgrade() -> None:
    _swap("agency_plan_assignments", "valid_assigned_by", ASSIGNED_BY)
    _swap("agency_plan_assignments", "valid_reason", ASSIGNMENT_REASONS)
    _swap("agency_plan_assignments", "reason_matches", REASON_MATCHES)
    _swap("audit_events", "valid_action", _extended("action", PREVIOUS_ACTIONS, NEW_ACTIONS))
    _swap(
        "audit_events",
        "valid_resource",
        _extended("resource_type", PREVIOUS_RESOURCES, NEW_RESOURCES),
    )
    _swap("audit_events", "scope", SCOPE)
    _swap("mail_outbox", "valid_purpose", _extended("purpose", PREVIOUS_PURPOSES, NEW_PURPOSES))
    _prices()
    _standings()
    _subscriptions()
    _checkouts()
    _events()
    _payments()
    _adjustments()
    _actions()
    _seed()
    op.execute(_function(PURGE_0034, billing=True))
    for statement in RUNTIME_GRANTS + LIFECYCLE_GRANTS:
        op.execute(statement)


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    for table in (*TABLES, "saas_plans", "agency_plan_assignments", "audit_events", "mail_outbox"):
        connection.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    actions = ", ".join(f"'{action}'" for action in NEW_ACTIONS)
    resources = ", ".join(f"'{resource}'" for resource in NEW_RESOURCES)
    purposes = ", ".join(f"'{purpose}'" for purpose in NEW_PURPOSES)
    stored = (
        *(f"EXISTS (SELECT 1 FROM {table})" for table in TABLES if table != STANDINGS),
        f"EXISTS (SELECT 1 FROM {STANDINGS} WHERE NOT (standing = 'complimentary' "
        "AND reason IN ('migration', 'billing_disabled')))",
        "EXISTS (SELECT 1 FROM agency_plan_assignments a JOIN saas_plans p ON p.id = a.plan_id "
        "WHERE a.assigned_by = 'billing' OR a.reason IN ('subscription', 'billing_hold') "
        f"OR p.key = '{HOLD_PLAN}')",
        f"EXISTS (SELECT 1 FROM audit_events WHERE action IN ({actions}) "
        f"OR resource_type IN ({resources}))",
        f"EXISTS (SELECT 1 FROM mail_outbox WHERE purpose IN ({purposes}))",
    )
    populated = connection.execute(sa.text("SELECT " + " OR ".join(stored))).scalar_one()
    if populated:
        raise RuntimeError("Refuse to remove stored billing state; use a forward fix.")
    for statement in LIFECYCLE_GRANTS:
        op.execute(statement.replace("GRANT", "REVOKE", 1).replace(" TO ", " FROM "))
    op.execute(_function(PURGE_0033, billing=False))
    for table in TABLES:
        op.drop_table(table)
    op.execute(f"DELETE FROM saas_plans WHERE key = '{HOLD_PLAN}' AND reason = 'seed'")
    _swap("mail_outbox", "valid_purpose", f"purpose IN ({PREVIOUS_PURPOSES})")
    _swap("audit_events", "scope", PREVIOUS_SCOPE)
    _swap("audit_events", "valid_resource", f"resource_type IN ({PREVIOUS_RESOURCES})")
    _swap("audit_events", "valid_action", f"action IN ({PREVIOUS_ACTIONS})")
    _swap("agency_plan_assignments", "reason_matches", PREVIOUS_REASON_MATCHES)
    _swap("agency_plan_assignments", "valid_reason", PREVIOUS_ASSIGNMENT_REASONS)
    _swap("agency_plan_assignments", "valid_assigned_by", PREVIOUS_ASSIGNED_BY)
