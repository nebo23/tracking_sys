"""R006-28 consumer protocol on disposable PostgreSQL with a persisted reference consumer.

The reference consumer (test-only tables, dropped after each test) keeps a generation, a
checkpoint and derived rows per client. Replays and rebuilds publish only through a
compare-and-swap on both the generation and the checkpoint captured at their start, and a
release compares the checkpoint with the current watermark. Two workers interleave through
hooks at the publication boundary (JV11). Synthetic values only.
"""

import secrets
from uuid import UUID

import pytest
from identity_support import make_identity_world, rows
from psycopg.errors import SerializationFailure
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import OperationalError

from app.models import IdentityChange, IdentityFeedState, IdentitySubject
from app.services.identity_feed import (
    begin_snapshot,
    current_watermark,
    read_batch,
    snapshot_watermark,
    verify,
)

pytestmark = pytest.mark.integration

TABLES = (
    "CREATE TABLE ref_identity_consumer_state (client_id uuid PRIMARY KEY, "
    "generation bigint NOT NULL, checkpoint bigint NOT NULL)",
    "CREATE TABLE ref_identity_consumer_rows (client_id uuid NOT NULL, generation bigint NOT NULL, "
    "person_id uuid NOT NULL, journey_revision bigint NOT NULL, "
    "PRIMARY KEY (client_id, generation, person_id))",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ref_identity_consumer_state, "
    "ref_identity_consumer_rows TO tracking_app",
)


@pytest.fixture
def idw(authenticated_world, api):
    return make_identity_world(authenticated_world, api)


@pytest.fixture
def consumer_tables(db):
    with db.migration.begin() as connection:
        for statement in TABLES:
            connection.execute(text(statement))
    try:
        yield
    finally:
        with db.migration.begin() as connection:
            connection.execute(text("DROP TABLE ref_identity_consumer_rows"))
            connection.execute(text("DROP TABLE ref_identity_consumer_state"))


class Consumer:
    """A synthetic per-client projection of person IDs and journey revisions."""

    def __init__(self, engine, client_id: UUID) -> None:
        self.engine, self.client_id = engine, client_id
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ref_identity_consumer_state VALUES (:c, 0, 0) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"c": client_id},
            )

    def state(self, connection) -> tuple[int, int]:
        row = connection.execute(
            text(
                "SELECT generation, checkpoint FROM ref_identity_consumer_state "
                "WHERE client_id = :c"
            ),
            {"c": self.client_id},
        ).one()
        return row.generation, row.checkpoint

    def _cas(self, connection, captured, generation, checkpoint) -> bool:
        return (
            connection.execute(
                text(
                    "UPDATE ref_identity_consumer_state SET generation = :g, checkpoint = :k "
                    "WHERE client_id = :c AND generation = :g0 AND checkpoint = :k0"
                ),
                {
                    "c": self.client_id,
                    "g": generation,
                    "k": checkpoint,
                    "g0": captured[0],
                    "k0": captured[1],
                },
            ).rowcount
            == 1
        )

    def replay(self, limit: int = 100, hook=None) -> str:
        # A serialization failure under REPEATABLE READ rejects a stale batch like a failed
        # compare-and-swap: the whole transaction, derived rows included, rolls back.
        try:
            return self._replay(limit, hook)
        except OperationalError as error:
            if not isinstance(error.orig, SerializationFailure):
                raise
            return "conflict"

    def _replay(self, limit: int, hook) -> str:
        with self.engine.connect() as connection:
            connection.begin()
            begin_snapshot(connection)
            captured = self.state(connection)
            batch = read_batch(connection, self.client_id, captured[1], limit)
            outcome = verify(batch, captured[1])
            if outcome != "apply":
                connection.rollback()
                return outcome
            if hook is not None:
                hook()  # another worker publishes after this batch was read
            for record in batch.records:
                if record.kind in {"erased", "withdrawn", "expired"}:
                    connection.execute(
                        text(
                            "DELETE FROM ref_identity_consumer_rows WHERE client_id = :c "
                            "AND generation = :g AND person_id = :p"
                        ),
                        {"c": self.client_id, "g": captured[0], "p": record.person_id},
                    )
                else:
                    connection.execute(
                        text(
                            "INSERT INTO ref_identity_consumer_rows VALUES (:c, :g, :p, :r) "
                            "ON CONFLICT (client_id, generation, person_id) "
                            "DO UPDATE SET journey_revision = EXCLUDED.journey_revision"
                        ),
                        {
                            "c": self.client_id,
                            "g": captured[0],
                            "p": record.person_id,
                            "r": record.journey_revision,
                        },
                    )
            if not self._cas(connection, captured, captured[0], batch.records[-1].seq):
                connection.rollback()
                return "conflict"
            connection.commit()
            return "applied"

    def rebuild(self, hook=None) -> str:
        with self.engine.connect() as connection:
            connection.begin()
            begin_snapshot(connection)
            captured = self.state(connection)
            watermark = snapshot_watermark(connection, self.client_id)
            people = connection.execute(
                select(IdentitySubject.id, IdentitySubject.journey_revision).where(
                    IdentitySubject.client_id == self.client_id
                )
            ).all()
            connection.rollback()
        staged = secrets.randbelow(2**62) + 1
        with self.engine.begin() as connection:
            for person_id, revision in people:
                connection.execute(
                    text("INSERT INTO ref_identity_consumer_rows VALUES (:c, :g, :p, :r)"),
                    {"c": self.client_id, "g": staged, "p": person_id, "r": revision},
                )
        if hook is not None:
            hook()
        with self.engine.connect() as connection:
            connection.begin()
            if not self._cas(connection, captured, staged, watermark):
                connection.rollback()
                with self.engine.begin() as cleanup:
                    cleanup.execute(
                        text(
                            "DELETE FROM ref_identity_consumer_rows WHERE client_id = :c "
                            "AND generation = :g"
                        ),
                        {"c": self.client_id, "g": staged},
                    )
                return "conflict"
            connection.execute(
                text(
                    "DELETE FROM ref_identity_consumer_rows WHERE client_id = :c "
                    "AND generation <> :g"
                ),
                {"c": self.client_id, "g": staged},
            )
            connection.commit()
            return "published"

    def release(self, person_id: UUID):
        with self.engine.begin() as connection:
            generation, checkpoint = self.state(connection)
            last_seq, _ = current_watermark(connection, self.client_id)
            if checkpoint < last_seq:
                return "stale"
            if (
                connection.execute(
                    select(IdentitySubject.id).where(IdentitySubject.id == person_id)
                ).first()
                is None
            ):
                return "unavailable"
            return connection.execute(
                text(
                    "SELECT journey_revision FROM ref_identity_consumer_rows WHERE client_id = :c "
                    "AND generation = :g AND person_id = :p"
                ),
                {"c": self.client_id, "g": generation, "p": person_id},
            ).scalar_one_or_none()

    def visible_generations(self) -> set[int]:
        with self.engine.begin() as connection:
            return set(
                connection.execute(
                    text(
                        "SELECT DISTINCT generation FROM ref_identity_consumer_rows "
                        "WHERE client_id = :c"
                    ),
                    {"c": self.client_id},
                ).scalars()
            )


