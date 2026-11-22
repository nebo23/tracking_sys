"""Paymob verification, minimization and mapping without a database (specification 015-B).

D-067 decisions D4 to D7 with amendment A1. The documented example of the HMAC transaction
callback page (read 2026-11-21) fixes the concatenated string; the synthetic sender of
tests/paymob_callbacks.py signs every other case. No case opens a network connection.
"""

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from paymob_callbacks import (
    FORBIDDEN,
    LIVE_INTEGRATION,
    OTHER_SECRET,
    TEST_INTEGRATION,
    TEST_SECRET,
    authorization,
    capture,
    refund,
    resent_parent,
    sale,
    signed,
    token,
    transaction,
    void,
)

from app.ledger import EvidenceClass, OperationKind
from app.payments.paymob import (
    TRANSACTION_FIELDS,
    Unverifiable,
    effective_time,
    map_transaction,
    minimize,
    same_order,
    signed_order,
    signed_string,
    verify,
)
from app.privacy import providers
from app.services.payments import paymob_allowed


def _documented_sample():
    # The values of Paymob's documented processed-callback sample that enter the signature.
    return {
        "amount_cents": 100000,
        "created_at": "2024-06-13T11:33:44.592345",
        "currency": "EGP",
        "error_occured": False,
        "has_parent_transaction": False,
        "id": 192036465,
        "integration_id": 4097558,
        "is_3d_secure": True,
        "is_auth": False,
        "is_capture": False,
        "is_refunded": False,
        "is_standalone_payment": True,
        "is_voided": False,
        "order": {"id": 217503754},
        "owner": 302852,
        "pending": False,
        "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
        "success": True,
    }


def test_documented_hmac_string():
    # T-10: the documented field order and formatting reproduce the documented example string.
    assert signed_string(_documented_sample(), TRANSACTION_FIELDS) == (
        "1000002024-06-13T11:33:44.592345EGPfalsefalse1920364654097558truefalsefalsefalsetrue"
        "false217503754302852false2346MasterCardcardtrue"
    )


def test_verify_accepts_current_and_previous_secrets_only():
    body, query = signed(sale())
    assert verify(body, query["hmac"], [TEST_SECRET]).kind == "TRANSACTION"
    assert verify(body, query["hmac"].upper(), [OTHER_SECRET, TEST_SECRET]).kind == "TRANSACTION"
    for secrets in ([OTHER_SECRET], []):
        with pytest.raises(Unverifiable):
            verify(body, query["hmac"], secrets)
    for received in (None, "", "ab" * 63, "zz" * 64):
        with pytest.raises(Unverifiable):
            verify(body, received, [TEST_SECRET])


def test_verify_refuses_altered_fields_and_unsupported_bodies():
    obj = sale()
    body, query = signed(obj)
    for field, value in (("amount_cents", 1), ("success", False), ("currency", "USD")):
        altered = dict(obj, **{field: value})
        with pytest.raises(Unverifiable):
            verify(signed(altered)[0], query["hmac"], [TEST_SECRET])
    for raw in (b"", b"[]", b'{"type": "TRANSACTION"}', b'{"type": "OTHER", "obj": {}}', b"\xff"):
        with pytest.raises(Unverifiable):
            verify(raw, query["hmac"], [TEST_SECRET])
    missing = dict(obj)
    del missing["owner"]
    with pytest.raises(Unverifiable):
        verify(signed(missing)[0], query["hmac"], [TEST_SECRET])
    floating = json.dumps({"type": "TRANSACTION", "obj": dict(obj, amount_cents=100000.0)})
    with pytest.raises(Unverifiable):
        verify(floating.encode(), query["hmac"], [TEST_SECRET])


def test_live_integration_declaration_is_validated_before_use():
    # D-070, second review: element types are checked before the set is built, so mixed or
    # unhashable lists are validation errors; duplicates collapse and the order is sorted.
    from app.services.payments import _live_integrations

    assert _live_integrations([5_000_001, LIVE_INTEGRATION, 5_000_001]) == [
        LIVE_INTEGRATION,
        5_000_001,
    ]
    for values in ([1, "2"], [[1]], [{}], [1, None], [True], [0], [2**63], [], list(range(1, 22))):
        with pytest.raises(ValueError):
            _live_integrations(values)
    for values in ("4097558", b"1", None, 7, {1}):
        with pytest.raises(ValueError):
            _live_integrations(values)


@pytest.mark.parametrize("kind", [[], ["TRANSACTION"], {}, {"a": 1}, None, 1, 1.5, True, "token"])
def test_malformed_type_is_unverifiable_not_an_error(kind):
    # R005: a list or object type is unhashable; every malformed discriminator is refused as
    # unverifiable before the signature check, with any signature, valid or not.
    obj = sale()
    _, query = signed(obj)
    body = json.dumps({"type": kind, "obj": obj}).encode()
    for received in (query["hmac"], "0" * 128):
        with pytest.raises(Unverifiable, match="unsupported_type"):
            verify(body, received, [TEST_SECRET])


