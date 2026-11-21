"""Model-level helpers of the conversion outbox (specification 014-B, D-064 decisions D9, D10, D13).

The connector runtime's teardown and the destination administration call these in their own
transactions. They depend only on the models, so the runtime can import them without a cycle.
Ending a delivery always destroys its sealed payload in the same statement.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.delivery import MATERIAL, ConversionDelivery, ConversionDestination

# Every payload column cleared and the lease released.
DESTROYED = {**dict.fromkeys(MATERIAL), "lease_expires_at": None}


# Cancel the deliveries that have not ended, of one destination or of one connection, with a
# closed reason, destroying their payloads. A delivery being sent keeps its attempt; its result
# write then finds it ended and changes nothing. Returns the number cancelled.
def cancel_open(
    session: Session,
    *,
    reason: str,
    now: datetime,
    destination_id: UUID | None = None,
    connection_id: UUID | None = None,
) -> int:
    query = update(ConversionDelivery).where(ConversionDelivery.ended_at.is_(None))
    if destination_id is not None:
        query = query.where(ConversionDelivery.destination_id == destination_id)
    if connection_id is not None:
        query = query.where(ConversionDelivery.connection_id == connection_id)
    result = session.execute(
        query.values(
            status="cancelled",
            reason=reason,
            rejection_class=None,
            ended_at=now,
            updated_at=now,
            **DESTROYED,
        )
    )
    return result.rowcount


# When a delivery connection's disconnect completes: cancel its open deliveries and disable its
# destination, which keeps its configuration until it is deleted (D13).
def end_connection(session: Session, connection_id: UUID, now: datetime) -> None:
    cancel_open(session, reason="connection_ended", now=now, connection_id=connection_id)
    session.execute(
        update(ConversionDestination)
        .where(ConversionDestination.connection_id == connection_id)
        .values(enabled=False, updated_at=now)
    )


__all__ = ["DESTROYED", "cancel_open", "end_connection"]
