"""Data-class registry (specification 003-A1) against the mapped SQLAlchemy metadata."""

import pytest

import app.models  # noqa: F401  (registers every mapped table)
from app.data_policy import (
    CLASSES,
    TABLES,
    EndOfLifeRule,
    RuleStatus,
    TablePolicy,
    registry_problems,
)
from app.database import Base

# Alembic owns its version table, which is therefore absent from the mapped metadata.
SCHEMA = {
    table.name: [column.name for column in table.columns] for table in Base.metadata.sorted_tables
}
SCHEMA["alembic_version"] = ["version_num"]
USER_REFERENCES = [
    (table.name, column.name)
    for table in Base.metadata.sorted_tables
    for column in table.columns
    for key in column.foreign_keys
    if key.target_fullname == "users.id"
]


def test_every_mapped_column_is_classified_with_a_row_rule():
    assert registry_problems(SCHEMA, USER_REFERENCES) == []
    # 43 application tables at 0016_youtube_provider, three more at 0017_ad_spend (014-A),
    # three more at 0018_conversion_delivery (014-B), one more at 0020_revenue_evidence
    # (015-A), three more at 0021_payment_sources (015-B), one more at 0022_revenue_imports
    # (015-C), seven more at 0023_integration_bookings and 0024_crm_deals (015-D), two more
    # at 0025_whatsapp (015-E), eleven more at 0026_identity_journey (006, D-075), five more
    # at 0027_ledger_persistence (007-B), one more at 0028_revenue_identity (007-C), six more
    # at 0029_attribution_persistence (008-B), four more at 0031_saas_plans (017-A), plus
    # alembic_version.
    assert len(SCHEMA) == 91


def test_synthetic_unclassified_column_and_table_are_reported():
    schema = {**SCHEMA, "users": [*SCHEMA["users"], "synthetic_phone"], "synthetic_table": ["id"]}
    assert registry_problems(schema) == [
        "unclassified column: users.synthetic_phone",
        "unclassified table: synthetic_table",
    ]


def test_dropped_column_is_reported_as_stale():
    schema = {**SCHEMA, "users": [c for c in SCHEMA["users"] if c != "display_name"]}
    assert registry_problems(schema) == ["stale registry column: users.display_name"]


def test_user_reference_must_use_account_reference(monkeypatch):
    policy = TABLES["auth_sessions"]
    monkeypatch.setitem(
        TABLES,
        "auth_sessions",
        TablePolicy({**policy.columns, "user_id": "credential.lifecycle"}, policy.rules),
    )
    assert registry_problems(SCHEMA, USER_REFERENCES) == [
        "user reference not classed account.reference: auth_sessions.user_id"
    ]


@pytest.mark.parametrize(
    ("policy", "problem"),
    [
        (
            TablePolicy({"version_num": "synthetic.unknown"}, TABLES["alembic_version"].rules),
            "unknown class: alembic_version.version_num -> synthetic.unknown",
        ),
        (
            TablePolicy(TABLES["alembic_version"].columns, ()),
            "missing row rule: alembic_version",
        ),
        (
            TablePolicy(
                TABLES["alembic_version"].columns,
                (EndOfLifeRule("row", RuleStatus.APPROVED, "Q-012", "Synthetic candidate."),),
            ),
            "approved rule without a recorded decision: alembic_version",
        ),
        (
            TablePolicy(
                TABLES["alembic_version"].columns,
                (
                    *TABLES["alembic_version"].rules,
                    EndOfLifeRule("missing", RuleStatus.PENDING_DECISION, "Q-012", "Synthetic."),
                ),
            ),
            "rule target is not a column: alembic_version.missing",
        ),
    ],
)
def test_malformed_policies_are_reported(monkeypatch, policy, problem):
    monkeypatch.setitem(TABLES, "alembic_version", policy)
    assert registry_problems(SCHEMA, USER_REFERENCES) == [problem]


