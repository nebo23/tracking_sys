"""Deletion journal and restore reconciliation contract (specification 003-D, D-025).

Point-in-time recovery loses entries written after the recovery target, so every tombstone
and consent withdrawal is also written to an independent append-only journal with monotonic
sequence numbers and an HMAC chain. After a restore, entries above the restored maximum are
re-applied idempotently before the service becomes ready. The journal store, restore_epochs
table, and readiness integration follow specifications 019 and 020; this module defines the
chain, the re-application plan, and the readiness gate.
"""

import hashlib
import hmac
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

GENESIS = "0" * 64


@dataclass(frozen=True)
class JournalEntry:
    seq: int
    kind: Literal["tombstone", "consent_withdrawal"]
    reference: UUID
    digest: str
    chain: str


class JournalTampered(ValueError):
    pass


def _chain(key: bytes, previous: str, seq: int, kind: str, reference: UUID, digest: str) -> str:
    message = "\0".join((previous, str(seq), kind, str(reference), digest)).encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


# Append one entry, chained to the last entry (or the genesis value) of a verified journal.
def append(
    key: bytes,
    entries: Sequence[JournalEntry],
    kind: Literal["tombstone", "consent_withdrawal"],
    reference: UUID,
    digest: str,
) -> JournalEntry:
    previous = entries[-1] if entries else None
    seq = previous.seq + 1 if previous else 1
    chain = _chain(key, previous.chain if previous else GENESIS, seq, kind, reference, digest)
    return JournalEntry(seq, kind, reference, digest, chain)


# Raise JournalTampered on a sequence gap, reordering, or any changed entry.
def verify(key: bytes, entries: Sequence[JournalEntry]) -> None:
    previous = GENESIS
    for expected, entry in enumerate(entries, start=1):
        if entry.seq != expected:
            raise JournalTampered("journal_sequence_gap")
        if not hmac.compare_digest(
            entry.chain, _chain(key, previous, entry.seq, entry.kind, entry.reference, entry.digest)
        ):
            raise JournalTampered("journal_chain_mismatch")
        previous = entry.chain


# Entries the restored database lacks: everything after its highest recorded sequence.
def to_reapply(
    key: bytes, entries: Sequence[JournalEntry], restored_max_seq: int
) -> list[JournalEntry]:
    verify(key, entries)
    return [entry for entry in entries if entry.seq > restored_max_seq]


# Re-apply entries idempotently: entries already applied are skipped, so a repeated or
# resumed reconciliation produces the same state. Returns applied and skipped counts.
def reconcile(
    entries: Sequence[JournalEntry],
    applied: Callable[[JournalEntry], bool],
    apply: Callable[[JournalEntry], None],
) -> dict[str, int]:
    counts = {"applied": 0, "skipped": 0}
    for entry in entries:
        if applied(entry):
            counts["skipped"] += 1
        else:
            apply(entry)
            counts["applied"] += 1
    return counts


# Readiness gate: not ready while the latest restore epoch is unreconciled or the live
# cluster fingerprint differs from the recorded one. None means ready.
def readiness_failure(
    latest_epoch_reconciled: bool | None, fingerprint_matches: bool
) -> str | None:
    if latest_epoch_reconciled is False or not fingerprint_matches:
        return "restore_reconciliation_pending"
    return None
