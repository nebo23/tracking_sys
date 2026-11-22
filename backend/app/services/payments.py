"""Paymob payment sources and callback intake (specification 015-B, D-067 D3, D4, D10 and D12).

Owner and Admin administration creates, lists, renames, disables and re-activates a client's
Paymob sources and replaces their merchant HMAC secret, each with an audit event in the caller's
transaction. The secret is sealed under the D-025 keyring at once and is never returned or
logged; a replaced version stays valid for SECRET_OVERLAP. The Paymob source type is off unless
TRACKING_PAYMENTS_PAYMOB_ENABLED is set and both provider rules are current (gate).

receive_callback records one verified callback: it maps the minimized transaction (app.payments
.paymob), appends the evidence under the client's revenue lock, and leaves one diagnostic row.
Each source names the merchant's live integration IDs (D-070), and only a callback whose signed
integration_id is among them can post. A refund or void whose parent sale is already stored
posts only when both carry the same signed order ID; otherwise it is unmapped (invalid_parent)
and stores nothing. Nothing here calls Paymob.
"""

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.ledger import Evidence, OperationKind
from app.models import (
    Agency,
    ClientWorkspace,
    PaymentCallbackDiagnostic,
    PaymentSource,
    PaymentSourceSecret,
    RevenueEvidence,
)
from app.models.payments import MAX_LIVE_INTEGRATIONS
from app.payments.paymob import REGIONS, Mapped, Posting, Verified, map_transaction, same_order
from app.privacy.providers import feature_allowed, rule
from app.privacy.token_secrets import LocalKeyring, SealedSecret, SecretContext, open_secret, seal
from app.security import new_token
from app.services.collection import require_token_keys
from app.services.revenue import append_evidence, lock_revenue
from app.services.tenancy import AccessDenied, TenancyService

SECRET_OVERLAP = timedelta(hours=24)
# Provider rules that must be current before Paymob sources are created or callbacks accepted.
RULES = ("payments.processor_records", "paymob.accept")
HMAC_SECRET = re.compile(r"[!-~]{16,256}")
PUBLIC_KEY = re.compile(r"ppk_[A-Za-z0-9_-]{43}")
CALLBACK_PATH = "/payments/paymob/callback/{public_key}"


class PaymentError(Exception):
    """A payment failure with a fixed public code; it never carries a secret or payload."""

    def __init__(self, code: str, status: int) -> None:
        self.code, self.status = code, status
        super().__init__(code)


# Whether the Paymob source type may be used today: the setting is on and every rule it
# depends on is current and within its review date (D12).
def paymob_allowed(settings: Settings, today: date) -> bool:
    return settings.payments_paymob_enabled and all(
        feature_allowed(rule(name), today).allowed for name in RULES
    )


def require_paymob(settings: Settings, today: date) -> None:
    if not paymob_allowed(settings, today):
        raise PaymentError("payments_unavailable", 503)


def callback_path(source: PaymentSource) -> str:
    return CALLBACK_PATH.format(public_key=source.public_key)


def _context(source: PaymentSource, secret_id: UUID, version: int) -> SecretContext:
    return SecretContext(
        source.agency_id, source.client_id, source.id, secret_id, "paymob_hmac", version
    )


def _hmac_secret(value: str) -> str:
    if not isinstance(value, str) or not HMAC_SECRET.fullmatch(value):
        raise ValueError("The HMAC secret must be 16-256 printable characters without spaces.")
    return value


# The merchant's live integration IDs (D-070): 1 to 20 positive integers that fit a bigint,
# kept sorted without repetition. Paymob shows them on the dashboard in live mode.
def _live_integrations(values: Sequence[int]) -> list[int]:
    # Every element is checked before the set is built, so a mixed or unhashable list is a
    # validation error, never a TypeError.
    if not isinstance(values, Sequence) or isinstance(values, str | bytes):
        raise ValueError("Give 1 to 20 live integration IDs.")
    if not all(
        isinstance(item, int) and not isinstance(item, bool) and 0 < item < 2**63 for item in values
    ):
        raise ValueError("Give 1 to 20 live integration IDs.")
    items = sorted(set(values))
    if not 1 <= len(items) <= MAX_LIVE_INTEGRATIONS:
        raise ValueError("Give 1 to 20 live integration IDs.")
    return items


