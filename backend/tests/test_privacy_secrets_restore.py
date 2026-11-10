"""Token envelope encryption (003-C), provider rules (003-C), and restore journal (003-D)."""

import base64
import secrets
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag

from app.privacy import providers
from app.privacy.consent import Decision
from app.privacy.restore import (
    EMPTY_HEAD,
    GENESIS,
    JournalHead,
    JournalIncomplete,
    JournalTampered,
    RestoreState,
    append,
    readiness_failure,
    reconcile,
    to_reapply,
    verify,
)
from app.privacy.token_secrets import (
    LocalKeyring,
    SecretContext,
    SecretStatus,
    TokenSecretReference,
    open_secret,
    rewrap,
    seal,
)

TOKEN = "synthetic-token-" + "x" * 1200


def context(**changes):
    base = SecretContext(uuid4(), uuid4(), uuid4(), uuid4(), "refresh_token", 1)
    return replace(base, **changes)


def keyring(*ids, active=None):
    keys = {kek_id: secrets.token_bytes(32) for kek_id in ids}
    return LocalKeyring(keys, active or ids[0])


def test_sealed_tokens_round_trip_and_hide_material():
    ring, item = keyring("kek-1"), context()
    sealed = seal(ring, TOKEN, item)
    assert open_secret(ring, sealed, item) == TOKEN
    assert TOKEN.encode() not in sealed.ciphertext
    assert "x" * 20 not in repr(sealed) and "kek-1" in repr(sealed)
    assert sealed.nonce != seal(ring, TOKEN, item).nonce


@pytest.mark.parametrize(
    "field", ["agency_id", "client_id", "connector_id", "secret_id", "kind", "version"]
)
def test_a_ciphertext_moved_to_another_row_or_tenant_fails(field):
    ring, item = keyring("kek-1"), context()
    sealed = seal(ring, TOKEN, item)
    changed = {
        "kind": "access_token",
        "version": 2,
    }.get(field, uuid4())
    with pytest.raises(InvalidTag):
        open_secret(ring, sealed, replace(item, **{field: changed}))


def test_swapped_wrapped_keys_fail():
    ring, first, second = keyring("kek-1"), context(), context()
    a, b = seal(ring, TOKEN, first), seal(ring, "other", second)
    with pytest.raises(InvalidTag):
        open_secret(ring, replace(a, wrapped_dek=b.wrapped_dek, wrap_nonce=b.wrap_nonce), first)


def test_rotation_rewraps_without_touching_the_token_ciphertext():
    old_key = secrets.token_bytes(32)
    item = context()
    sealed = seal(LocalKeyring({"kek-1": old_key}, "kek-1"), TOKEN, item)
    rotated_ring = LocalKeyring({"kek-1": old_key, "kek-2": secrets.token_bytes(32)}, "kek-2")
    rotated = rewrap(rotated_ring, sealed, item)
    assert (rotated.kek_id, rotated.ciphertext, rotated.nonce) == (
        "kek-2",
        sealed.ciphertext,
        sealed.nonce,
    )
    retired = LocalKeyring({"kek-2": rotated_ring.key("kek-2")}, "kek-2")
    assert open_secret(retired, rotated, item) == TOKEN
    with pytest.raises(KeyError):
        open_secret(retired, sealed, item)


def test_keyring_parsing_and_production_refusal():
    encoded = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    ring = LocalKeyring.from_text(f"kek-1:{encoded}", "kek-1")
    assert ring.active == "kek-1" and encoded not in repr(ring)
    with pytest.raises(ValueError):
        LocalKeyring.from_text(f"kek-1:{encoded}", "kek-1", environment="production")
    with pytest.raises(ValueError):
        LocalKeyring({"kek-1": b"short"}, "kek-1")
    with pytest.raises(ValueError):
        LocalKeyring({"kek-1": secrets.token_bytes(32)}, "kek-2")


def test_destroying_a_reference_removes_the_ciphertext():
    ring, item = keyring("kek-1"), context()
    now = datetime(2030, 1, 1, tzinfo=UTC)
    reference = TokenSecretReference(item, SecretStatus.ACTIVE, now, seal(ring, TOKEN, item))
    gone = reference.destroyed(now)
    assert (gone.status, gone.sealed, gone.destroyed_at) == (SecretStatus.DESTROYED, None, now)