def test_card_token_callback_is_verified_and_carries_nothing():
    body, query = signed(token(), kind="TOKEN")
    result = verify(body, query["hmac"], [TEST_SECRET])
    assert result.kind == "TOKEN" and result.transaction is None
    assert not any(value in repr(result) for value in FORBIDDEN)


def test_minimize_keeps_only_allowed_fields():
    # T-16: nothing of the card, billing, shipping, customer, items or token survives.
    kept = minimize(sale())
    assert set(kept) == {
        "id",
        "amount_cents",
        "currency",
        "created_at",
        "success",
        "pending",
        "error_occured",
        "is_auth",
        "is_capture",
        "is_standalone_payment",
        "has_parent_transaction",
        "is_refund",
        "is_void",
        "is_live",
        "parent_transaction",
        "integration_id",
        "order_id",
    }
    assert not any(value in repr(kept) for value in FORBIDDEN)


def _map(obj, live=(LIVE_INTEGRATION,)):
    return map_transaction(minimize(obj), "egypt", live_integrations=frozenset(live))


def test_mapping_table():
    # T-14 (M) and A1: each state follows D5.
    paid = sale(id=1001)
    posted = _map(paid)
    assert posted.outcome == "stored" and posted.posting is not None
    assert posted.posting.kind is OperationKind.SALE
    assert posted.posting.classification is EvidenceClass.CONFIRMED_CAPTURE
    assert posted.posting.operation_id == "1001" and posted.posting.amount.minor == 100_000
    assert posted.posting.source_account_id == "paymob-egypt"
    assert posted.posting.source_reference == f"paymob:{LIVE_INTEGRATION}:{paid['order']['id']}"
    captured = _map(capture(1002, 40_000, id=1003))
    assert captured.posting.kind is OperationKind.SALE and captured.posting.operation_id == "1003"
    partial = _map(refund(1001, 25_000, id=1004)).posting
    assert partial.kind is OperationKind.REFUND and partial.parent_operation_id == "1001"
    assert partial.classification is EvidenceClass.CONFIRMED_ADJUSTMENT and partial.reason is None
    voided = _map(void(1001, 100_000, id=1005)).posting
    assert voided.kind is OperationKind.REFUND and voided.reason == "void"
    assert (_map(authorization()).outcome, _map(authorization()).reason) == (
        "not_posted",
        "authorization",
    )
    assert _map(sale(success=False)).reason == "failed"
    assert _map(sale(error_occured=True)).reason == "failed"
    assert _map(sale(pending=True)).reason == "pending"
    assert _map(sale(is_live=False)).outcome == "test_mode"
    assert _map(refund(1001, 10, is_live=False)).outcome == "test_mode"


def test_only_a_declared_live_integration_posts():
    # R001 (D-070): is_live is unsigned, so the signed integration_id decides. Paymob uses
    # separate integration IDs in test mode; flipping is_live on a test transaction changes
    # nothing that is signed, and the integration stays undeclared.
    tampered = sale(is_live=False)
    assert tampered["integration_id"] == TEST_INTEGRATION
    tampered["is_live"] = True
    mapped = _map(tampered)
    assert (mapped.outcome, mapped.reason) == ("test_mode", "undeclared_integration")
    # A live transaction of an integration the merchant did not declare posts nothing either.
    other = sale(integration_id=5_000_001)
    assert (_map(other).outcome, _map(other).reason) == ("test_mode", "undeclared_integration")
    assert _map(other, live=(LIVE_INTEGRATION, 5_000_001)).outcome == "stored"
    # A declared integration with is_live false is still test mode (A1), and no declaration at
    # all posts nothing.
    assert _map(sale(is_live=False, integration_id=LIVE_INTEGRATION)).reason is None
    assert _map(sale(is_live=False, integration_id=LIVE_INTEGRATION)).outcome == "test_mode"
    assert _map(sale(), live=()).reason == "undeclared_integration"
    # A missing or malformed integration ID is never declared.
    for value in (None, 0, -1, True, "4097558x", 4097558.0):
        broken = dict(minimize(sale()), integration_id=value)
        mapped = map_transaction(broken, "egypt", live_integrations={LIVE_INTEGRATION})
        assert (mapped.outcome, mapped.reason) == ("test_mode", "undeclared_integration"), value
    # A numeric string of a declared ID is the same signed text and posts.
    text = dict(minimize(sale()), integration_id=str(LIVE_INTEGRATION))
    assert map_transaction(text, "egypt", live_integrations={LIVE_INTEGRATION}).posting


