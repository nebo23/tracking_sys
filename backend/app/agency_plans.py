"""Platform operator administration of plans and agencies: python -m app.agency_plans.

Specification 017-A (D-092, decision D7; specs/017-saas-lifecycle/design-017a.md section 8).
The platform operator defines plans, chooses the default plan of new agencies, assigns plans,
lists agencies with their use, and suspends or reactivates an agency. There is no web
interface: the command runs outside the agency roles, as tracking_app with the application
settings. Every change needs --confirm and writes an audit event whose actor is the platform
operator; an agency change takes that agency's row lock, a plan change the plan lock.

Usage:
  python -m app.agency_plans plans
  python -m app.agency_plans create-plan --key K --name N --clients V --seats V
      --connections V --managed-links V --tracked-events V --reason R --confirm
  python -m app.agency_plans set-default --plan K --confirm
  python -m app.agency_plans assign --agency <uuid> --plan K --reason R --confirm
  python -m app.agency_plans agencies [--over-allowance] [--after <uuid>] [--limit N]
  python -m app.agency_plans suspend --agency <uuid> --confirm
  python -m app.agency_plans reactivate --agency <uuid> --confirm

A limit value is a non-negative integer or "unlimited". Output is one JSON document with
identifiers, plan keys, numbers, closed codes and times only: never an agency or client name,
a person, an email, a token or a secret. A refusal prints {"error": code} and exits with 1.
"""

import argparse
import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.logging_config import configure_logging
from app.models import Agency, AuditEvent, SaasPlan
from app.services import plans

# Transaction advisory lock for plan changes, in the two-key space: (namespace, key).
PLAN_LOCK_NAMESPACE = 1717
PLAN_LOCK_KEY = 1
MAX_LIMIT_VALUE = 1_000_000_000
PLAN_KEY = re.compile(r"[a-z][a-z0-9_-]{1,31}")
PLAN_REASONS = ("new_offer", "replacement", "individual")
ASSIGNMENT_REASONS = ("plan_change", "correction")
LIMIT_OPTIONS = (
    ("clients", "clients_limit"),
    ("seats", "seats_limit"),
    ("connections", "connections_limit"),
    ("managed-links", "managed_links_limit"),
    ("tracked-events", "tracked_events_limit"),
)
CHANGES = frozenset({"create-plan", "set-default", "assign", "suspend", "reactivate"})


class Refused(Exception):
    """A refusal with a closed code, printed as {"error": code} and any detail."""

    def __init__(self, code: str, **detail: Any) -> None:
        self.code, self.detail = code, detail
        super().__init__(code)


def _limit(value: str) -> int | None:
    if value == "unlimited":
        return None
    if not value.isascii() or not value.isdigit() or int(value) > MAX_LIMIT_VALUE:
        raise argparse.ArgumentTypeError("use a non-negative integer or 'unlimited'")
    return int(value)


def _key(value: str) -> str:
    if not PLAN_KEY.fullmatch(value):
        raise argparse.ArgumentTypeError("use 2-32 lowercase letters, digits, - or _")
    return value


def _page(value: str) -> int:
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 500:
        raise argparse.ArgumentTypeError("use 1-500")
    return int(value)


def _name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100 or not value.isprintable():
        raise argparse.ArgumentTypeError("use 1-100 printable characters")
    return value


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _plan_view(plan: SaasPlan, agencies: int | None = None) -> dict[str, Any]:
    view: dict[str, Any] = {
        "key": plan.key,
        "name": plan.name,
        "limits": {
            option.replace("-", "_"): getattr(plan, column) for option, column in LIMIT_OPTIONS
        },
        "is_default": plan.is_default,
        "reason": plan.reason,
        "created_at": _time(plan.created_at),
    }
    if agencies is not None:
        view["agencies"] = agencies
    return view