def _store_secret(
    session: Session, keyring: LocalKeyring, source: PaymentSource, raw: str, version: int
) -> None:
    secret_id = uuid4()
    sealed = seal(keyring, raw, _context(source, secret_id, version))
    session.add(
        PaymentSourceSecret(
            id=secret_id,
            agency_id=source.agency_id,
            client_id=source.client_id,
            source_id=source.id,
            version=version,
            kek_id=sealed.kek_id,
            wrap_nonce=sealed.wrap_nonce,
            wrapped_dek=sealed.wrapped_dek,
            nonce=sealed.nonce,
            ciphertext=sealed.ciphertext,
        )
    )


# Owner/Admin administration of payment sources (D3, D10); audited in the caller's transaction.
class PaymentSourceAdmin(TenancyService):
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    def _today(self) -> date:
        return self.session.scalar(select(func.clock_timestamp())).date()

    def _source(self, agency_id: UUID, client_id: UUID, source_id: UUID) -> PaymentSource:
        item = self.session.scalar(
            select(PaymentSource)
            .where(
                PaymentSource.agency_id == agency_id,
                PaymentSource.client_id == client_id,
                PaymentSource.id == source_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AccessDenied()
        return item

    def create(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        provider: Literal["paymob"],
        region: str,
        name: str,
        hmac_secret: str,
        live_integration_ids: Sequence[int],
    ) -> PaymentSource:
        actor = self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        if provider != "paymob" or region not in REGIONS:
            raise ValueError("Unsupported provider or region.")
        secret = _hmac_secret(hmac_secret)
        live = _live_integrations(live_integration_ids)
        require_paymob(self.settings, self._today())
        keyring = require_token_keys(self.settings)
        source = PaymentSource(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            provider=provider,
            region=region,
            name=self._name(name),
            status="active",
            public_key="ppk_" + new_token(),
            live_integration_ids=live,
            created_by_membership_id=actor.id,
        )
        self.session.add(source)
        self.session.flush()
        _store_secret(self.session, keyring, source, secret, 1)
        self._audit(agency_id, "payment_source.created", "payment_source", source.id, client_id)
        return source

    def list(self, agency_id: UUID, client_id: UUID) -> list[PaymentSource]:
        self._manager(agency_id)
        self.get_client(agency_id, client_id)
        return list(
            self.session.scalars(
                select(PaymentSource)
                .where(PaymentSource.agency_id == agency_id, PaymentSource.client_id == client_id)
                .order_by(PaymentSource.created_at, PaymentSource.id)
                .limit(100)
            )
        )

    # A new merchant secret version; the previous versions stay valid for SECRET_OVERLAP.
    def replace_secret(
        self, agency_id: UUID, client_id: UUID, source_id: UUID, hmac_secret: str
    ) -> PaymentSource:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        source = self._source(agency_id, client_id, source_id)
        secret = _hmac_secret(hmac_secret)
        keyring = require_token_keys(self.settings)
        now = self.session.scalar(select(func.clock_timestamp()))
        versions = list(
            self.session.scalars(
                select(PaymentSourceSecret).where(PaymentSourceSecret.source_id == source.id)
            )
        )
        for item in versions:
            if item.retires_at is None:
                item.retires_at = now + SECRET_OVERLAP
        latest = max((item.version for item in versions), default=0)
        _store_secret(self.session, keyring, source, secret, latest + 1)
        source.updated_at = now
        self._audit(
            agency_id, "payment_source.secret_replaced", "payment_source", source.id, client_id
        )
        return source

    def update(
        self,
        agency_id: UUID,
        client_id: UUID,
        source_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        live_integration_ids: Sequence[int] | None = None,
    ) -> PaymentSource:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)
        source = self._source(agency_id, client_id, source_id)
        if status is not None and status not in {"active", "disabled"}:
            raise ValueError("Invalid source status.")
        live = None if live_integration_ids is None else _live_integrations(live_integration_ids)
        if status == "active" and source.status != "active":
            require_paymob(self.settings, self._today())
        if name is not None:
            source.name = self._name(name)
        if status is not None:
            source.status = status
        if live is not None:
            source.live_integration_ids = live
        source.updated_at = self.session.scalar(select(func.clock_timestamp()))
        self._audit(agency_id, "payment_source.updated", "payment_source", source.id, client_id)
        return source


# The active source of an active client and agency behind a public key, or None. A malformed key
# is looked up by nobody.
def live_source(session: Session, public_key: str) -> PaymentSource | None:
    if not PUBLIC_KEY.fullmatch(public_key):
        return None
    return session.scalar(
        select(PaymentSource)
        .join(
            ClientWorkspace,
            (ClientWorkspace.agency_id == PaymentSource.agency_id)
            & (ClientWorkspace.id == PaymentSource.client_id),
        )
        .join(Agency, Agency.id == PaymentSource.agency_id)
        .where(
            PaymentSource.public_key == public_key,
            PaymentSource.status == "active",
            ClientWorkspace.status == "active",
            Agency.status == "active",
        )
        .execution_options(populate_existing=True)
    )


# Every secret version of a source still valid at now: the current one and those replaced less
# than SECRET_OVERLAP ago. No version is dropped by a count limit.
def live_secrets(
    session: Session, settings: Settings, source: PaymentSource, now: datetime
) -> list[str]:
    keyring = require_token_keys(settings)
    rows = session.scalars(
        select(PaymentSourceSecret)
        .where(
            PaymentSourceSecret.source_id == source.id,
            (PaymentSourceSecret.retires_at.is_(None)) | (PaymentSourceSecret.retires_at > now),
        )
        .order_by(PaymentSourceSecret.version.desc())
    )
    return [
        open_secret(
            keyring,
            SealedSecret(row.kek_id, row.wrap_nonce, row.wrapped_dek, row.nonce, row.ciphertext),
            _context(source, row.id, row.version),
        )
        for row in rows
    ]


# Whether a refund or void may be stored against its named parent (D-070): when a Paymob sale of
# that operation is already stored for the client, one of them must carry the refund's signed
# order ID. A parent not yet stored is checked on every ledger read instead (app.services.revenue).
def _parent_bound(session: Session, source: PaymentSource, posting: Posting) -> bool:
    parents = list(
        session.scalars(
            select(RevenueEvidence.source_reference).where(
                RevenueEvidence.agency_id == source.agency_id,
                RevenueEvidence.client_id == source.client_id,
                RevenueEvidence.source_account_id == posting.source_account_id,
                RevenueEvidence.operation_id == posting.parent_operation_id,
                RevenueEvidence.kind == OperationKind.SALE.value,
                RevenueEvidence.intake == "paymob",
            )
        )
    )
    return not parents or any(same_order(posting.source_reference, item) for item in parents)


# Record one verified callback of a source (D4, D5, D7): map it, append the evidence under the
# client's revenue lock, and add one diagnostic row. Returns the closed outcome.
def receive_callback(session: Session, source: PaymentSource, verified: Verified) -> Mapped:
    received = lock_revenue(session, source.client_id)
    if verified.kind == "TOKEN" or verified.transaction is None:
        mapped = Mapped("unmapped", "card_token")
    else:
        mapped = map_transaction(
            verified.transaction, source.region, live_integrations=source.live_integration_ids
        )
    posting = mapped.posting
    if (
        posting is not None
        and posting.kind is OperationKind.REFUND
        and not _parent_bound(session, source, posting)
    ):
        mapped = Mapped("unmapped", "invalid_parent")
    if mapped.posting is not None:
        posting = mapped.posting
        outcome = append_evidence(
            session,
            Evidence(
                delivery_id=posting.delivery_id,
                agency_id=source.agency_id,
                client_id=source.client_id,
                source_account_id=posting.source_account_id,
                operation_id=posting.operation_id,
                kind=posting.kind,
                classification=posting.classification,
                amount=posting.amount,
                effective_at=posting.effective_at,
                received_at=received,
                parent_operation_id=posting.parent_operation_id,
                reason=posting.reason,
                source_reference=posting.source_reference,
            ),
            "paymob",
            source.id,
        )
        mapped = Mapped(outcome, None, posting)
    session.add(
        PaymentCallbackDiagnostic(
            id=uuid4(),
            agency_id=source.agency_id,
            client_id=source.client_id,
            source_id=source.id,
            delivery_digest=verified.delivery_digest,
            received_at=received,
            outcome=mapped.outcome,
            reason=mapped.reason,
        )
    )
    session.flush()
    return mapped