def test_refund_and_sale_share_the_signed_order():
    # R001 (D-070): parent_transaction is unsigned, the order ID is signed in both callbacks.
    first, second = sale(), sale()
    assert first["order"]["id"] != second["order"]["id"]
    returned = refund(first["id"], 10_000)
    assert returned["order"]["id"] == first["order"]["id"]
    sale_ref = _map(first).posting.source_reference
    refund_ref = _map(returned).posting.source_reference
    assert signed_order(refund_ref) == str(first["order"]["id"])
    assert same_order(refund_ref, sale_ref)
    assert not same_order(refund_ref, _map(second).posting.source_reference)
    # An unknown or malformed order never binds, not even to another unknown order.
    unknown = _map(dict(sale(), order={"id": None})).posting.source_reference
    assert unknown.endswith(":unknown") and signed_order(unknown) is None
    assert not same_order(unknown, unknown)
    for reference in (None, "", "declaration:1", "paymob:1", "paymob:1:0", "paymob:1:x"):
        assert signed_order(reference) is None, reference


@pytest.mark.parametrize(
    ("obj", "reason"),
    [
        (transaction(is_standalone_payment=False), "unsupported_state"),
        (transaction(is_refund=True), "unsupported_state"),  # a refund flag without a parent
        (refund(1001, 10, is_void=True), "unsupported_state"),  # both refund and void
        (transaction(parent=1001, is_standalone_payment=False), "unsupported_state"),
        (refund(1001, 10, is_capture=True), "unsupported_state"),
        (refund(0, 10), "invalid_parent"),
        (sale(amount_cents=0), "invalid_amount"),
        (sale(currency="OMR"), "unsupported_currency"),
        (sale(currency="JPY"), "unsupported_currency"),
        (sale(created_at="yesterday"), "invalid_time"),
    ],
)
def test_unmapped_states(obj, reason):
    # T-15: a state the rules do not cover posts nothing and is counted, never guessed.
    mapped = _map(obj)
    assert (mapped.outcome, mapped.reason, mapped.posting) == ("unmapped", reason, None)


def test_refund_parent_must_differ_from_operation():
    assert _map(refund(2001, 10, id=2001)).reason == "invalid_parent"


def test_parent_resent_after_refund_or_void_repeats_its_delivery():
    # V-4: the parent's re-sent callback maps to the same sale and delivery ID.
    paid = sale(id=3001)
    first = _map(paid).posting
    assert _map(resent_parent(paid, refunded=25_000)).posting == first
    assert _map(resent_parent(paid, voided=True)).posting == first
    changed = _map(dict(paid, amount_cents=90_000)).posting
    assert changed.operation_id == first.operation_id
    assert changed.delivery_id != first.delivery_id


def test_effective_time_uses_offset_or_cairo_local_time():
    # V-7: no offset means Cairo local time (UTC+3 under summer time, UTC+2 in winter).
    assert effective_time("2024-06-13T11:33:44.592345", "egypt") == datetime(
        2024, 6, 13, 8, 33, 44, 592345, tzinfo=UTC
    )
    assert effective_time("2026-11-10T11:33:44", "egypt") == datetime(
        2026, 11, 10, 9, 33, 44, tzinfo=UTC
    )
    assert effective_time("2024-06-25T15:16:25.910710+04:00", "egypt") == datetime(
        2024, 6, 25, 11, 16, 25, 910710, tzinfo=UTC
    )
    # The repeated hour at the end of Cairo summer time resolves to its first occurrence.
    assert effective_time("2026-10-29T23:30:00", "egypt") == datetime(
        2026, 10, 29, 20, 30, tzinfo=UTC
    )
    for value in (None, 1, "", "not a time", "2026-13-01T00:00:00"):
        assert effective_time(value, "egypt") is None


def test_rules_gate(settings, monkeypatch):
    # T-20 (M), D12: the Paymob source type is off by default and needs both current rules.
    today = date(2026, 11, 21)
    assert settings.payments_paymob_enabled is False
    assert not paymob_allowed(settings, today)
    enabled = settings.model_copy(update={"payments_paymob_enabled": True})
    assert paymob_allowed(enabled, today)
    assert paymob_allowed(enabled, date(2027, 11, 21))
    assert not paymob_allowed(enabled, date(2027, 11, 22))  # past the review date
    for rule_id in ("payments.processor_records", "paymob.accept"):
        stale = tuple(
            replace(item, status=providers.RuleStatus.STALE) if item.rule_id == rule_id else item
            for item in providers.RULES
        )
        with monkeypatch.context() as patched:
            patched.setattr(providers, "RULES", stale)
            assert not paymob_allowed(enabled, today), rule_id
    for rule_id in ("payments.processor_records", "paymob.accept"):
        item = providers.rule(rule_id)
        assert item.status is providers.RuleStatus.CURRENT and item.data_class == "revenue.evidence"
        assert (item.verified_at, item.review_due_at) == (today, date(2027, 11, 21))


def test_deeply_nested_body_cannot_be_verified():
    # A body nested beyond the decoder's depth is unverifiable (401), never a server error.
    nested = b'{"type": "TRANSACTION", "obj": ' + b"[" * 60_000 + b"]" * 60_000 + b"}"
    with pytest.raises(Unverifiable):
        verify(nested, "ab" * 64, [TEST_SECRET])
