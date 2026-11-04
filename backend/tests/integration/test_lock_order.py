"""Deterministic lock-order checks between invitation acceptance and inviter mutations."""

import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    Agency,
    AgencyInvitation,
    AgencyMembership,
    AuditEvent,
    ClientGrant,
    InvitationClientGrant,
)
from app.security import digest, now_utc
from app.services.access import AccessService
from app.services.auth import AuthService
from app.services.tenancy import TenancyService

pytestmark = pytest.mark.integration

RAW_INVITATION = "synthetic-lock-order-invitation-token-0000000000"


def wait_state(engine, pid: int, worker: threading.Thread, timeout: float = 10.0) -> str:
    """Return "finished" or "waiting_on_lock" for the worker's backend, bounded by timeout."""
    deadline = time.monotonic() + timeout
    with engine.connect() as monitor:
        while time.monotonic() < deadline:
            if not worker.is_alive():
                return "finished"
            state = monitor.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            ).scalar()
            monitor.commit()
            if state == "Lock":
                return "waiting_on_lock"
            time.sleep(0.02)
    return "timeout"


def test_invitation_acceptance_does_not_deadlock_with_inviter_session_lock(
    world, database_settings
):
    """Inviter holds its user-row session lock, then mutates the agency the invitee is joining.

    Acceptance writes membership/grant audit rows attributed to the inviter. Their foreign keys
    need a key-share lock on the inviter's user row, which must stay compatible with the
    session-authentication user lock; otherwise the two transactions form a lock cycle.
    """
    with Session(world.db.migration) as setup, setup.begin():
        invitation = AgencyInvitation(
            agency_id=world.a,
            inviter_membership_id=world.owner_a,
            email_normalized="second_owner@example.test",
            role="analyst",
            token_digest=digest(RAW_INVITATION),
            expires_at=now_utc() + timedelta(hours=1),
        )
        setup.add(invitation)
        setup.flush()
        invitation_id = invitation.id
        setup.add(
            InvitationClientGrant(
                agency_id=world.a, invitation_id=invitation_id, client_id=world.a1
            )
        )

    engine = world.db.runtime
    inviter = Session(engine, expire_on_commit=False)
    inviter.begin()
    # Mirrors browser authentication of the inviter at the start of its request.
    AuthService(inviter, database_settings)._lock_user(world.users.owner_a)

    outcome: dict[str, object] = {}
    started = threading.Event()

    def accept() -> None:
        with Session(engine, expire_on_commit=False) as invitee, invitee.begin():
            outcome["pid"] = invitee.execute(text("SELECT pg_backend_pid()")).scalar_one()
            started.set()
            try:
                AuthService(invitee, database_settings)._lock_user(world.users.second_owner)
                AccessService(
                    invitee, world.users.second_owner, database_settings
                ).accept_invitation(RAW_INVITATION)
            except Exception as error:  # Recorded for the assertion below.
                outcome["error"] = type(getattr(error, "orig", error)).__name__
                raise
        outcome["accepted"] = True

    worker = threading.Thread(target=accept, daemon=True)
    try:
        worker.start()
        assert started.wait(10)
        state = wait_state(engine, int(outcome["pid"]), worker)
        inviter_error = None
        try:
            # The inviter's mutation requests the agency lock the invitee may still hold.
            TenancyService(inviter, world.users.owner_a).rename_agency(
                world.a, "Synthetic Agency A renamed"
            )
            inviter.commit()
        except Exception as error:
            inviter_error = type(getattr(error, "orig", error)).__name__
            inviter.rollback()
        worker.join(15)
    finally:
        inviter.close()

    assert state == "finished", (
        f"Acceptance blocked on the inviter's user lock ({state}); "
        f"inviter={inviter_error}, invitee={outcome.get('error')}"
    )
    assert inviter_error is None and outcome.get("accepted") is True

    with Session(world.db.migration) as check:
        member = check.scalar(
            select(AgencyMembership).where(
                AgencyMembership.agency_id == world.a,
                AgencyMembership.user_id == world.users.second_owner,
            )
        )
        assert member is not None and member.role == "analyst"
        assert check.get(ClientGrant, (world.a, world.a1, member.id)) is not None
        assert check.scalar(select(Agency.name).where(Agency.id == world.a)) == (
            "Synthetic Agency A renamed"
        )
        actors = {
            action: actor
            for action, actor in check.execute(
                select(AuditEvent.action, AuditEvent.actor_user_id).where(
                    AuditEvent.agency_id == world.a,
                    AuditEvent.action.in_(
                        ["membership.created", "grant.created", "invitation.accepted"]
                    ),
                    AuditEvent.resource_id.in_([member.id, invitation_id]),
                )
            )
        }
        assert actors == {
            "membership.created": world.users.owner_a,
            "grant.created": world.users.owner_a,
            "invitation.accepted": world.users.second_owner,
        }


def test_user_lock_still_serializes_same_user_operations(world, database_settings):
    """FOR NO KEY UPDATE remains self-conflicting, so per-user auth changes stay serialized."""
    engine = world.db.runtime
    first = Session(engine, expire_on_commit=False)
    first.begin()
    AuthService(first, database_settings)._lock_user(world.users.admin)
    outcome: dict[str, object] = {}
    started = threading.Event()

    def second_lock() -> None:
        with Session(engine, expire_on_commit=False) as second, second.begin():
            outcome["pid"] = second.execute(text("SELECT pg_backend_pid()")).scalar_one()
            started.set()
            AuthService(second, database_settings)._user_by_email("admin@example.test")
            outcome["locked_at"] = time.monotonic()

    worker = threading.Thread(target=second_lock, daemon=True)
    try:
        worker.start()
        assert started.wait(10)
        assert wait_state(engine, int(outcome["pid"]), worker) == "waiting_on_lock"
        released_at = time.monotonic()
        first.commit()
        worker.join(10)
    finally:
        first.close()
    assert not worker.is_alive()
    assert float(outcome["locked_at"]) >= released_at
