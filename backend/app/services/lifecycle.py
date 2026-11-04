"""Bounded retention runs for ended credential state (specification 003-A3, D-024).

Each target deletes rows whose end (revocation, expiry, consumption, invalidation, or delivery)
plus the approved period lies strictly before one cutoff sampled from the database clock.
Predicates are re-evaluated on every run, so an interrupted, timed-out, or bounded run is
completed by the next run without a cursor and no eligible row is skipped permanently.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Engine, delete, func, or_, select, text
from sqlalchemy.exc import OperationalError

from app.config import LifecycleSettings
from app.models import (
    AuthRateLimit,
    AuthSession,
    AuthToken,
    MailOutbox,
    OAuthTransaction,
    VerificationChallenge,
)

# Session-level advisory lock in PostgreSQL's two-key space, which does not overlap the 64-bit
# keys of the registration and verification email locks: (specification 003, job).
LOCK_NAMESPACE = 3003
CREDENTIAL_STATE_JOB = 1
# A batch waits at most this long for a row lock held by an API transaction, then rolls back
# its own batch. Because this is far below PostgreSQL's default deadlock_timeout (1 second),
# a lock conflict aborts the lifecycle batch rather than an API request; the rows are retried
# on the next run.
BATCH_LOCK_TIMEOUT = "100ms"


@dataclass(frozen=True)
class Target:
    name: str
    model: Any
    key: Any
    eligible: Callable[[datetime], ColumnElement[bool]]


# The approved targets with their end-of-life predicates for a given cutoff.
def targets(settings: LifecycleSettings) -> tuple[Target, ...]:
    def before(days: int, cutoff: datetime) -> datetime:
        return cutoff - timedelta(days=days)

    def sessions(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.session_retention_days, cutoff)
        idle = timedelta(seconds=settings.session_idle_seconds)
        return or_(
            AuthSession.revoked_at < limit,
            AuthSession.expires_at < limit,
            AuthSession.last_seen_at < limit - idle,
        )

    def tokens(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.token_retention_days, cutoff)
        return or_(AuthToken.consumed_at < limit, AuthToken.expires_at < limit)

    def challenges(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.challenge_retention_days, cutoff)
        return or_(
            VerificationChallenge.consumed_at < limit,
            VerificationChallenge.invalidated_at < limit,
            VerificationChallenge.expires_at < limit,
        )

    def transactions(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.oauth_transaction_retention_days, cutoff)
        return or_(OAuthTransaction.consumed_at < limit, OAuthTransaction.expires_at < limit)

    def rate_limits(cutoff: datetime) -> ColumnElement[bool]:
        # An expired bucket already restarts at one attempt, so deleting it at expiry changes
        # no throttling decision.
        return AuthRateLimit.expires_at < cutoff

    def outbox(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.outbox_retention_days, cutoff)
        return or_(MailOutbox.delivered_at < limit, MailOutbox.expires_at < limit)

    return (
        Target("auth_sessions", AuthSession, AuthSession.id, sessions),
        Target("auth_tokens", AuthToken, AuthToken.id, tokens),
        Target(
            "verification_challenges", VerificationChallenge, VerificationChallenge.id, challenges
        ),
        Target("oauth_transactions", OAuthTransaction, OAuthTransaction.id, transactions),
        Target("auth_rate_limits", AuthRateLimit, AuthRateLimit.bucket_key, rate_limits),
        Target("mail_outbox", MailOutbox, MailOutbox.id, outbox),
    )


# Delete one ordered batch of eligible rows. The outer predicate repeats the eligibility test,
# so PostgreSQL re-checks a row changed by a concurrent transaction (for example a rate-limit
# bucket restarted after the key subquery ran) and leaves it in place.
def _delete_batch(connection: Any, target: Target, cutoff: datetime, size: int) -> int:
    condition = target.eligible(cutoff)
    keys = select(target.key).where(condition).order_by(target.key).limit(size)
    connection.execute(text(f"SET LOCAL lock_timeout = '{BATCH_LOCK_TIMEOUT}'"))
    return connection.execute(delete(target.model).where(target.key.in_(keys), condition)).rowcount


# Delete development .eml captures (and interrupted .pending files) older than the approved
# period, only in development local mode. Only regular files directly in the mail directory
# are considered; symbolic links and other files are left alone. Returns deleted and failed
# counts.
def clean_local_mail(settings: LifecycleSettings, cutoff: datetime) -> dict[str, int]:
    counts = {"deleted": 0, "failed": 0}
    directory = settings.mail_directory
    if settings.environment != "development" or settings.mail_mode != "local":
        return counts
    if not directory.is_dir():
        return counts
    limit = cutoff.timestamp() - settings.local_mail_retention_days * 86400
    for path in directory.iterdir():
        if path.suffix not in {".eml", ".pending"} or path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
                counts["deleted"] += 1
        except OSError:
            counts["failed"] += 1
    return counts


# Run every target once under the job's advisory lock. A concurrent run returns
# skipped_concurrent_run without deleting anything. Each batch commits separately. A batch that
# times out on a lock marks its target incomplete and the run continues with the next target;
# max_batches bounds the work per target (None means until no eligible row remains). Returns
# counts and status codes only.
def run_lifecycle(
    engine: Engine,
    settings: LifecycleSettings,
    *,
    cutoff: datetime | None = None,
    max_batches: int | None = None,
) -> dict[str, Any]:
    size = settings.lifecycle_batch_size
    deleted: dict[str, int] = {}
    incomplete: list[str] = []
    with engine.connect() as connection:
        acquired = connection.execute(
            select(func.pg_try_advisory_lock(LOCK_NAMESPACE, CREDENTIAL_STATE_JOB))
        ).scalar_one()
        connection.commit()
        if not acquired:
            return {"status": "skipped_concurrent_run", "deleted": {}, "incomplete": []}
        try:
            if cutoff is None:
                cutoff = connection.execute(select(func.now())).scalar_one()
                connection.commit()
            for target in targets(settings):
                deleted[target.name] = 0
                batches = 0
                while max_batches is None or batches < max_batches:
                    try:
                        count = _delete_batch(connection, target, cutoff, size)
                        connection.commit()
                    except OperationalError:
                        connection.rollback()
                        incomplete.append(target.name)
                        break
                    batches += 1
                    deleted[target.name] += count
                    if count < size:
                        break
                else:
                    incomplete.append(target.name)
        finally:
            connection.execute(
                select(func.pg_advisory_unlock(LOCK_NAMESPACE, CREDENTIAL_STATE_JOB))
            )
            connection.commit()
    files = clean_local_mail(settings, cutoff)
    if files["failed"]:
        incomplete.append("local_mail_files")
    return {
        "status": "partial" if incomplete else "completed",
        "deleted": {**deleted, "local_mail_files": files["deleted"]},
        "incomplete": incomplete,
    }
