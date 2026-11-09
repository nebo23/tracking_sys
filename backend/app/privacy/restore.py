"""Deletion journal and restore reconciliation contract (specification 003-D, D-025).

Point-in-time recovery loses entries written after the recovery target, so every tombstone
and consent withdrawal is also written to an independent append-only journal with monotonic
sequence numbers and an HMAC chain. After a restore, entries above the restored maximum are
re-applied idempotently before the service becomes ready. The journal store, restore_epochs
table, and readiness integration follow specifications 019 and 020; this module defines the
chain, the trusted journal head, the re-application plan, and the readiness gate.

An authentic chain proves only that the supplied entries were written in that order: a
truncated journal is still a valid chain. A recovery plan therefore also requires the trusted
journal head, the sequence number and chain value of the last entry the journal writer
appended. The head is evidence of completeness only because it does not come from the entries
being verified. Trust boundary: the writer records the new head with every append, in custody
independent of both the database being restored and the journal entry storage; the recovery
procedure stops the writer and reads the head from that custody, never computing it from the
supplied entries. Establishing that a head is authoritative and current for a given recovery
(its custody, freshness, and binding to a restore epoch) is the obligation of specifications
019 and 020. This module cannot detect a head that was rolled back together with the journal.
"""

import hashlib
import hmac
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Literal
from uuid import UUID

GENESIS = "0" * 64
_CHAIN_VALUE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class JournalEntry:
    seq: int
    kind: Literal["tombstone", "consent_withdrawal"]
    reference: UUID
    digest: str
    chain: str


# True for a journal sequence number or restored watermark: a non-negative integer, not a bool.
def _sequence_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# The trusted journal head (see the module documentation): the sequence number and chain value
# of the last appended entry, or 0 and GENESIS for an empty journal. The writer records
# JournalHead(entry.seq, entry.chain) after each append. Malformed values are rejected.
@dataclass(frozen=True)
class JournalHead:
    seq: int
    chain: str

    # Reject a negative or non-integer sequence, a chain that is not 64 lowercase hexadecimal
    # characters, and any pairing other than sequence 0 with GENESIS for the empty journal.
    def __post_init__(self) -> None:
        if (
            not _sequence_number(self.seq)
            or not isinstance(self.chain, str)
            or not _CHAIN_VALUE.fullmatch(self.chain)
            or (self.seq == 0) != (self.chain == GENESIS)
        ):
            raise ValueError("invalid_journal_head")


EMPTY_HEAD = JournalHead(0, GENESIS)


# The supplied entries are not the authentic journal: a sequence gap, reordering, changed
# entry, wrong key, or a final chain value that differs from the trusted head.
class JournalTampered(ValueError):
    pass


# Completeness of the supplied entries cannot be established: no trusted head was given, the
# entries end before the restored watermark or the trusted head, or the head is older than the
# entries or the watermark. A subclass of JournalTampered, so callers that block on tampering
# also block on an incomplete journal.
class JournalIncomplete(JournalTampered):
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


# Raise JournalTampered on a sequence gap, reordering, or any changed entry. This authenticates
# only the entries supplied; a valid prefix also passes, so recovery uses to_reapply.
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


# Entries the restored database lacks: everything after its watermark, the highest journal
# sequence it records as applied (0 for none). Nothing is returned unless the inputs are valid,
# the journal is at least as long as the watermark, the chain verifies from GENESIS, and the
# last entry is exactly the trusted head, which is required and has no default. Every failure
# raises ValueError: JournalIncomplete or JournalTampered for the journal, plain ValueError for
# a malformed watermark. Any of them must leave the restore unreconciled (JOURNAL_UNVERIFIED).
def to_reapply(
    key: bytes,
    entries: Sequence[JournalEntry],
    restored_max_seq: int,
    *,
    expected_head: JournalHead,
) -> list[JournalEntry]:
    if not isinstance(expected_head, JournalHead):
        raise JournalIncomplete("journal_head_required")
    if not _sequence_number(restored_max_seq):
        raise ValueError("invalid_restored_watermark")
    if restored_max_seq > expected_head.seq:
        raise JournalIncomplete("journal_head_stale")
    if len(entries) < restored_max_seq:
        raise JournalIncomplete("journal_shorter_than_watermark")
    verify(key, entries)
    last_seq, last_chain = (entries[-1].seq, entries[-1].chain) if entries else (0, GENESIS)
    if last_seq < expected_head.seq:
        raise JournalIncomplete("journal_missing_suffix")
    if last_seq > expected_head.seq:
        raise JournalIncomplete("journal_head_stale")
    if not hmac.compare_digest(last_chain, expected_head.chain):
        raise JournalTampered("journal_head_mismatch")
    return [entry for entry in entries if entry.seq > restored_max_seq]


# Re-apply entries idempotently: entries already applied are skipped, so a repeated or
# resumed reconciliation produces the same state. Returns applied and skipped counts only after
# every entry was handled; an exception from either callable propagates, and the restore stays
# unreconciled until a later run returns.
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


# Restore status of the latest restore epoch, as recorded by the consumer (019, 020). Only
# NOT_RESTORED and RECONCILED can be ready. RECONCILED may be recorded only after to_reapply
# returned a plan for the trusted head and reconcile returned for that whole plan.
class RestoreState(Enum):
    NOT_RESTORED = "not_restored"  # no restore epoch is recorded
    RECONCILIATION_PENDING = "reconciliation_pending"  # epoch open; reapplication unfinished
    JOURNAL_UNVERIFIED = "journal_unverified"  # completeness unknown or verification failed
    RECONCILED = "reconciled"  # a verified complete plan was fully reapplied


# Readiness gate: not ready unless no restore occurred or the latest restore was reconciled,
# and the live cluster fingerprint matches the recorded one. Any other value, including None,
# a bool, or a string, fails closed. None means ready.
def readiness_failure(state: RestoreState, fingerprint_matches: bool) -> str | None:
    if state is RestoreState.JOURNAL_UNVERIFIED:
        return "restore_journal_unverified"
    if (
        state is not RestoreState.NOT_RESTORED and state is not RestoreState.RECONCILED
    ) or fingerprint_matches is not True:
        return "restore_reconciliation_pending"
    return None
