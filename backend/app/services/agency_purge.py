"""The purge of closed agencies (specification 017-B, D-098 D7 and D9; design-017b.md section 5).

Run by the lifecycle runner as tracking_lifecycle, which may read a purge record's agency and
state and execute purge_agency_batch (migration 0033), and nothing else on a tenant table. The
function refuses an agency unless it is closed with a completed offboarding and settled
teardowns, deletes at most its budget of rows per call, children first, and on the call that
finds nothing left replaces the agency's name with a pseudonym and marks the purge done. Each
call is one transaction with the batch lock timeout. A refusal for a teardown in progress
leaves the agency waiting; a lock timeout or another database error rolls the batch back and
reports the step incomplete; the next run resumes from the first table. Counts only.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError

from app.models import AgencyPurge

# A batch waits at most this long for a row lock held by another transaction.
BATCH_LOCK_TIMEOUT = "100ms"
# The function's refusals (RAISE ... USING ERRCODE 'P0001').
REFUSALS = frozenset(
    {"invalid_budget", "agency_not_closed", "offboarding_not_completed", "teardown_pending"}
)
# Refusals that only mean "not yet": the agency waits for its teardowns.
WAITING = frozenset({"teardown_pending", "offboarding_not_completed"})


class PurgeRefused(Exception):
    """purge_agency_batch refused the agency with one of REFUSALS."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def refusal(error: DBAPIError) -> str | None:
    """The function's refusal code carried by a database error, if it is one."""
    original = getattr(error, "orig", None)
    if getattr(original, "sqlstate", None) != "P0001":
        return None
    diagnostic = getattr(original, "diag", None)
    message = getattr(diagnostic, "message_primary", None)
    return message if message in REFUSALS else None


# One call of the function in the caller's open transaction, which the caller commits or rolls
# back. Returns {"state": "purging" | "purged", "deleted": {table: rows}}.
def purge_batch(connection: Any, agency_id: UUID, budget: int) -> dict[str, Any]:
    connection.execute(text(f"SET LOCAL lock_timeout = '{BATCH_LOCK_TIMEOUT}'"))
    try:
        return connection.execute(
            text("SELECT purge_agency_batch(:agency, :budget)"),
            {"agency": agency_id, "budget": budget},
        ).scalar_one()
    except DBAPIError as error:
        code = refusal(error)
        if code is None:
            raise
        raise PurgeRefused(code) from None


# Call the function for one agency until it is purged, it refuses, or `max_batches` calls are
# spent. Returns (rows deleted, outcome), outcome one of purged, waiting, partial, failed.
def purge_agency(
    connection: Any,
    agency_id: UUID,
    budget: int,
    max_batches: int | None,
    on_batch: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[int, str]:
    rows = batches = 0
    while max_batches is None or batches < max_batches:
        try:
            result = purge_batch(connection, agency_id, budget)
            connection.commit()
        except PurgeRefused as refused:
            connection.rollback()
            return rows, "waiting" if refused.code in WAITING else "failed"
        except OperationalError:
            connection.rollback()
            return rows, "partial"
        except DBAPIError:
            # For example a late insert that broke a foreign key; the next run starts over.
            connection.rollback()
            return rows, "failed"
        batches += 1
        deleted = sum(int(value) for value in result["deleted"].values())
        rows += deleted
        if on_batch is not None:
            on_batch(result)
        if result["state"] == "purged":
            return rows, "purged"
        if deleted == 0:
            # A call that walks every step with budget to spare completes the purge, so an
            # unfinished call always deletes rows; stop rather than spin if it ever does not.
            return rows, "partial"
    return rows, "partial"


# The lifecycle step: every agency whose record is waiting or purging, in ID order, with at most
# `max_batches` calls each. Reports agency_rows_purged and agencies_purged.
def run_purges(
    connection: Any, size: int, max_batches: int | None, incomplete: list[str]
) -> dict[str, int]:
    agencies = list(
        connection.execute(
            select(AgencyPurge.agency_id)
            .where(AgencyPurge.state.in_(("waiting", "purging")))
            .order_by(AgencyPurge.agency_id)
        ).scalars()
    )
    connection.commit()
    counts = {"agency_rows_purged": 0, "agencies_purged": 0}
    for agency_id in agencies:
        rows, outcome = purge_agency(connection, agency_id, size, max_batches)
        counts["agency_rows_purged"] += rows
        if outcome == "purged":
            counts["agencies_purged"] += 1
        elif outcome in {"partial", "failed"} and "agency_purges" not in incomplete:
            incomplete.append("agency_purges")
    return counts
