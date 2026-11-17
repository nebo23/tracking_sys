"""Provider webhook deliveries (specification 009-D, D-049 decisions D18 and D19).

A delivery reaches the runtime only after its adapter verified the signature over the raw body
(Spec 004 contract for the synthetic adapter). Its only effect is to queue one incremental sync
for each active connection of the named external account whose agency and client are active,
coalescing with a run that is already open. The payload is never stored: the sync reads the
data through the authorized API, under each connection's own tokens, fence, and limits. A
delivery is recorded by provider and SHA-256 digest of its event ID in the same transaction as
its effect, so a repeated delivery, even a concurrent one, has no further effect. Connections
that require reconnection, are disconnecting, or are disconnected receive nothing.
"""

import hashlib
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Engine, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.connectors.contracts import WebhookDelivery
from app.models import (
    Agency,
    ClientWorkspace,
    ConnectorConnection,
    ConnectorSyncRun,
    ConnectorWebhookDelivery,
)


def event_digest(event_id: str) -> str:
    return hashlib.sha256(event_id.encode()).hexdigest()


# Record the delivery and queue its syncs; returns "accepted" or "duplicate". The result does
# not depend on whether any connection matched.
def receive_delivery(
    engine: Engine, provider: str, delivery: WebhookDelivery, now: datetime
) -> str:
    with Session(engine) as session, session.begin():
        created = session.execute(
            insert(ConnectorWebhookDelivery)
            .values(
                id=uuid4(),
                provider=provider,
                event_digest=event_digest(delivery.event_id),
                received_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_connector_webhook_deliveries_event")
            .returning(ConnectorWebhookDelivery.id)
        ).first()
        if created is None:
            return "duplicate"
        # A shared lock orders this transaction with a concurrent disconnect: whichever commits
        # first, a disconnecting connection never keeps a run queued by the delivery.
        targets = list(
            session.scalars(
                select(ConnectorConnection)
                .join(Agency, Agency.id == ConnectorConnection.agency_id)
                .join(
                    ClientWorkspace,
                    (ClientWorkspace.agency_id == ConnectorConnection.agency_id)
                    & (ClientWorkspace.id == ConnectorConnection.client_id),
                )
                .where(
                    ConnectorConnection.provider == provider,
                    ConnectorConnection.external_account_id == delivery.external_account_id,
                    ConnectorConnection.status == "active",
                    Agency.status == "active",
                    ClientWorkspace.status == "active",
                )
                .order_by(ConnectorConnection.id)
                .with_for_update(of=ConnectorConnection, read=True)
            )
        )
        for connection in targets:
            session.execute(
                insert(ConnectorSyncRun)
                .values(
                    id=uuid4(),
                    agency_id=connection.agency_id,
                    client_id=connection.client_id,
                    connection_id=connection.id,
                    connection_generation=connection.generation,
                    status="queued",
                    kind="incremental",
                    created_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["connection_id"],
                    index_where=text("status IN ('queued', 'running')"),
                )
            )
        session.execute(
            update(ConnectorWebhookDelivery)
            .where(ConnectorWebhookDelivery.id == created.id)
            .values(notified=len(targets))
        )
    return "accepted"


__all__ = ["event_digest", "receive_delivery"]
