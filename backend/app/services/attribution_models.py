"""Per-client attribution model versions (specification 008-B, D-079 decisions D2, D3 and D10).

Every client starts with First Click, Last Click and Linear at 30 days under the 008-A.1 rules,
all calculated for every conversion, with Linear as the default (Q-007). The defaults are
seeded lazily and idempotently the first time a client's models, status or runs are read or
the client is processed. A version is immutable: model, a window of 1 to 90 whole days and the
rule set. An Owner or Admin may add a version, change the default or retire a version, each
idempotent by operation ID and audited. A retired version stops receiving revisions and keeps
its history; the current default cannot be retired, and at most six versions are active.

Administration takes the agency row lock (TenancyService._manager with write=True) and then
locks the client's version rows, so concurrent changes are serialized. The attribution worker
reads versions without a lock.
"""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.attribution import RULES
from app.models import AttributionModelVersion
from app.services.attribution_records import DAY, model_set_digest, valid_window_days, version_key
from app.services.tenancy import AccessDenied, TenancyService

MODELS = ("first_click", "last_click", "linear")
DEFAULTS = (("first_click", 30, False), ("last_click", 30, False), ("linear", 30, True))
DEFAULT_WINDOW_DAYS = 30
ACTIVE_LIMIT = 6
RESOURCE = "attribution_model"


class AttributionError(Exception):
    """A public refusal of the attribution API with a closed code and HTTP status."""

    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


def ensure_defaults(session: Session, agency_id: UUID, client_id: UUID) -> None:
    """Seed the three default versions once, when the client has no version at all."""
    exists = session.scalar(
        select(AttributionModelVersion.id)
        .where(AttributionModelVersion.client_id == client_id)
        .limit(1)
    )
    if exists is not None:
        return
    for model, days, default in DEFAULTS:
        session.execute(
            insert(AttributionModelVersion)
            .values(
                id=uuid4(),
                agency_id=agency_id,
                client_id=client_id,
                version_key=version_key(model, days, 1),
                model=model,
                window_seconds=days * DAY,
                rules=RULES,
                is_default=default,
                status="active",
            )
            .on_conflict_do_nothing(index_elements=["client_id", "version_key"])
        )
    session.flush()


def versions(session: Session, client_id: UUID) -> list[AttributionModelVersion]:
    return list(
        session.scalars(
            select(AttributionModelVersion)
            .where(AttributionModelVersion.client_id == client_id)
            .order_by(AttributionModelVersion.created_at, AttributionModelVersion.version_key)
            .execution_options(populate_existing=True)
        )
    )


def active_versions(session: Session, client_id: UUID) -> list[AttributionModelVersion]:
    return [row for row in versions(session, client_id) if row.status == "active"]


def active_digest(rows: list[AttributionModelVersion]) -> str:
    return model_set_digest(
        (row.version_key, row.model, row.window_seconds, row.rules)
        for row in rows
        if row.status == "active"
    )


def view(row: AttributionModelVersion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "version_key": row.version_key,
        "model": row.model,
        "window_days": row.window_seconds // DAY,
        "rules": row.rules,
        "is_default": row.is_default,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "retired_at": row.retired_at.isoformat() if row.retired_at else None,
    }


def listing(session: Session, agency_id: UUID, client_id: UUID) -> dict[str, Any]:
    ensure_defaults(session, agency_id, client_id)
    rows = versions(session, client_id)
    default = next((row for row in rows if row.is_default), None)
    return {
        "versions": [view(row) for row in rows],
        "default_version_id": str(default.id) if default else None,
        "active_limit": ACTIVE_LIMIT,
    }


def resolve(
    session: Session, agency_id: UUID, client_id: UUID, version_id: UUID | None
) -> AttributionModelVersion:
    """The requested version of the client, or its default when none is named."""
    ensure_defaults(session, agency_id, client_id)
    rows = versions(session, client_id)
    if version_id is None:
        found = next((row for row in rows if row.is_default), None)
    else:
        found = next((row for row in rows if row.id == version_id), None)
    if found is None:
        raise AccessDenied()
    return found


