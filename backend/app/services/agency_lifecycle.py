"""Completion of agency closures whose grace period has ended (017-A, D-092 decision D8).

Run by the lifecycle runner as tracking_lifecycle, which may read an agency's ID and status and
a closure's ID, agency, closing time and outcome columns, and change only an agency's status
(and updated_at) and a closure's completion time; since 017-C (D-103 D10) it also queues the
immediate cancellation of the agency's subscriptions that have not ended, reading their ID,
agency and status only. One batch is one transaction: each due
closure locks its agency first, as a cancellation does, then the closure, and completes only
if the agency is still closing and the closure still open and due. A completed closure is never
selected again, so the step is idempotent, and the caller bounds the number of batches.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update

from app.models import Agency, AgencyClosure
from app.services.billing_actions import queue_closure_completion

# A batch waits at most this long for an agency lock held by an API transaction.
BATCH_LOCK_TIMEOUT = "100ms"


def _due(cutoff: datetime) -> tuple[Any, ...]:
    return (
        AgencyClosure.cancelled_at.is_(None),
        AgencyClosure.completed_at.is_(None),
        AgencyClosure.closes_at <= cutoff,
    )


# Complete at most `size` due closures in the caller's open transaction, which the caller
# commits; returns the number completed. A held lock raises OperationalError after the lock
# timeout, and the caller rolls the batch back and reports the step incomplete.
def complete_closures(connection: Any, cutoff: datetime, size: int) -> int:
    connection.execute(text(f"SET LOCAL lock_timeout = '{BATCH_LOCK_TIMEOUT}'"))
    candidates = connection.execute(
        select(AgencyClosure.id, AgencyClosure.agency_id)
        .where(*_due(cutoff))
        .order_by(AgencyClosure.closes_at, AgencyClosure.id)
        .limit(size)
    ).all()
    completed = 0
    for closure_id, agency_id in candidates:
        status = connection.execute(
            select(Agency.status).where(Agency.id == agency_id).with_for_update()
        ).scalar_one_or_none()
        if status != "closing":
            continue
        still_due = connection.execute(
            select(AgencyClosure.id)
            .where(AgencyClosure.id == closure_id, *_due(cutoff))
            .with_for_update()
        ).scalar_one_or_none()
        if still_due is None:
            continue
        connection.execute(
            update(AgencyClosure).where(AgencyClosure.id == closure_id).values(completed_at=cutoff)
        )
        connection.execute(
            update(Agency)
            .where(Agency.id == agency_id, Agency.status == "closing")
            .values(status="closed", updated_at=cutoff)
        )
        # 017-C (D-103 D10): every subscription that has not ended is canceled at once by the
        # billing worker; the purge waits until the action is settled.
        queue_closure_completion(connection, agency_id)
        completed += 1
    return completed