def test_connector_rules_block_their_features_until_reverified():
    today = date(2026, 11, 4)
    connector_rules = [rule for rule in providers.RULES if rule.provider != "google"]
    assert len(connector_rules) == 11
    assert all(
        providers.feature_allowed(rule, today) == Decision(False, "rule_stale")
        for rule in connector_rules
    )
    current = providers.rule("google.sign_in")
    assert providers.feature_allowed(current, today) == Decision(True, "rule_current")
    overdue = replace(current, review_due_at=date(2026, 11, 3))
    assert providers.feature_allowed(overdue, today) == Decision(False, "rule_review_overdue")
    unsupported = replace(current, status=providers.RuleStatus.UNSUPPORTED)
    assert providers.feature_allowed(unsupported, today) == Decision(False, "rule_unsupported")
    assert len({rule.rule_id for rule in providers.RULES}) == len(providers.RULES)


def journal(key, count):
    entries = []
    for index in range(count):
        kind = "tombstone" if index % 2 == 0 else "consent_withdrawal"
        entries.append(append(key, entries, kind, uuid4(), f"{index:064x}"))
    return entries


# The head the journal writer recorded after its last append. Tests take it from the complete
# journal, standing in for the independent checkpoint custody of specifications 019 and 020.
def head(entries):
    return JournalHead(entries[-1].seq, entries[-1].chain) if entries else EMPTY_HEAD


def test_r2_entries_after_the_restore_point_are_reapplied():
    key = secrets.token_bytes(32)
    entries = journal(key, 5)
    pending = to_reapply(key, entries, restored_max_seq=3, expected_head=head(entries))
    assert [entry.seq for entry in pending] == [4, 5]


def test_r4_reconciliation_is_idempotent():
    key, applied = secrets.token_bytes(32), set()
    full = journal(key, 4)
    entries = to_reapply(key, full, restored_max_seq=0, expected_head=head(full))

    def run():
        return reconcile(entries, lambda e: e.seq in applied, lambda e: applied.add(e.seq))

    assert run() == {"applied": 4, "skipped": 0}
    assert run() == {"applied": 0, "skipped": 4}


# Review finding R003-03: an authentic but truncated journal was accepted as complete.
@pytest.mark.parametrize(
    ("supplied", "restored_max_seq", "reason"),
    [
        (2, 3, "journal_shorter_than_watermark"),  # the reviewed reproduction
        (0, 2, "journal_shorter_than_watermark"),  # empty journal, nonzero watermark
        (3, 3, "journal_missing_suffix"),  # reaches the watermark; entry 4 is missing
        (3, 1, "journal_missing_suffix"),  # passes the watermark; entry 4 is missing
        (0, 0, "journal_missing_suffix"),  # nothing supplied for a nonempty journal
    ],
)
def test_truncated_journals_are_rejected_against_the_trusted_head(
    supplied, restored_max_seq, reason
):
    key = secrets.token_bytes(32)
    full = journal(key, 4)
    with pytest.raises(JournalIncomplete, match=reason):
        to_reapply(key, full[:supplied], restored_max_seq, expected_head=head(full))
    # A consumer written to block on tampering also blocks on an incomplete journal.
    with pytest.raises(JournalTampered):
        to_reapply(key, full[:supplied], restored_max_seq, expected_head=head(full))


def test_head_and_chain_mismatches_are_rejected():
    key = secrets.token_bytes(32)
    full = journal(key, 4)
    forked = journal(key, 4)  # same key and length, different entries
    with pytest.raises(JournalTampered, match="journal_head_mismatch"):
        to_reapply(key, full, 2, expected_head=head(forked))
    # A head older than the supplied entries, or than the restored watermark, is stale.
    with pytest.raises(JournalIncomplete, match="journal_head_stale"):
        to_reapply(key, full, 2, expected_head=head(full[:3]))
    with pytest.raises(JournalIncomplete, match="journal_head_stale"):
        to_reapply(key, full[:3], 3, expected_head=head(full[:2]))
    with pytest.raises(JournalIncomplete, match="journal_head_stale"):
        to_reapply(key, [], 1, expected_head=EMPTY_HEAD)
    # The trusted head does not excuse a broken chain or another key.
    changed = [*full[:1], replace(full[1], digest="f" * 64), *full[2:]]
    with pytest.raises(JournalTampered, match="journal_chain_mismatch"):
        to_reapply(key, changed, 0, expected_head=head(full))
    with pytest.raises(JournalTampered, match="journal_chain_mismatch"):
        to_reapply(secrets.token_bytes(32), full, 0, expected_head=head(full))


def test_completeness_evidence_is_required():
    key = secrets.token_bytes(32)
    full = journal(key, 3)
    with pytest.raises(TypeError):
        to_reapply(key, full, 0)  # the unsafe call form is no longer accepted
    for missing in (None, (3, full[-1].chain), full[-1]):
        with pytest.raises(JournalIncomplete, match="journal_head_required"):
            to_reapply(key, full, 0, expected_head=missing)


