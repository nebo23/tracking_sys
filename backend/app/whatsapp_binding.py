"""Platform operator binding of WhatsApp phone number IDs: python -m app.whatsapp_binding.

D-070 (review finding R004). An agency's registration of a phone number ID is only a claim and
routes nothing. Before verifying a claim, the platform operator confirms out of band, in Meta
Business Manager, that the number belongs to that client's WhatsApp Business Account and that
the account was onboarded to the platform's Meta app. This command is the separately authorized
step outside the agency roles; nothing here calls Meta.

Usage:
  python -m app.whatsapp_binding list [--status pending|active|disabled|revoked|all]
  python -m app.whatsapp_binding verify --claim <uuid> --confirm
  python -m app.whatsapp_binding revoke --claim <uuid> --confirm

A number has at most one verified binding: to move it to another client (transfer), revoke the
current binding, then verify the other client's pending claim. Output is JSON with claim,
agency and client identifiers, the phone number ID, the status and times; never a message.
"""

import argparse
import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.models import WhatsappNumber
from app.services.whatsapp import WhatsappError, list_claims, revoke_claim, verify_claim

STATUSES = ("pending", "active", "disabled", "revoked", "all")


def _view(item: WhatsappNumber) -> dict[str, str | None]:
    return {
        "claim": str(item.id),
        "agency_id": str(item.agency_id),
        "client_id": str(item.client_id),
        "phone_number_id": item.phone_number_id,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
        "verified_at": None if item.verified_at is None else item.verified_at.isoformat(),
    }


# Run one operator command against the engine and return (exit code, JSON-ready result).
def run(engine: Engine, command: str, *, claim: UUID | None = None, status: str = "pending"):
    try:
        with Session(engine) as session, session.begin():
            if command == "list":
                items = list_claims(session, None if status == "all" else status)
                return 0, [_view(item) for item in items]
            assert claim is not None
            action = verify_claim if command == "verify" else revoke_claim
            return 0, _view(action(session, claim))
    except WhatsappError as error:
        return 1, {"error": error.code}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.whatsapp_binding",
        description="Verify or revoke WhatsApp phone number claims (platform operator).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="List claims (pending by default).")
    listing.add_argument("--status", choices=STATUSES, default="pending")
    for name, text in (
        ("verify", "Verify a pending claim after the out-of-band ownership check."),
        ("revoke", "Revoke a claim or binding; it routes nothing afterwards."),
    ):
        action = commands.add_parser(name, help=text)
        action.add_argument("--claim", required=True, type=UUID)
        action.add_argument("--confirm", action="store_true", help="Required to act.")
    args = parser.parse_args(argv)
    if args.command != "list" and not args.confirm:
        parser.error("--confirm is required to change a claim.")
    configure_logging()
    engine = create_database_engine(Settings())
    try:
        code, result = run(
            engine,
            args.command,
            claim=getattr(args, "claim", None),
            status=getattr(args, "status", "pending"),
        )
    finally:
        engine.dispose()
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
