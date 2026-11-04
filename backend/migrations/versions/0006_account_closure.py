"""Self-service account closure and erasure

Revision ID: 0006_account_closure
Revises: 0005_lifecycle
Created: 2026-11-04

Specification 003-A5 (D-024 decisions 3 and 4). Adds users.closed_at, a check that a closed
account is disabled, and the account_closed security action. tracking_app may update only the
identity columns that closure pseudonymizes; tracking_lifecycle may read users and delete the
password credential and external identity of closed accounts. Audit and security events stay
append-only for both roles. The downgrade refuses populated closure state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0006_account_closure"
down_revision: str | Sequence[str] | None = "0005_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREVIOUS_ACTIONS = (
    "action IN ('registered', 'email_verified', 'login_succeeded', 'login_failed', "
    "'logout', 'logout_all', 'password_changed', 'reset_requested', 'reset_completed', "
    "'google_login_succeeded', 'google_registered', 'google_identity_linked', "
    "'verification_code_failed')"
)
ACTIONS = PREVIOUS_ACTIONS[:-1] + ", 'account_closed')"
CLOSURE_COLUMNS = "email_normalized, display_name, status, closed_at"


def upgrade() -> None:
    op.add_column("users", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_users_closed_is_disabled"), "users", "closed_at IS NULL OR status = 'disabled'"
    )
    op.drop_constraint(op.f("ck_security_events_valid_action"), "security_events", type_="check")
    op.create_check_constraint(op.f("ck_security_events_valid_action"), "security_events", ACTIONS)
    op.execute(f"GRANT UPDATE ({CLOSURE_COLUMNS}) ON users TO tracking_app")
    op.execute("GRANT SELECT ON users TO tracking_lifecycle")
    op.execute(
        "GRANT SELECT, DELETE ON password_credentials, external_identities TO tracking_lifecycle"
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires an online empty-state check.")
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE users, security_events IN ACCESS EXCLUSIVE MODE"))
    if connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM users WHERE closed_at IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM security_events WHERE action = 'account_closed')"
        )
    ).scalar_one():
        raise RuntimeError("Refuse to remove populated account-closure state; use a forward fix.")
    op.execute(
        "REVOKE SELECT, DELETE ON password_credentials, external_identities FROM tracking_lifecycle"
    )
    op.execute("REVOKE SELECT ON users FROM tracking_lifecycle")
    op.execute(f"REVOKE UPDATE ({CLOSURE_COLUMNS}) ON users FROM tracking_app")
    op.drop_constraint(op.f("ck_security_events_valid_action"), "security_events", type_="check")
    op.create_check_constraint(
        op.f("ck_security_events_valid_action"), "security_events", PREVIOUS_ACTIONS
    )
    op.drop_constraint(op.f("ck_users_closed_is_disabled"), "users", type_="check")
    op.drop_column("users", "closed_at")
