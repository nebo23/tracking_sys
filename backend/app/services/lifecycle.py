"""Bounded retention runs for ended credential state (specification 003-A3/003-A5, D-024).

Each target deletes rows whose end (revocation, expiry, consumption, invalidation, or delivery)
plus the approved period lies strictly before one cutoff sampled from the database clock. Rows
belonging to a closed account (users.closed_at set) are deleted on the next run without a
period: its password credential, external identity, sessions, tokens, challenges, and OAuth
transactions. Specification 004 (D-027 decision 7) adds collected data: event rows past their
expiry (395 days after first receipt), diagnostic counters 30 days after their day, rotated-out
webhook secrets after their 24-hour overlap, and subjects with their consent records 395 days
after last activity once no event references them. Event, consent-record, and subject
expiry depends on a client's privacy state, so those targets run one client at a time inside a
transaction that first takes that client's privacy lock (D-027 decision 10) and then
re-evaluates eligibility: an admission, consent change, or erasure in flight either finishes
first and is observed, or waits for the batch (review finding R004-02). Because each batch
commits and releases that lock, consent history is removed so that every committed state keeps
each purpose's effective record: the latest record of a subject and purpose is deleted only
once no older record of it remains, so no batch can expose an older grant (review finding
R004-04). Specification 009-A (D-048) adds connector OAuth transactions, deleted one day
after consumption or expiry like sign-in transactions.
Specification 011-A (D-058 decision D11) clears connector record attributes and account labels
that were not refreshed for 30 days, keeping the statistics, and lets a provider keep its
connector records for a shorter period than the global one. Specification 014 (D-064 decision
D13) deletes advertising spend facts 730 days after their spend date, and ended conversion
deliveries with their acknowledgements 30 days after they end. A 015 booking can stay linked to a
subject after the subject's own retention has run out; in the batch that deletes such a subject,
booking_links first clears the booking's subject_id and linked_at together, and the subject is
deleted only once no booking references it (review finding R002, D-070). The booking itself is
kept until its own retention.
Predicates are re-evaluated on every run, so an interrupted, timed-out, or bounded run is
completed by the next run without a cursor and no eligible row is skipped permanently.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Engine,
    and_,
    delete,
    exists,
    func,
    or_,
    select,
    text,
    tuple_,
    union,
    update,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import aliased

from app.config import LifecycleSettings
from app.models import (
    AdSpendFact,
    AuthRateLimit,
    AuthSession,
    AuthToken,
    Booking,
    CollectedEvent,
    CollectionSubject,
    ConnectorConnection,
    ConnectorOAuthTransaction,
    ConnectorRecord,
    ConnectorWebhookDelivery,
    ConversionAcknowledgement,
    ConversionDelivery,
    CrmDeal,
    EventDiagnostic,
    ExternalIdentity,
    IngestionSourceSecret,
    IntegrationDelivery,
    IntegrationSourceSecret,
    MailOutbox,
    OAuthTransaction,
    PasswordCredential,
    PaymentCallbackDiagnostic,
    PaymentSourceSecret,
    RevenueImport,
    StoredConsentRecord,
    User,
    VerificationChallenge,
    WhatsappMessage,
)
from app.services.collection import LOCK_NAMESPACE as CLIENT_LOCK_NAMESPACE
from app.services.collection import client_lock_key

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
    # Collected data whose eligibility depends on a client's privacy state; deleted per client
    # under that client's privacy lock (delete_client_batch). The model has a client_id column.
    client_scoped: bool = False
    # 011-A (D11): the values that clear an eligible row's expired columns; the row is kept.
    clear: Mapping[str, Any] | None = None


# The approved targets with their end-of-life predicates for a given cutoff.
def targets(settings: LifecycleSettings) -> tuple[Target, ...]:
    def before(days: int, cutoff: datetime) -> datetime:
        return cutoff - timedelta(days=days)

    # Accounts closed under D-024 decision 3; their credential state needs no waiting period.
    closed = select(User.id).where(User.closed_at.is_not(None))

    def sessions(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.session_retention_days, cutoff)
        idle = timedelta(seconds=settings.session_idle_seconds)
        return or_(
            AuthSession.revoked_at < limit,
            AuthSession.expires_at < limit,
            AuthSession.last_seen_at < limit - idle,
            AuthSession.user_id.in_(closed),
        )

    def tokens(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.token_retention_days, cutoff)
        return or_(
            AuthToken.consumed_at < limit,
            AuthToken.expires_at < limit,
            AuthToken.user_id.in_(closed),
        )

    def challenges(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.challenge_retention_days, cutoff)
        return or_(
            VerificationChallenge.consumed_at < limit,
            VerificationChallenge.invalidated_at < limit,
            VerificationChallenge.expires_at < limit,
            VerificationChallenge.user_id.in_(closed),
        )

    def transactions(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.oauth_transaction_retention_days, cutoff)
        return or_(
            OAuthTransaction.consumed_at < limit,
            OAuthTransaction.expires_at < limit,
            OAuthTransaction.user_id.in_(closed),
        )

    # Connector OAuth transactions (D-048) follow the same one-day rule as sign-in transactions.
    def connector_transactions(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.oauth_transaction_retention_days, cutoff)
        return or_(
            ConnectorOAuthTransaction.consumed_at < limit,
            ConnectorOAuthTransaction.expires_at < limit,
        )

    # Connector webhook delivery records (D-049) only recognize repeats; 7 days after receipt.
    def webhook_deliveries(cutoff: datetime) -> ColumnElement[bool]:
        return ConnectorWebhookDelivery.received_at < before(
            settings.webhook_delivery_retention_days, cutoff
        )

    # Connector records (D-053 decision D9) are kept at most 2 years after observation, or
    # their provider's shorter period (011-A, D11).
    def connector_records(cutoff: datetime) -> ColumnElement[bool]:
        rules = [
            ConnectorRecord.observed_at < before(settings.connector_record_retention_days, cutoff)
        ]
        for provider, days in sorted(settings.connector_provider_retention_days.items()):
            rules.append(
                and_(
                    ConnectorRecord.observed_at < before(days, cutoff),
                    ConnectorRecord.connection_id.in_(
                        select(ConnectorConnection.id).where(
                            ConnectorConnection.provider == provider
                        )
                    ),
                )
            )
        return or_(*rules)

    # Record attributes and account labels not refreshed within the period (011-A, D11).
    def stale_attributes(cutoff: datetime) -> ColumnElement[bool]:
        return ConnectorRecord.attributes_refreshed_at < before(
            settings.connector_attribute_refresh_days, cutoff
        )

    def stale_labels(cutoff: datetime) -> ColumnElement[bool]:
        return ConnectorConnection.account_label_refreshed_at < before(
            settings.connector_attribute_refresh_days, cutoff
        )

    # Advertising spend facts (D-064 D13): 730 days after their account-local spend date.
    def spend_facts(cutoff: datetime) -> ColumnElement[bool]:
        return AdSpendFact.spend_date < before(settings.ad_spend_retention_days, cutoff).date()

    # Conversion deliveries (D-064 D13): 30 days after they ended, acknowledgements first.
    def ended_deliveries(cutoff: datetime) -> Any:
        return select(ConversionDelivery.id).where(
            ConversionDelivery.ended_at < before(settings.delivery_retention_days, cutoff)
        )

    def acknowledgements(cutoff: datetime) -> ColumnElement[bool]:
        return ConversionAcknowledgement.delivery_id.in_(ended_deliveries(cutoff))

    def deliveries(cutoff: datetime) -> ColumnElement[bool]:
        return and_(
            ConversionDelivery.ended_at < before(settings.delivery_retention_days, cutoff),
            # Only the referencing column: the lifecycle role reads no other (0018).
            ~select(ConversionAcknowledgement.delivery_id)
            .where(ConversionAcknowledgement.delivery_id == ConversionDelivery.id)
            .exists(),
        )

    # Paymob callback diagnostics (D-067 D14): 30 days after receipt.
    def payment_diagnostics(cutoff: datetime) -> ColumnElement[bool]:
        return PaymentCallbackDiagnostic.received_at < before(
            settings.payment_diagnostic_retention_days, cutoff
        )

    # Replaced payment source secrets once retired, 24 hours after replacement (D-067 D14).
    def payment_secrets(cutoff: datetime) -> ColumnElement[bool]:
        return PaymentSourceSecret.retires_at < cutoff

    # Revenue import records (D-067 D14): 13 months (395 days) after the commit.
    def revenue_imports(cutoff: datetime) -> ColumnElement[bool]:
        return RevenueImport.committed_at < before(settings.revenue_import_retention_days, cutoff)

    # 015-D (D-068 E9): integration deliveries after 30 days, retired integration secrets,
    # and bookings and CRM deals 395 days after their last update.
    def integration_deliveries(cutoff: datetime) -> ColumnElement[bool]:
        return IntegrationDelivery.received_at < before(
            settings.integration_delivery_retention_days, cutoff
        )

    def integration_secrets(cutoff: datetime) -> ColumnElement[bool]:
        return IntegrationSourceSecret.retires_at < cutoff

    def bookings(cutoff: datetime) -> ColumnElement[bool]:
        return Booking.updated_at < before(settings.booking_retention_days, cutoff)

    def deals(cutoff: datetime) -> ColumnElement[bool]:
        return CrmDeal.updated_at < before(settings.deal_retention_days, cutoff)

    # 015-E (D-068 E9): WhatsApp referral messages 395 days after receipt.
    def whatsapp_messages(cutoff: datetime) -> ColumnElement[bool]:
        return WhatsappMessage.received_at < before(
            settings.whatsapp_message_retention_days, cutoff
        )

    def rate_limits(cutoff: datetime) -> ColumnElement[bool]:
        # An expired bucket already restarts at one attempt, so deleting it at expiry changes
        # no throttling decision.
        return AuthRateLimit.expires_at < cutoff

    def outbox(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.outbox_retention_days, cutoff)
        return or_(MailOutbox.delivered_at < limit, MailOutbox.expires_at < limit)

    def closed_credentials(cutoff: datetime) -> ColumnElement[bool]:
        return PasswordCredential.user_id.in_(closed)

    def closed_identities(cutoff: datetime) -> ColumnElement[bool]:
        # Deleting the identity frees the Google subject for a new sign-up (D-024).
        return ExternalIdentity.user_id.in_(closed)

    def events(cutoff: datetime) -> ColumnElement[bool]:
        limit = before(settings.event_retention_days, cutoff)
        return or_(CollectedEvent.expires_at < cutoff, CollectedEvent.first_received_at < limit)

    def counters(cutoff: datetime) -> ColumnElement[bool]:
        return EventDiagnostic.day < before(settings.diagnostic_retention_days, cutoff).date()

    def secrets(cutoff: datetime) -> ColumnElement[bool]:
        return IngestionSourceSecret.retires_at < cutoff

    # Subjects inactive for the approved period that no event row references any longer.
    def idle(cutoff: datetime) -> ColumnElement[bool]:
        return and_(
            CollectionSubject.last_activity_at < before(settings.subject_retention_days, cutoff),
            ~exists().where(CollectedEvent.subject_id == CollectionSubject.id),
        )

    # Consent records of idle subjects, removed so that no committed batch can change a
    # purpose's effective consent into a grant (review finding R004-04). Admission evaluates
    # the latest record per subject and purpose, ordered by (received_at, id) exactly as
    # app.privacy.consent.current_state does. A record is eligible only when
    # - a newer record of the same subject and purpose exists: deleting it leaves the
    #   effective record, and so the evaluated state, unchanged; or
    # - no older record of that subject and purpose exists: deleting it leaves the purpose
    #   with no record, which J1 evaluates as unknown, a denial.
    # The latest record of a purpose that still has older records is therefore never deleted,
    # so a withdrawal or denial cannot disappear while an older grant remains. Each DELETE
    # evaluates these predicates on one snapshot, so the latest record becomes eligible only in
    # a later statement, after its older records are gone.
    def consent_records(cutoff: datetime) -> ColumnElement[bool]:
        record = tuple_(StoredConsentRecord.received_at, StoredConsentRecord.id)

        def sibling(other: Any) -> ColumnElement[bool]:
            return and_(
                other.subject_id == StoredConsentRecord.subject_id,
                other.purpose == StoredConsentRecord.purpose,
            )

        newer, older = aliased(StoredConsentRecord), aliased(StoredConsentRecord)
        return and_(
            StoredConsentRecord.subject_id.in_(select(CollectionSubject.id).where(idle(cutoff))),
            or_(
                exists().where(sibling(newer), tuple_(newer.received_at, newer.id) > record),
                ~exists().where(sibling(older), tuple_(older.received_at, older.id) < record),
            ),
        )

    # Idle subjects without consent records left: their consent history is gone.
    def expiring(cutoff: datetime) -> ColumnElement[bool]:
        return and_(
            idle(cutoff),
            ~exists().where(StoredConsentRecord.subject_id == CollectionSubject.id),
        )

    # Bookings linked to an expiring subject: both link columns are cleared together, in the
    # batch before the subject's deletion (R002). Only granted columns are read.
    def booking_links(cutoff: datetime) -> ColumnElement[bool]:
        return Booking.subject_id.in_(select(CollectionSubject.id).where(expiring(cutoff)))

    # A subject is deleted only after all its consent records and booking links, so a bounded
    # batch never breaks the consent foreign key or the bookings link constraint.
    def subjects(cutoff: datetime) -> ColumnElement[bool]:
        return and_(
            expiring(cutoff),
            ~select(Booking.subject_id).where(Booking.subject_id == CollectionSubject.id).exists(),
        )

    return (
        Target(
            "password_credentials",
            PasswordCredential,
            PasswordCredential.user_id,
            closed_credentials,
        ),
        Target("external_identities", ExternalIdentity, ExternalIdentity.id, closed_identities),
        Target("auth_sessions", AuthSession, AuthSession.id, sessions),
        Target("auth_tokens", AuthToken, AuthToken.id, tokens),
        Target(
            "verification_challenges", VerificationChallenge, VerificationChallenge.id, challenges
        ),
        Target("oauth_transactions", OAuthTransaction, OAuthTransaction.id, transactions),
        Target(
            "connector_oauth_transactions",
            ConnectorOAuthTransaction,
            ConnectorOAuthTransaction.id,
            connector_transactions,
        ),
        Target(
            "connector_webhook_deliveries",
            ConnectorWebhookDelivery,
            ConnectorWebhookDelivery.id,
            webhook_deliveries,
        ),
        Target("connector_records", ConnectorRecord, ConnectorRecord.id, connector_records),
        Target(
            "connector_record_attributes",
            ConnectorRecord,
            ConnectorRecord.id,
            stale_attributes,
            clear={"attributes": {}, "attributes_refreshed_at": None},
        ),
        Target(
            "connector_account_labels",
            ConnectorConnection,
            ConnectorConnection.id,
            stale_labels,
            clear={"account_label": None, "account_label_refreshed_at": None},
        ),
        Target("ad_spend_facts", AdSpendFact, AdSpendFact.id, spend_facts),
        Target(
            "conversion_acknowledgements",
            ConversionAcknowledgement,
            ConversionAcknowledgement.id,
            acknowledgements,
        ),
        Target("conversion_deliveries", ConversionDelivery, ConversionDelivery.id, deliveries),
        Target(
            "payment_callback_diagnostics",
            PaymentCallbackDiagnostic,
            PaymentCallbackDiagnostic.id,
            payment_diagnostics,
        ),
        Target(
            "payment_source_secrets", PaymentSourceSecret, PaymentSourceSecret.id, payment_secrets
        ),
        Target("revenue_imports", RevenueImport, RevenueImport.id, revenue_imports),
        Target(
            "integration_deliveries",
            IntegrationDelivery,
            IntegrationDelivery.id,
            integration_deliveries,
        ),
        Target(
            "integration_source_secrets",
            IntegrationSourceSecret,
            IntegrationSourceSecret.id,
            integration_secrets,
        ),
        Target("bookings", Booking, Booking.id, bookings),
        Target("crm_deals", CrmDeal, CrmDeal.id, deals),
        Target("whatsapp_messages", WhatsappMessage, WhatsappMessage.id, whatsapp_messages),
        Target("auth_rate_limits", AuthRateLimit, AuthRateLimit.bucket_key, rate_limits),
        Target("mail_outbox", MailOutbox, MailOutbox.id, outbox),
        Target("collected_events", CollectedEvent, CollectedEvent.id, events, True),
        Target("event_diagnostics", EventDiagnostic, EventDiagnostic.id, counters),
        Target(
            "ingestion_source_secrets", IngestionSourceSecret, IngestionSourceSecret.id, secrets
        ),
        Target(
            "consent_records", StoredConsentRecord, StoredConsentRecord.id, consent_records, True
        ),
        Target(
            "booking_links",
            Booking,
            Booking.id,
            booking_links,
            True,
            clear={"subject_id": None, "linked_at": None},
        ),
        Target("collection_subjects", CollectionSubject, CollectionSubject.id, subjects, True),
    )


# Delete one ordered batch of eligible rows, or clear their expired columns for a clearing
# target. The outer predicate repeats the eligibility test, so PostgreSQL re-checks a row
# changed by a concurrent transaction (for example a rate-limit bucket restarted after the key
# subquery ran) and leaves it in place.
def _delete_batch(connection: Any, target: Target, cutoff: datetime, size: int) -> int:
    condition = target.eligible(cutoff)
    keys = select(target.key).where(condition).order_by(target.key).limit(size)
    connection.execute(text(f"SET LOCAL lock_timeout = '{BATCH_LOCK_TIMEOUT}'"))
    if target.clear is not None:
        statement = update(target.model).where(target.key.in_(keys), condition)
        return connection.execute(statement.values(**target.clear)).rowcount
    return connection.execute(delete(target.model).where(target.key.in_(keys), condition)).rowcount


# Delete one bounded batch of each client-scoped target for one client, in the caller's open
# transaction, which the caller commits or rolls back. The client's privacy lock is taken first
# with the batch lock timeout, so a held lock aborts this batch (OperationalError) instead of
# waiting. Every predicate runs after the lock is held and therefore sees the committed result
# of any admission, consent change, or erasure that held it.
def delete_client_batch(
    connection: Any, scoped: Sequence[Target], client_id: UUID, cutoff: datetime, size: int
) -> dict[str, int]:
    connection.execute(text(f"SET LOCAL lock_timeout = '{BATCH_LOCK_TIMEOUT}'"))
    connection.execute(
        select(func.pg_advisory_xact_lock(CLIENT_LOCK_NAMESPACE, client_lock_key(client_id)))
    )
    counts: dict[str, int] = {}
    for target in scoped:
        condition = and_(target.model.client_id == client_id, target.eligible(cutoff))
        keys = select(target.key).where(condition).order_by(target.key).limit(size)
        if target.clear is not None:
            statement = update(target.model).where(target.key.in_(keys), condition)
            counts[target.name] = connection.execute(statement.values(**target.clear)).rowcount
            continue
        counts[target.name] = connection.execute(
            delete(target.model).where(target.key.in_(keys), condition)
        ).rowcount
    return counts


# Clients that may have eligible collected data; only a candidate list; eligibility is decided
# again under each client's lock.
def _client_candidates(connection: Any, scoped: Sequence[Target], cutoff: datetime) -> list[UUID]:
    query = union(
        *(select(target.model.client_id).where(target.eligible(cutoff)) for target in scoped)
    )
    return sorted(connection.execute(query).scalars())


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
# max_batches bounds the work per target (None means until no eligible row remains). Then the
# client-scoped targets run client by client under each client's privacy lock: a client whose
# lock is busy is skipped and marked incomplete, and max_batches bounds the batches per client.
# A client's batches continue until one deletes nothing, because a consent record that becomes
# eligible only after its older history is gone may follow a short batch (R004-04). Returns
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
            every = targets(settings)
            scoped = [target for target in every if target.client_scoped]
            deleted.update((target.name, 0) for target in scoped)
            for target in every:
                if target.client_scoped:
                    continue
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
            clients = _client_candidates(connection, scoped, cutoff) if scoped else []
            connection.commit()
            for client_id in clients:
                batches = 0
                while max_batches is None or batches < max_batches:
                    try:
                        counts = delete_client_batch(connection, scoped, client_id, cutoff, size)
                        connection.commit()
                    except OperationalError:
                        connection.rollback()
                        _mark(incomplete, scoped)
                        break
                    batches += 1
                    for name, count in counts.items():
                        deleted[name] += count
                    if not any(counts.values()):
                        break
                else:
                    _mark(incomplete, scoped)
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


def _mark(incomplete: list[str], scoped: Sequence[Target]) -> None:
    incomplete.extend(target.name for target in scoped if target.name not in incomplete)
