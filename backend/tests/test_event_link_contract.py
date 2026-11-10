"""EventEnvelope link reference compatibility (specification 005-C, D-033)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.collection.contract import Envelope, fingerprint

OCCURRED = datetime(2026, 11, 10, 12, 30, 0, 123456, tzinfo=UTC)
SUBJECT = UUID("00000000-0000-4000-8000-000000000010")
LINK = UUID("00000000-0000-4000-8000-000000000123")
PAGE = {"url": "https://shop.example.test/offer?utm_source=demo"}
FORM = {
    "url": "https://shop.example.test/f",
    "form_key": "lead",
    "fields": {"plan": "pro", "qty": 2},
}
# Computed with the unmodified specification 004 fingerprint (merged main e8ef587) before the
# 005 change. Events stored before 005 carry these values; absent link references must keep them.
GOLDEN_PAGE = "3b9cd58bdb1f09e731d91f142dcce70981853eaab89905ef9c3c12a85ac6a65b"
GOLDEN_FORM = "f6b043b2f9e338a4e1e8a3b8b2e382163995a1d7c64c486ef3fa2e369a820d01"


def test_absent_link_reference_keeps_pre_005_fingerprints():
    assert fingerprint("page_view", OCCURRED, SUBJECT, PAGE, False) == GOLDEN_PAGE
    assert fingerprint("page_view", OCCURRED, SUBJECT, PAGE, False, None) == GOLDEN_PAGE
    assert fingerprint("form_submit", OCCURRED, SUBJECT, FORM, False) == GOLDEN_FORM


def test_a_present_link_reference_is_part_of_the_content():
    linked = fingerprint("page_view", OCCURRED, SUBJECT, PAGE, False, LINK)
    other = fingerprint(
        "page_view", OCCURRED, SUBJECT, PAGE, False, UUID("00000000-0000-4000-8000-000000000124")
    )
    assert len({GOLDEN_PAGE, linked, other}) == 3
    assert fingerprint("page_view", OCCURRED, SUBJECT, PAGE, False, LINK) == linked


def test_old_envelopes_parse_unchanged_and_link_ids_are_strict():
    base = {
        "schema_version": 1,
        "event_id": "00000000-0000-4000-8000-000000000001",
        "event_type": "page_view",
        "occurred_at": OCCURRED.isoformat(),
        "subject_token": "sbj_" + "a" * 43,
        "payload": PAGE,
    }
    assert Envelope.model_validate(base).link_id is None
    assert Envelope.model_validate({**base, "link_id": str(LINK)}).link_id == LINK
    for bad in ("not-a-uuid", 7, ""):
        with pytest.raises(ValidationError):
            Envelope.model_validate({**base, "link_id": bad})
    with pytest.raises(ValidationError):
        Envelope.model_validate({**base, "ts_link": str(LINK)})
