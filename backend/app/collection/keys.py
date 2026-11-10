"""Independent tombstone keyring for specification 004 (D-027 decision 9).

Tombstones hold HMAC match keys (app.privacy.deletion.tombstone_key), never the deleted
values, so a tombstone key can never be re-keyed: every retained key ID stays usable for
lookups for as long as its tombstones exist. Rotation is therefore add-only: a new active key
signs new tombstones while lookups compute match keys under every retained key. The keyring
is development-only local custody held in ignored .env (TRACKING_TOMBSTONE_KEYRING as
"id:hex,id:hex" plus TRACKING_TOMBSTONE_KEYRING_ACTIVE); managed custody follows 020.
"""

import re
from collections.abc import Mapping
from uuid import UUID

_KEY_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


class TombstoneKeyring:
    def __init__(self, keys: Mapping[str, bytes], active: str) -> None:
        if not keys or active not in keys:
            raise ValueError("The active tombstone key must be in the keyring.")
        for key_id, key in keys.items():
            if not _KEY_ID.fullmatch(key_id) or len(key) < 32:
                raise ValueError("Each tombstone key needs a short lowercase ID and 32+ bytes.")
        if len(set(keys.values())) != len(keys):
            raise ValueError("Tombstone keys must be distinct.")
        self._keys, self.active = dict(keys), active

    # Parse "id:hex,id:hex" as stored in ignored .env.
    @classmethod
    def from_text(cls, text: str, active: str) -> "TombstoneKeyring":
        keys: dict[str, bytes] = {}
        for item in filter(None, (part.strip() for part in text.split(","))):
            key_id, _, encoded = item.partition(":")
            if key_id in keys:
                raise ValueError("Tombstone key IDs must be unique.")
            keys[key_id] = bytes.fromhex(encoded)
        return cls(keys, active)

    def __repr__(self) -> str:
        return f"TombstoneKeyring(active={self.active!r}, keys={len(self._keys)})"

    def key_material(self) -> frozenset[bytes]:
        return frozenset(self._keys.values())

    # Match key for a new tombstone under the active key, with that key's ID.
    def seal(self, client_id: UUID, kind: str, value: str) -> tuple[bytes, str]:
        # Imported here: app.config parses this keyring, and the deletion contract imports
        # app.security, which imports app.config.
        from app.privacy.deletion import tombstone_key

        return tombstone_key(self._keys[self.active], client_id, kind, value), self.active

    # Match keys of one value under every retained key, for lookups.
    def candidates(self, client_id: UUID, kind: str, value: str) -> list[bytes]:
        from app.privacy.deletion import tombstone_key

        return [tombstone_key(key, client_id, kind, value) for key in self._keys.values()]