def _audit(
    session: Session,
    action: str,
    resource_type: str,
    resource_id: UUID,
    agency_id: UUID | None = None,
) -> None:
    session.flush()
    session.add(
        AuditEvent(
            id=uuid4(),
            agency_id=agency_id,
            actor_kind="platform_operator",
            actor_user_id=None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )
    session.flush()


def _plan_lock(session: Session) -> None:
    session.execute(select(func.pg_advisory_xact_lock(PLAN_LOCK_NAMESPACE, PLAN_LOCK_KEY)))


def _plan(session: Session, key: str) -> SaasPlan:
    plan = session.scalar(
        select(SaasPlan).where(SaasPlan.key == key).execution_options(populate_existing=True)
    )
    if plan is None:
        raise Refused("plan_not_found")
    return plan


def _locked_agency(session: Session, agency_id: UUID) -> Agency:
    agency = session.scalar(
        select(Agency)
        .where(Agency.id == agency_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if agency is None:
        raise Refused("agency_not_found")
    return agency


def list_plans(session: Session) -> list[dict[str, Any]]:
    counts = plans.agencies_per_plan(session)
    rows = session.scalars(select(SaasPlan).order_by(SaasPlan.created_at, SaasPlan.key))
    return [_plan_view(plan, counts.get(plan.id, 0)) for plan in rows]


def create_plan(
    session: Session, *, key: str, name: str, reason: str, limits: dict[str, int | None]
) -> dict[str, Any]:
    _plan_lock(session)
    if session.scalar(select(SaasPlan.id).where(SaasPlan.key == key)) is not None:
        raise Refused("plan_exists")
    plan = SaasPlan(id=uuid4(), key=key, name=name, reason=reason, is_default=False, **limits)
    session.add(plan)
    session.flush()
    _audit(session, "plan.created", "plan", plan.id)
    session.refresh(plan)
    return _plan_view(plan)


def set_default(session: Session, *, key: str) -> dict[str, Any]:
    _plan_lock(session)
    plan = _plan(session, key)
    # 017-C (D-103 D5): the billing hold plan is assigned by billing only, never by default.
    if plan.key == plans.HOLD_PLAN:
        raise Refused("reserved_plan")
    if plan.is_default:
        raise Refused("already_default")
    session.execute(update(SaasPlan).where(SaasPlan.is_default.is_(True)).values(is_default=False))
    session.execute(update(SaasPlan).where(SaasPlan.id == plan.id).values(is_default=True))
    _audit(session, "plan.default_set", "plan", plan.id)
    session.refresh(plan)
    return _plan_view(plan)


def assign(session: Session, *, agency_id: UUID, key: str, reason: str) -> dict[str, Any]:
    agency = _locked_agency(session, agency_id)
    plan = _plan(session, key)
    if plan.key == plans.HOLD_PLAN:
        raise Refused("reserved_plan")
    if agency.status == "closed":
        raise Refused("agency_closed")
    if plans.current_plan(session, agency_id).plan.id == plan.id:
        raise Refused("already_assigned")
    row = plans.add_assignment(
        session, agency_id, plan, assigned_by="platform_operator", reason=reason
    )
    _audit(session, "agency.plan_assigned", "plan_assignment", row.id, agency_id)
    session.refresh(row)
    return {
        "agency_id": str(agency_id),
        "plan": plan.key,
        "revision": row.revision,
        "reason": row.reason,
        "assigned_at": _time(row.assigned_at),
    }


def change_status(session: Session, *, agency_id: UUID, command: str) -> dict[str, Any]:
    agency = _locked_agency(session, agency_id)
    if command == "suspend":
        if agency.status != "active":
            raise Refused("not_active", status=agency.status)
        agency.status, action = "suspended", "agency.suspended"
    else:
        if agency.status != "suspended":
            raise Refused("not_suspended", status=agency.status)
        agency.status, action = "active", "agency.reactivated"
    _audit(session, action, "agency", agency.id, agency.id)
    return {"agency_id": str(agency.id), "status": agency.status}


def _usage_view(session: Session, agency: Agency, now: datetime) -> dict[str, Any]:
    usage = plans.agency_usage(session, agency.id, now)
    events = usage.tracked_events
    return {
        "agency_id": str(agency.id),
        "status": agency.status,
        "plan": usage.current.plan.key,
        "assigned_at": _time(usage.current.assignment.assigned_at),
        "use": {item.limit: item.used for item in usage.limits},
        "tracked_events": {
            "count": events.count,
            "count_capped": events.count_capped,
            "allowance": events.allowance,
            "state": events.state,
        },
    }


def list_agencies(
    session: Session,
    *,
    after: UUID | None = None,
    limit: int = 100,
    over_allowance: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or session.scalar(select(func.now()))
    assert moment is not None
    query = select(Agency).order_by(Agency.id).limit(limit)
    if after is not None:
        query = query.where(Agency.id > after)
    examined = list(session.scalars(query))
    views = [_usage_view(session, agency, moment) for agency in examined]
    if over_allowance:
        views = [view for view in views if view["tracked_events"]["state"] == "over_allowance"]
    following = str(examined[-1].id) if len(examined) == limit else None
    return {"agencies": views, "next_after": following}


# Run one subcommand in its own transaction and return (exit code, JSON-ready result). Listings
# read one REPEATABLE READ snapshot; changes run under READ COMMITTED with their locks.
def run(engine: Engine, command: str, **options: Any) -> tuple[int, Any]:
    try:
        if command in {"plans", "agencies"}:
            with engine.connect() as raw:
                connection = raw.execution_options(
                    isolation_level="REPEATABLE READ", postgresql_readonly=True
                )
                with Session(bind=connection) as session, session.begin():
                    if command == "plans":
                        return 0, list_plans(session)
                    return 0, list_agencies(
                        session,
                        after=options.get("after"),
                        limit=options.get("limit", 100),
                        over_allowance=options.get("over_allowance", False),
                        now=options.get("now"),
                    )
        with Session(engine, expire_on_commit=False) as session, session.begin():
            if command == "create-plan":
                return 0, create_plan(
                    session,
                    key=options["key"],
                    name=options["name"],
                    reason=options["reason"],
                    limits=options["limits"],
                )
            if command == "set-default":
                return 0, set_default(session, key=options["plan"])
            if command == "assign":
                return 0, assign(
                    session,
                    agency_id=options["agency"],
                    key=options["plan"],
                    reason=options["reason"],
                )
            if command in {"suspend", "reactivate"}:
                return 0, change_status(session, agency_id=options["agency"], command=command)
        raise ValueError("Unknown command.")
    except Refused as refusal:
        return 1, {"error": refusal.code, **refusal.detail}
    except plans.PlanUnavailable:
        return 1, {"error": plans.PlanUnavailable.code}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="python -m app.agency_plans",
        description="Administer plans and agencies (platform operator).",
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("plans", help="List every plan and how many agencies have it.")
    create = commands.add_parser("create-plan", help="Create a plan (not the default).")
    create.add_argument("--key", required=True, type=_key)
    create.add_argument("--name", required=True, type=_name)
    for option, _ in LIMIT_OPTIONS:
        create.add_argument(f"--{option}", required=True, type=_limit, metavar="N|unlimited")
    create.add_argument("--reason", required=True, choices=PLAN_REASONS)
    default = commands.add_parser("set-default", help="Make a plan the default of new agencies.")
    default.add_argument("--plan", required=True, type=_key)
    move = commands.add_parser("assign", help="Assign a plan to an agency.")
    move.add_argument("--agency", required=True, type=UUID)
    move.add_argument("--plan", required=True, type=_key)
    move.add_argument("--reason", required=True, choices=ASSIGNMENT_REASONS)
    listing = commands.add_parser("agencies", help="List agencies with their plan and use.")
    listing.add_argument("--over-allowance", action="store_true")
    listing.add_argument("--after", type=UUID)
    listing.add_argument("--limit", type=_page, default=100, metavar="1-500")
    for name, text in (
        ("suspend", "Suspend an active agency."),
        ("reactivate", "Reactivate a suspended agency."),
    ):
        action = commands.add_parser(name, help=text)
        action.add_argument("--agency", required=True, type=UUID)
    for name in CHANGES:
        commands.choices[name].add_argument("--confirm", action="store_true", help="Required.")
    return root


def options_of(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "create-plan":
        limits = {
            column: getattr(args, option.replace("-", "_")) for option, column in LIMIT_OPTIONS
        }
        return {"key": args.key, "name": args.name, "reason": args.reason, "limits": limits}
    if args.command == "agencies":
        return {"after": args.after, "limit": args.limit, "over_allowance": args.over_allowance}
    return {
        name: getattr(args, name) for name in ("agency", "plan", "reason") if hasattr(args, name)
    }


def main(argv: Sequence[str] | None = None) -> int:
    root = parser()
    args = root.parse_args(argv)
    if args.command in CHANGES and not args.confirm:
        root.error(f"--confirm is required to {args.command.replace('-', ' ')}.")
    configure_logging()
    engine = create_database_engine(Settings())
    try:
        code, result = run(engine, args.command, **options_of(args))
    finally:
        engine.dispose()
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