class ModelAdmin(TenancyService):
    """Owner/Admin administration of a client's model versions; idempotent and audited."""

    def _begin(self, agency_id: UUID, client_id: UUID) -> tuple[Any, list[AttributionModelVersion]]:
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        ensure_defaults(self.session, agency_id, client_id)
        rows = list(
            self.session.scalars(
                select(AttributionModelVersion)
                .where(AttributionModelVersion.client_id == client_id)
                .order_by(AttributionModelVersion.created_at, AttributionModelVersion.version_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        return actor, rows

    @staticmethod
    def _fingerprint(*parts: object) -> str:
        return hashlib.sha256(json.dumps([str(part) for part in parts]).encode()).hexdigest()

    @staticmethod
    def _replay(
        rows: list[AttributionModelVersion], operation_id: UUID, fingerprint: str
    ) -> tuple[dict[str, Any], int] | None:
        for row in rows:
            for item in row.operations or []:
                if item.get("operation_id") == str(operation_id):
                    if item.get("fingerprint") != fingerprint:
                        raise AttributionError("operation_conflict", 409)
                    return view(row), 200
        return None

    @staticmethod
    def _record(row: AttributionModelVersion, operation_id: UUID, action: str, fingerprint: str):
        entry = {"operation_id": str(operation_id), "action": action, "fingerprint": fingerprint}
        row.operations = [*(row.operations or []), entry]

    def create(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        operation_id: UUID,
        model: str,
        window_days: int,
    ) -> tuple[dict[str, Any], int]:
        actor, rows = self._begin(agency_id, client_id)
        fingerprint = self._fingerprint("create", model, window_days, actor.id)
        replayed = self._replay(rows, operation_id, fingerprint)
        if replayed is not None:
            return replayed
        if model not in MODELS:
            raise AttributionError("validation_failed", 422)
        if not valid_window_days(window_days):
            raise AttributionError("invalid_window", 422)
        seconds = window_days * DAY
        active = [row for row in rows if row.status == "active"]
        if any(row.model == model and row.window_seconds == seconds for row in active):
            raise AttributionError("model_version_conflict", 409)
        if len(active) >= ACTIVE_LIMIT:
            raise AttributionError("model_version_limit", 409)
        earlier = sum(1 for row in rows if row.model == model and row.window_seconds == seconds)
        row = AttributionModelVersion(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            version_key=version_key(model, window_days, earlier + 1),
            model=model,
            window_seconds=seconds,
            rules=RULES,
            is_default=False,
            status="active",
            created_by_membership_id=actor.id,
            operations=[],
        )
        self._record(row, operation_id, "created", fingerprint)
        self.session.add(row)
        self._audit(agency_id, "attribution.model_created", RESOURCE, row.id, client_id)
        self.session.refresh(row)
        return view(row), 201

    def set_default(
        self, agency_id: UUID, client_id: UUID, version_id: UUID, *, operation_id: UUID
    ) -> tuple[dict[str, Any], int]:
        actor, rows = self._begin(agency_id, client_id)
        fingerprint = self._fingerprint("default", version_id, actor.id)
        replayed = self._replay(rows, operation_id, fingerprint)
        if replayed is not None:
            return replayed
        target = next((row for row in rows if row.id == version_id), None)
        if target is None:
            raise AccessDenied()
        if target.status != "active":
            raise AttributionError("model_version_conflict", 409)
        changed = not target.is_default
        for row in rows:
            if row.is_default and row.id != target.id:
                row.is_default = False
        self.session.flush()  # the previous default first: one default per client
        target.is_default = True
        self._record(target, operation_id, "default", fingerprint)
        if changed:
            self._audit(agency_id, "attribution.model_default_set", RESOURCE, target.id, client_id)
        self.session.flush()
        return view(target), 201

    def retire(
        self, agency_id: UUID, client_id: UUID, version_id: UUID, *, operation_id: UUID
    ) -> tuple[dict[str, Any], int]:
        actor, rows = self._begin(agency_id, client_id)
        fingerprint = self._fingerprint("retire", version_id, actor.id)
        replayed = self._replay(rows, operation_id, fingerprint)
        if replayed is not None:
            return replayed
        target = next((row for row in rows if row.id == version_id), None)
        if target is None:
            raise AccessDenied()
        if target.status != "active" or target.is_default:
            raise AttributionError("model_version_conflict", 409)
        # Read the clock first: a query between the two assignments would flush a retired row
        # without its time.
        now = self.session.scalar(select(func.clock_timestamp()))
        target.status, target.retired_at = "retired", now
        self._record(target, operation_id, "retired", fingerprint)
        self._audit(agency_id, "attribution.model_retired", RESOURCE, target.id, client_id)
        self.session.flush()
        return view(target), 201