@pytest.mark.parametrize("watermark", [-1, True, False, 1.0, "1", None])
def test_invalid_restored_watermarks_are_rejected(watermark):
    key = secrets.token_bytes(32)
    full = journal(key, 3)
    with pytest.raises(ValueError, match="invalid_restored_watermark"):
        to_reapply(key, full, watermark, expected_head=head(full))


@pytest.mark.parametrize(
    ("seq", "chain"),
    [
        (-1, "a" * 64),
        (True, "a" * 64),
        (1.0, "a" * 64),
        (1, "a" * 63),
        (1, "A" * 64),
        (1, "g" * 64),
        (1, None),
        (1, GENESIS),  # GENESIS stands only for the empty journal
        (0, "a" * 64),
    ],
)
def test_invalid_journal_heads_are_rejected(seq, chain):
    with pytest.raises(ValueError, match="invalid_journal_head"):
        JournalHead(seq, chain)


def test_empty_journal_recovers_with_the_trusted_empty_head():
    key = secrets.token_bytes(32)
    assert to_reapply(key, [], 0, expected_head=EMPTY_HEAD) == []
    assert EMPTY_HEAD == JournalHead(0, GENESIS)


def test_repeated_recovery_of_a_complete_journal_is_idempotent():
    key, applied = secrets.token_bytes(32), set()
    full = journal(key, 5)
    trusted = head(full)
    plan = to_reapply(key, full, 3, expected_head=trusted)
    assert [entry.seq for entry in plan] == [4, 5]
    assert to_reapply(key, full, 3, expected_head=trusted) == plan
    # A restored database that already holds every entry needs nothing reapplied.
    assert to_reapply(key, full, 5, expected_head=trusted) == []

    def run(entries):
        return reconcile(entries, lambda e: e.seq in applied, lambda e: applied.add(e.seq))

    assert run(plan) == {"applied": 2, "skipped": 0}
    assert run(to_reapply(key, full, 3, expected_head=trusted)) == {"applied": 0, "skipped": 2}
    assert applied == {4, 5}


def test_a_failed_reapplication_does_not_complete_reconciliation():
    key, applied, failing = secrets.token_bytes(32), set(), [True]
    full = journal(key, 3)
    plan = to_reapply(key, full, 0, expected_head=head(full))

    def apply(entry):
        if entry.seq == 2 and failing[0]:
            raise RuntimeError("synthetic apply failure")
        applied.add(entry.seq)

    with pytest.raises(RuntimeError):
        reconcile(plan, lambda e: e.seq in applied, apply)
    # No counts were returned, so the epoch cannot be recorded as reconciled and stays blocked.
    assert applied == {1}
    assert readiness_failure(RestoreState.RECONCILIATION_PENDING, True) == (
        "restore_reconciliation_pending"
    )
    failing[0] = False
    assert reconcile(plan, lambda e: e.seq in applied, apply) == {"applied": 2, "skipped": 1}
    assert applied == {1, 2, 3}


@pytest.mark.parametrize("tamper", ["changed", "gap", "reordered", "wrong_key"])
def test_journal_tampering_is_detected(tamper):
    key = secrets.token_bytes(32)
    entries = journal(key, 4)
    if tamper == "changed":
        entries[1] = replace(entries[1], digest="f" * 64)
    elif tamper == "gap":
        del entries[2]
    elif tamper == "reordered":
        entries[1], entries[2] = entries[2], entries[1]
    else:
        key = secrets.token_bytes(32)
    with pytest.raises(JournalTampered):
        verify(key, entries)


def test_r1_readiness_waits_for_a_verified_reconciliation():
    pending = "restore_reconciliation_pending"
    assert readiness_failure(RestoreState.NOT_RESTORED, True) is None
    assert readiness_failure(RestoreState.RECONCILED, True) is None
    assert readiness_failure(RestoreState.RECONCILIATION_PENDING, True) == pending
    assert readiness_failure(RestoreState.JOURNAL_UNVERIFIED, True) == (
        "restore_journal_unverified"
    )
    assert readiness_failure(RestoreState.RECONCILED, False) == pending
    assert readiness_failure(RestoreState.NOT_RESTORED, False) == pending
    # Values outside the contract fail closed, including the earlier None and bool inputs.
    for unknown in (None, True, False, "reconciled", "not_restored", 1):
        assert readiness_failure(unknown, True) == pending
    for fingerprint in (None, 1, "true"):
        assert readiness_failure(RestoreState.RECONCILED, fingerprint) == pending
