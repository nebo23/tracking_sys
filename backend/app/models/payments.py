"""Paymob payment sources, sealed HMAC secrets and callback diagnostics (specification 015-B).

D-067 decisions D3, D4, D12 and D14. A payment source belongs to one client and carries an
unguessable public key for its callback URL and the live integration IDs the merchant declared
(D-070): only a signed integration_id in that list can post. The merchant's HMAC secret is
sealed under the D-025
keyring; a replaced secret stays valid until retires_at, 24 hours later, and tracking_lifecycle
deletes retired secrets. Each verified callback leaves one diagnostic row (source, a digest of
the received signature, receipt time and a closed outcome) that tracking_lifecycle deletes after
30 days. No table holds card, billing, shipping or customer data, or a payload (D6). Reference
queries below are manual read-only diagnostics for an authorized operator; replace the synthetic
literals before use. Sealed material and public keys are omitted.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

CLIENT_FK = (["agency_id", "client_id"], ["client_workspaces.agency_id", "client_workspaces.id"])
SOURCE_FK = (
    ["agency_id", "client_id", "source_id"],
    ["payment_sources.agency_id", "payment_sources.client_id", "payment_sources.id"],
)
OUTCOMES = ("stored", "duplicate", "not_posted", "unmapped", "test_mode")
REASONS = (
    "authorization",
    "failed",
    "pending",
    "card_token",
    "unsupported_state",
    "unsupported_currency",
    "invalid_time",
    "invalid_amount",
    "invalid_parent",
    "undeclared_integration",
)
PUBLIC_KEY = "^ppk_[A-Za-z0-9_-]{43}$"
MAX_LIVE_INTEGRATIONS = 20
# D-070: 1 to 20 positive live integration IDs, without nulls (0 < ALL alone passes a null).
LIVE_INTEGRATIONS_CHECK = (
    f"cardinality(live_integration_ids) BETWEEN 1 AND {MAX_LIVE_INTEGRATIONS} "
    "AND array_position(live_integration_ids, NULL) IS NULL "
    "AND 0 < ALL (live_integration_ids)"
)


def _values(items: tuple[str, ...]) -> str:
    return ", ".join(f"'{item}'" for item in items)


# One client's Paymob payment source (D3): provider, region, name, status, the public key of its
# callback URL (POST /payments/paymob/callback/{public_key}) and the live integration IDs the
# merchant declared (D-070).
# SELECT id, provider, region, name, status, created_at, updated_at
# FROM public.payment_sources
# WHERE agency_id = '00000000-0000-0000-0000-000000000002'::uuid
#   AND client_id = '00000000-0000-0000-0000-000000000003'::uuid
# ORDER BY created_at, id LIMIT 100;
class PaymentSource(Base):
    __tablename__ = "payment_sources"
    __table_args__ = (
        ForeignKeyConstraint(*CLIENT_FK),
        ForeignKeyConstraint(
            ["agency_id", "created_by_membership_id"],
            ["agency_memberships.agency_id", "agency_memberships.id"],
        ),
        UniqueConstraint("agency_id", "client_id", "id", name="uq_payment_sources_scope"),
        UniqueConstraint("public_key", name="uq_payment_sources_public_key"),
        Index("ix_payment_sources_agency_client", "agency_id", "client_id"),
        CheckConstraint("provider = 'paymob'", name="valid_provider"),
        CheckConstraint("region = 'egypt'", name="valid_region"),
        CheckConstraint("status IN ('active', 'disabled')", name="valid_status"),
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 200", name="valid_name"),
        CheckConstraint(f"public_key ~ '{PUBLIC_KEY}'", name="valid_public_key"),
        CheckConstraint(LIVE_INTEGRATIONS_CHECK, name="valid_live_integrations"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(16))
    region: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    public_key: Mapped[str] = mapped_column(String(64))
    live_integration_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    created_by_membership_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Sealed merchant HMAC secret versions of one source (token_secrets envelope, kind paymob_hmac).
# The newest unretired version and any version before its retires_at verify callbacks.
# SELECT id, source_id, version, kek_id, created_at, retires_at
# FROM public.payment_source_secrets
# WHERE source_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY version DESC LIMIT 5;
class PaymentSourceSecret(Base):
    __tablename__ = "payment_source_secrets"
    __table_args__ = (
        ForeignKeyConstraint(*SOURCE_FK),
        UniqueConstraint("source_id", "version", name="uq_payment_source_secrets_version"),
        CheckConstraint("version >= 1", name="positive_version"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    kek_id: Mapped[str] = mapped_column(String(32))
    wrap_nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    retires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# One verified callback of one source: a digest of the received signature, the receipt time and
# a closed outcome with an optional closed reason. Deleted 30 days after receipt (D14).
# SELECT received_at, outcome, reason
# FROM public.payment_callback_diagnostics
# WHERE source_id = '00000000-0000-0000-0000-000000000009'::uuid
# ORDER BY received_at DESC LIMIT 100;
class PaymentCallbackDiagnostic(Base):
    __tablename__ = "payment_callback_diagnostics"
    __table_args__ = (
        ForeignKeyConstraint(*SOURCE_FK),
        Index("ix_payment_callback_diagnostics_received_at", "received_at"),
        CheckConstraint(f"outcome IN ({_values(OUTCOMES)})", name="valid_outcome"),
        CheckConstraint(f"reason IS NULL OR reason IN ({_values(REASONS)})", name="valid_reason"),
        CheckConstraint("delivery_digest ~ '^[0-9a-f]{64}$'", name="valid_digest"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agency_id: Mapped[UUID] = mapped_column(Uuid)
    client_id: Mapped[UUID] = mapped_column(Uuid)
    source_id: Mapped[UUID] = mapped_column(Uuid)
    delivery_digest: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(32))
