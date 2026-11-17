"""Provider deauthorize and data deletion callbacks (specification 010-A, D-053 decision D5).

A provider such as Meta calls these routes with a signed_request that names one of its
accounts. The adapter verifies the signature before the payload is read. The only effect is to
start the disconnect of every live connection of that provider account, in every agency and
client, with reason "deauthorized" or "deletion_requested"; the worker then destroys the tokens
and purges the provider data as for any disconnect (Spec 003 case D3). A deletion request is
also recorded with a random confirmation code, the number of connections it stopped, and its
completion time, so the provider's user can follow its status. No account ID, tenant, or
payload is stored with the request, and the response never reveals whether any connection
matched. Archived clients and suspended agencies are included: deletion does not depend on
the customer's account state.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.contracts import SignedRequest
from app.models import ConnectorConnection, ConnectorDeletionRequest
from app.security import new_token
from app.services.connectors import LIVE, start_disconnect

Kind = Literal["deauthorize", "deletion"]


@dataclass(frozen=True)
class DeletionReceipt:
    confirmation_code: str
    url: str


def status_url(settings: Settings, provider: str, code: str) -> str:
    callback = urlsplit(settings.connector_redirect_uri)
    return f"{callback.scheme}://{callback.netloc}/connectors/{provider}/data-deletion/{code}"


# Apply a verified signed request. Returns the deletion receipt for a data deletion request,
# otherwise None.
def receive_signed_request(
    engine: Engine,
    settings: Settings,
    provider: str,
    kind: Kind,
    request: SignedRequest,
    now: datetime,
) -> DeletionReceipt | None:
    with Session(engine) as session, session.begin():
        record = None
        if kind == "deletion":
            record = ConnectorDeletionRequest(
                provider=provider, confirmation_code=new_token(), received_at=now
            )
            session.add(record)
            session.flush()
        targets = list(
            session.scalars(
                select(ConnectorConnection)
                .where(
                    ConnectorConnection.provider == provider,
                    ConnectorConnection.external_account_id == request.external_account_id,
                    ConnectorConnection.status.in_(LIVE),
                )
                .order_by(ConnectorConnection.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        reason = "deletion_requested" if record is not None else "deauthorized"
        for connection in targets:
            start_disconnect(session, settings, connection, reason, now)
            if record is not None:
                connection.deletion_request_id = record.id
        if record is None:
            return None
        record.connections = len(targets)
        if not targets:
            record.completed_at = now
        return DeletionReceipt(
            record.confirmation_code,
            status_url(settings, provider, record.confirmation_code),
        )


# The public status of a deletion request: "pending" until every connection it stopped has
# been destroyed and purged, then "completed". None when the code is unknown.
def deletion_status(engine: Engine, provider: str, code: str) -> dict[str, object] | None:
    with Session(engine) as session:
        record = session.scalar(
            select(ConnectorDeletionRequest).where(
                ConnectorDeletionRequest.provider == provider,
                ConnectorDeletionRequest.confirmation_code == code,
            )
        )
        if record is None:
            return None
        return {
            "confirmation_code": record.confirmation_code,
            "status": "completed" if record.completed_at is not None else "pending",
            "received_at": record.received_at,
            "completed_at": record.completed_at,
        }


__all__ = ["DeletionReceipt", "deletion_status", "receive_signed_request", "status_url"]
