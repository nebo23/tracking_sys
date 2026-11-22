"""Canonical digests of report inputs and revisions (specification 016-A, D-072 decision D7).

A Digest absorbs canonical JSON items in order: sorted keys, compact separators, dates and
instants in ISO form (instants in UTC), UUIDs as text. Two reads of the same inputs give the same
hex digest; any change to an absorbed value changes it. A revision is the digest of the
authenticated principal, the scope and permission, the normalized query, the contract and catalog
versions, the source identity and the input and semantic digests. It is an equality check for
pagination and release, never a credential, a signature or an authorization grant, and the
inputs it covers are never part of a response.
"""

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def _default(value: object) -> object:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise TypeError("naive datetime in a report digest")
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=lambda item: json.dumps(item, default=_default, sort_keys=True))
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"unsupported type in a report digest: {type(value).__name__}")


def canonical(value: object) -> str:
    return json.dumps(
        value,
        default=_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


class Digest:
    def __init__(self, label: str) -> None:
        self._hash = hashlib.sha256()
        self.add(label)

    def add(self, item: Any) -> None:
        data = canonical(item).encode()
        self._hash.update(len(data).to_bytes(8, "big"))
        self._hash.update(data)

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def digest_of(label: str, *items: Any) -> str:
    target = Digest(label)
    for item in items:
        target.add(item)
    return target.hexdigest()