def new_person(idw, value):
    token = idw.browser_subject()["subject_token"]
    response = idw.via_browser(token, [idw.identifier("email", value, "email_code")])
    assert response.status_code == 201, response.text
    return token


def test_rebuild_publication_needs_both_generation_and_checkpoint(idw, db, consumer_tables):
    a1 = idw.w.a1
    new_person(idw, "c1@example.test")
    worker_a, worker_b = Consumer(db.runtime, a1), Consumer(db.runtime, a1)
    assert worker_a.rebuild() == "published"
    with db.runtime.begin() as connection:
        generation, checkpoint = worker_a.state(connection)
    # B replays within the same generation while A stages: A's publication must fail.
    new_person(idw, "c2@example.test")
    outcomes = []

    def replay_in_between():
        outcomes.append(worker_b.replay())

    assert worker_a.rebuild(hook=replay_in_between) == "conflict"
    assert outcomes == ["applied"]
    with db.runtime.begin() as connection:
        after = worker_a.state(connection)
    assert after[0] == generation and after[1] > checkpoint
    assert worker_a.visible_generations() == {generation}  # staging discarded
    # B publishes another generation while A stages: A fails again.
    published = []
    assert worker_a.rebuild(hook=lambda: published.append(worker_b.rebuild())) == "conflict"
    assert published == ["published"]
    assert len(worker_a.visible_generations()) == 1


def test_concurrent_replays_commit_once(idw, db, consumer_tables):
    a1 = idw.w.a1
    new_person(idw, "r1@example.test")
    worker_a, worker_b = Consumer(db.runtime, a1), Consumer(db.runtime, a1)
    new_person(idw, "r2@example.test")
    inner = []
    assert worker_a.replay(hook=lambda: inner.append(worker_b.replay())) == "conflict"
    assert inner == ["applied"]
    assert worker_a.replay() == "caught_up"


def test_erasure_after_snapshot_is_never_released_stale(idw, db, consumer_tables):
    a1 = idw.w.a1
    new_person(idw, "gone@example.test")
    (person,) = rows(db, select(IdentitySubject.id).where(IdentitySubject.client_id == a1))
    consumer = Consumer(db.runtime, a1)

    def erase_now():
        response = idw.owner.post(
            f"{idw.base}/clients/{a1}/identity/erasures", json={"subject_id": str(person)}
        )
        assert response.status_code == 201, response.text

    assert consumer.rebuild(hook=erase_now) == "published"
    assert consumer.release(person) == "stale"  # the snapshot still holds the person
    assert consumer.replay() == "applied"
    assert consumer.release(person) == "unavailable"
    # A completely pruned feed behind the checkpoint forces a rebuild, never a skip.
    new_person(idw, "later@example.test")
    with db.migration.begin() as connection:
        last = connection.execute(
            select(IdentityFeedState.last_seq).where(IdentityFeedState.client_id == a1)
        ).scalar_one()
        connection.execute(delete(IdentityChange).where(IdentityChange.client_id == a1))
        connection.execute(
            update(IdentityFeedState)
            .where(IdentityFeedState.client_id == a1)
            .values(pruned_through_seq=last)
        )
    assert consumer.replay() == "rebuild"
    assert consumer.rebuild() == "published"
    assert consumer.replay() == "caught_up"
