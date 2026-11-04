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
    assert len(SCHEMA) == 20  # 19 application tables at 0004_identity plus alembic_version


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
    # D-017/D-019/D-022 behavior from specification 002 and the D-024 retention periods for
    # ended credential state; security, audit, invitation, and account rules stay unapproved.
    assert approved == {
        ("client_grants", "row", "D-017"),
        ("mail_outbox", "encrypted_payload", "D-019; D-022; D-024"),
        ("mail_outbox", "row", "D-024"),
        ("auth_sessions", "row", "D-024"),
        ("auth_tokens", "row", "D-024"),
        ("verification_challenges", "row", "D-024"),
        ("oauth_transactions", "row", "D-024"),
        ("auth_rate_limits", "row", "D-024"),
    }
    assert all(
        rule.status is not RuleStatus.APPROVED
        for name in ("users", "security_events", "audit_events", "agency_invitations")
        for rule in TABLES[name].rules
    )


def test_direct_personal_classes_are_marked_high_or_medium():
    direct = {code for code, item in CLASSES.items() if item.personal == "direct"}
    assert direct == {
        "account.identity",
        "contact.invitee",
        "message.transactional",
        "tenancy.label",
    }
    assert all(CLASSES[code].sensitivity in {"high", "medium"} for code in direct)
