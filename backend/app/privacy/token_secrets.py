"""TokenSecretReference contract: envelope encryption of connector tokens (specification
003-C, D-025).

Each secret version gets a fresh 256-bit data key and 96-bit nonce under AES-GCM (the approved
cryptography package). The data key is wrapped with AES-GCM under a key-encryption key (KEK)
from a keyring. Associated data binds the ciphertext to its agency, client, connector, secret,
kind, and version, and the wrap to its KEK and secret, so a ciphertext copied to another row or
tenant fails to open. D-025 decision 16: development uses a local keyring held in ignored
.env; production refuses it until managed custody is chosen with hosting (020). Tokens are
never logged, exported, or sent to the browser; storage accepts tokens of 1,000+ characters.
"""

import base64
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ALGORITHM = "A256GCM-ENV-v1"
AAD_VERSION = 1
_KEK_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


class SecretStatus(StrEnum):
    ACTIVE = "active"
    REFRESH_DUE = "refresh_due"
    REVOKED = "revoked"
    DESTROYED = "destroyed"


@dataclass(frozen=True)
class SecretContext:
    agency_id: UUID
    client_id: UUID
    connector_id: UUID
    secret_id: UUID
    kind: Literal["access_token", "refresh_token"]
    version: int


# Stored form of one secret version; repr never shows key or ciphertext material.
@dataclass(frozen=True)
class SealedSecret:
    kek_id: str
    wrap_nonce: bytes
    wrapped_dek: bytes
    nonce: bytes
    ciphertext: bytes
    algorithm: str = ALGORITHM
    aad_version: int = AAD_VERSION

    def __repr__(self) -> str:
        return f"SealedSecret(kek_id={self.kek_id!r}, algorithm={self.algorithm!r})"


# The TokenSecretReference row contract (design section 8); a table follows specification 009.
@dataclass(frozen=True)
class TokenSecretReference:
    context: SecretContext
    status: SecretStatus
    created_at: datetime
    sealed: SealedSecret | None
    provider_expires_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    destroyed_at: datetime | None = None

    # Destroy the ciphertext and wrapped key. Revocation at the provider remains the primary
    # control and is the connector's responsibility (specification 009).
    def destroyed(self, now: datetime) -> "TokenSecretReference":
        return replace(self, status=SecretStatus.DESTROYED, sealed=None, destroyed_at=now)


# Local development keyring: KEK ID -> 32-byte key. Production refuses it.
class LocalKeyring:
    def __init__(
        self, keys: Mapping[str, bytes], active: str, *, environment: str = "development"
    ) -> None:
        if environment != "development":
            raise ValueError("Production requires managed key custody (specification 020).")
        if not keys or active not in keys:
            raise ValueError("The active KEK must be in the keyring.")
        for kek_id, key in keys.items():
            if not _KEK_ID.fullmatch(kek_id) or len(key) != 32:
                raise ValueError("Each KEK needs a short lowercase ID and 32 key bytes.")
        self._keys, self.active = dict(keys), active

    # Parse "id:base64url,id:base64url" as stored in ignored .env (TRACKING_TOKEN_KEYRING).
    @classmethod
    def from_text(cls, text: str, active: str, *, environment: str = "development"):
        keys: dict[str, bytes] = {}
        for item in filter(None, (part.strip() for part in text.split(","))):
            kek_id, _, encoded = item.partition(":")
            keys[kek_id] = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        return cls(keys, active, environment=environment)

    def __repr__(self) -> str:
        return f"LocalKeyring(active={self.active!r}, keys={len(self._keys)})"

    def key(self, kek_id: str) -> bytes:
        if kek_id not in self._keys:
            raise KeyError("Unknown key-encryption key.")
        return self._keys[kek_id]


def _encode(*parts: bytes) -> bytes:
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def _secret_aad(context: SecretContext) -> bytes:
    return _encode(
        f"tracking-token:{AAD_VERSION}".encode(),
        context.agency_id.bytes,
        context.client_id.bytes,
        context.connector_id.bytes,
        context.secret_id.bytes,
        context.kind.encode(),
        str(context.version).encode(),
    )


def _wrap_aad(kek_id: str, context: SecretContext) -> bytes:
    return _encode(b"tracking-token-wrap:1", kek_id.encode(), context.secret_id.bytes)


def _wrap(keyring: LocalKeyring, kek_id: str, dek: bytes, context: SecretContext):
    nonce = os.urandom(12)
    return nonce, AESGCM(keyring.key(kek_id)).encrypt(nonce, dek, _wrap_aad(kek_id, context))


def seal(keyring: LocalKeyring, token: str, context: SecretContext) -> SealedSecret:
    dek, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(nonce, token.encode(), _secret_aad(context))
    wrap_nonce, wrapped = _wrap(keyring, keyring.active, dek, context)
    return SealedSecret(keyring.active, wrap_nonce, wrapped, nonce, ciphertext)


# Open a sealed secret for exactly this context; any change raises InvalidTag.
def open_secret(keyring: LocalKeyring, sealed: SealedSecret, context: SecretContext) -> str:
    if sealed.algorithm != ALGORITHM or sealed.aad_version != AAD_VERSION:
        raise ValueError("Unsupported secret format.")
    dek = AESGCM(keyring.key(sealed.kek_id)).decrypt(
        sealed.wrap_nonce, sealed.wrapped_dek, _wrap_aad(sealed.kek_id, context)
    )
    return AESGCM(dek).decrypt(sealed.nonce, sealed.ciphertext, _secret_aad(context)).decode()


# KEK rotation: re-wrap the data key under the active KEK without touching the token
# ciphertext or its nonce. A retired KEK may be removed only when no row and no retained
# backup still references it.
def rewrap(keyring: LocalKeyring, sealed: SealedSecret, context: SecretContext) -> SealedSecret:
    dek = AESGCM(keyring.key(sealed.kek_id)).decrypt(
        sealed.wrap_nonce, sealed.wrapped_dek, _wrap_aad(sealed.kek_id, context)
    )
    wrap_nonce, wrapped = _wrap(keyring, keyring.active, dek, context)
    return replace(sealed, kek_id=keyring.active, wrap_nonce=wrap_nonce, wrapped_dek=wrapped)