def test_only_recorded_decisions_are_presented_as_approved():
    approved = {
        (table, rule.target, rule.reference)
        for table, policy in TABLES.items()
        for rule in policy.rules
        if rule.status is RuleStatus.APPROVED
    }
    # D-017/D-019/D-022 behavior from specification 002, the D-024 retention periods for ended
    # credential state, D-024 account closure, the D-027 collection periods, and the D-048
    # connector purge; security,
    # audit, and invitation rules stay unapproved.
    assert approved == {
        ("client_grants", "row", "D-017"),
        ("mail_outbox", "encrypted_payload", "D-019; D-022; D-024"),
        ("mail_outbox", "row", "D-024"),
        ("auth_sessions", "row", "D-024"),
        ("auth_tokens", "row", "D-024"),
        ("verification_challenges", "row", "D-024"),
        ("oauth_transactions", "row", "D-024"),
        ("auth_rate_limits", "row", "D-024"),
        ("users", "row", "D-024"),
        ("password_credentials", "row", "D-024"),
        ("external_identities", "row", "D-024"),
        ("ingestion_source_secrets", "row", "D-027"),
        ("collection_subjects", "row", "D-027; D-075"),
        ("consent_records", "row", "D-027"),
        ("collected_events", "row", "D-027; D-033; D-075"),
        ("event_diagnostics", "row", "D-027"),
        ("deletion_requests", "row", "D-027"),
        ("deletion_tombstones", "row", "D-025; D-027"),
        # D-048 (009-A): the connector transaction period mirrors the D-024 OAuth rule, and the
        # disconnect purge clears account references, sealed material, and provider records.
        ("connector_oauth_transactions", "row", "D-048"),
        ("connector_connections", "external_account_id", "D-048"),
        ("connector_token_secrets", "ciphertext", "D-048"),
        # D-053 (010-A): records also leave on deauthorization, deletion and after 730 days.
        # D-058 (011-A): records of confirmed-deleted objects are purged, and attributes and
        # refreshed labels are cleared 30 days after their last refresh.
        ("connector_records", "row", "D-048; D-053; D-058"),
        ("connector_records", "attributes", "D-058"),
        ("connector_connections", "account_label", "D-058"),
        # D-049 (009-B): the disconnect purge also deletes sync checkpoints.
        ("connector_checkpoints", "row", "D-049"),
        # D-049 (009-D): webhook delivery records are deleted 7 days after receipt.
        ("connector_webhook_deliveries", "row", "D-049"),
        # D-064 (014-A, D13): spend rows leave with the disconnect, facts after 730 days.
        ("ad_accounts", "row", "D-064"),
        ("ad_objects", "row", "D-064"),
        ("ad_spend_facts", "row", "D-064"),
        # D-064 (014-B, D9, D13): payloads end with the delivery, rows 30 days later.
        ("conversion_deliveries", "row", "D-064"),
        ("conversion_deliveries", "ciphertext", "D-064"),
        ("conversion_acknowledgements", "row", "D-064"),
        # D-067 (015-B, D14): callback diagnostics after 30 days, replaced secrets once retired.
        ("payment_callback_diagnostics", "row", "D-067"),
        ("payment_source_secrets", "row", "D-067"),
        # D-067 (015-C, D14): import records 13 months after the commit.
        ("revenue_imports", "row", "D-067"),
        # D-068 (015-D, E9): deliveries, retired secrets, bookings, their events and deals.
        ("integration_deliveries", "row", "D-068"),
        ("integration_source_secrets", "row", "D-068"),
        ("bookings", "row", "D-068"),
        ("booking_events", "row", "D-068"),
        ("crm_deals", "row", "D-068"),
        ("whatsapp_messages", "row", "D-068"),
        # D-075 (006, J6): the development identity retention rules.
        ("identity_subjects", "row", "D-075"),
        ("identity_keys", "row", "D-075"),
        ("identity_assertions", "row", "D-075"),
        ("identity_assertion_receipts", "row", "D-075"),
        ("identity_links", "row", "D-075"),
        ("identity_handoffs", "row", "D-075"),
        ("identity_merges", "row", "D-075"),
        ("identity_changes", "row", "D-075"),
        ("identity_erasure_holds", "row", "D-075"),
        ("revenue_identity_bindings", "row", "D-075"),
        # D-079 (008-B, D9 and D12): the attribution history scrub and staging discard.
        ("attribution_conversions", "row", "D-079"),
        ("attribution_runs", "row", "D-079"),
        ("attribution_allocations", "row", "D-079"),
        ("attribution_credit_changes", "row", "D-079"),
        # D-092 (017-A): plans are never deleted; agreement records follow the closed account.
        ("saas_plans", "row", "D-092"),
        ("user_agreements", "row", "D-092; D-024"),
    }
    assert all(
        rule.status is not RuleStatus.APPROVED
        for name in ("security_events", "audit_events", "agency_invitations")
        for rule in TABLES[name].rules
    )


def test_direct_personal_classes_are_marked_high_or_medium():
    direct = {code for code, item in CLASSES.items() if item.personal == "direct"}
    assert direct == {
        "account.identity",
        "contact.invitee",
        "link.label",
        "message.transactional",
        "tenancy.label",
    }
    assert all(CLASSES[code].sensitivity in {"high", "medium"} for code in direct)
