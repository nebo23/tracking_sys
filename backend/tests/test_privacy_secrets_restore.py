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
    JournalTampered,
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


def test_r2_entries_after_the_restore_point_are_reapplied():
    key = secrets.token_bytes(32)
    entries = journal(key, 5)
    pending = to_reapply(key, entries, restored_max_seq=3)
    assert [entry.seq for entry in pending] == [4, 5]


def test_r4_reconciliation_is_idempotent():
    key, applied = secrets.token_bytes(32), set()
    entries = to_reapply(key, journal(key, 4), restored_max_seq=0)

    def run():
        return reconcile(entries, lambda e: e.seq in applied, lambda e: applied.add(e.seq))

    assert run() == {"applied": 4, "skipped": 0}
    assert run() == {"applied": 0, "skipped": 4}


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


def test_r1_readiness_waits_for_reconciliation():
    assert readiness_failure(False, True) == "restore_reconciliation_pending"
    assert readiness_failure(True, False) == "restore_reconciliation_pending"
    assert readiness_failure(None, True) is None
    assert readiness_failure(True, True) is None
