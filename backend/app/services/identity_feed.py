"""Gap-safe reads of the per-client identity change feed (design section 11.1, R006-28).

A consumer keeps per client its derived rows, their generation and a checkpoint c meaning
"every record up to c is applied to this generation". read_batch() must run inside one
REPEATABLE READ transaction: it reads the watermarks first and then the records above c in
the same snapshot. verify() refuses to apply a batch that starts after a pruned record or has
a gap, so a record removed by retention or committed while the consumer works is never
skipped. snapshot_watermark() gives a rebuild its watermark w in the same snapshot as the
source rows the consumer reads next.

Publishing is the consumer's job: a replay commits its derived changes and new checkpoint, and a
rebuild switches to its staged generation with checkpoint w, each conditional on both the
generation and the checkpoint captured at the start (compare-and-swap on the pair, R006-28).
Before releasing person-derived data, a consumer compares its checkpoint with the current
watermark (current_watermark()) and answers stale while it is behind.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import Connection, select, text

from app.models import IdentityChange, IdentityFeedState


@dataclass(frozen=True)
class FeedRecord:
    seq: int
    person_id: UUID
    kind: str
    journey_revision: int


@dataclass(frozen=True)
class FeedBatch:
    last_seq: int
    pruned_through_seq: int
    records: tuple[FeedRecord, ...]


def begin_snapshot(connection: Connection) -> None:
    """Make the caller's open transaction a REPEATABLE READ snapshot (first statement)."""
    connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))


def _watermarks(connection: Connection, client_id: UUID) -> tuple[int, int]:
    row = connection.execute(
        select(IdentityFeedState.last_seq, IdentityFeedState.pruned_through_seq).where(
            IdentityFeedState.client_id == client_id
        )
    ).one_or_none()
    return (row.last_seq, row.pruned_through_seq) if row is not None else (0, 0)


def read_batch(connection: Connection, client_id: UUID, after: int, limit: int) -> FeedBatch:
    last_seq, pruned = _watermarks(connection, client_id)
    records = tuple(
        FeedRecord(row.seq, row.person_id, row.kind, row.journey_revision)
        for row in connection.execute(
            select(
                IdentityChange.seq,
                IdentityChange.person_id,
                IdentityChange.kind,
                IdentityChange.journey_revision,
            )
            .where(IdentityChange.client_id == client_id, IdentityChange.seq > after)
            .order_by(IdentityChange.seq)
            .limit(limit)
        )
    )
    return FeedBatch(last_seq, pruned, records)


def verify(batch: FeedBatch, checkpoint: int) -> Literal["apply", "caught_up", "rebuild"]:
    if checkpoint < batch.pruned_through_seq:
        return "rebuild"
    if not batch.records:
        return "rebuild" if batch.last_seq > checkpoint else "caught_up"
    expected = checkpoint + 1
    for record in batch.records:
        if record.seq != expected:
            return "rebuild"
        expected += 1
    return "apply"


def snapshot_watermark(connection: Connection, client_id: UUID) -> int:
    return _watermarks(connection, client_id)[0]


def current_watermark(connection: Connection, client_id: UUID) -> tuple[int, int]:
    return _watermarks(connection, client_id)
