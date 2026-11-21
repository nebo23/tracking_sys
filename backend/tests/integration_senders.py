"""Synthetic Cal.com and signed webhook senders for tests (specification 015-D, D-068 E13).

Cal.com bodies follow the documented webhook structure (second-round entry review W-1 to W-4):
the envelope with triggerEvent and createdAt, and the booking in payload (MEETING_ENDED flat),
including the attendee, answer, note and meeting link fields that must be discarded. They are
signed with HMAC-SHA256 of the raw body under a test secret, sent in x-cal-signature-256. The
signed webhook bodies follow the project's documented contract and the 004 signature scheme.
Every value is synthetic. Nothing here opens a network connection or calls a provider.
"""

import hashlib
import hmac
import json
import time
from itertools import count
from typing import Any

from app.collection.contract import sign_webhook

CALCOM_SECRET = "SYNTHETIC-CALCOM-SECRET-0001"
OTHER_CALCOM_SECRET = "SYNTHETIC-CALCOM-SECRET-0002"
ATTENDEE_NAME = "Synthetic Attendee"
ATTENDEE_EMAIL = "synthetic.attendee@example.test"
ATTENDEE_PHONE = "+201000000742"
NOTE = "Synthetic private note 742"
MEETING_URL = "https://video.example.test/meeting-742"
ANSWER = "Synthetic answer 742"
FORBIDDEN = (ATTENDEE_NAME, ATTENDEE_EMAIL, ATTENDEE_PHONE, NOTE, MEETING_URL, ANSWER)
_uids = count(1)


def uid() -> str:
    return f"syn-booking-{next(_uids):04d}"


def calcom(
    trigger: str,
    ref: str,
    *,
    created_at: str = "2026-11-10T09:00:00.000Z",
    previous: str | None = None,
    start: str = "2026-11-12T10:00:00Z",
    end: str = "2026-11-12T10:30:00Z",
    subject_token: str | None = None,
    event_type: int = 501,
) -> dict[str, Any]:
    responses: dict[str, Any] = {
        "name": {"label": "your_name", "value": ATTENDEE_NAME},
        "email": {"label": "email_address", "value": ATTENDEE_EMAIL},
        "notes": {"label": "additional_notes", "value": ANSWER},
    }
    if subject_token is not None:
        responses["ts_subject"] = {"label": "ts_subject", "value": subject_token, "isHidden": True}
    booking = {
        "title": "Synthetic Session",
        "startTime": start,
        "endTime": end,
        "additionalNotes": NOTE,
        "eventTypeId": event_type,
        "attendees": [{"name": ATTENDEE_NAME, "email": ATTENDEE_EMAIL, "timeZone": "Africa/Cairo"}],
        "attendeePhoneNumber": ATTENDEE_PHONE,
        "responses": responses,
        "uid": ref,
        "bookingId": 100,
        "metadata": {"videoCallUrl": MEETING_URL},
        "videoCallData": {"url": MEETING_URL, "password": "synthetic"},
        "status": "ACCEPTED",
    }
    if previous is not None:
        booking["rescheduleUid"] = previous
    if trigger == "MEETING_ENDED":
        return {"triggerEvent": trigger, "createdAt": created_at, **booking}
    return {"triggerEvent": trigger, "createdAt": created_at, "payload": booking}


def signed_calcom(body: dict[str, Any], secret: str = CALCOM_SECRET) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"x-cal-signature-256": signature, "content-type": "application/json"}


def booking_event(
    kind: str,
    ref: str,
    *,
    occurred_at: str = "2026-11-10T09:00:00Z",
    previous: str | None = None,
    subject_token: str | None = None,
) -> dict[str, Any]:
    booking: dict[str, Any] = {
        "id": ref,
        "event_type": "discovery-call",
        "start_at": "2026-11-12T10:00:00Z",
        "end_at": "2026-11-12T10:30:00Z",
    }
    if previous is not None:
        booking["previous_id"] = previous
    if subject_token is not None:
        booking["subject_token"] = subject_token
    return {
        "type": f"booking.{kind}",
        "id": f"evt-{ref}-{kind}",
        "occurred_at": occurred_at,
        "booking": booking,
    }


def deal_event(
    deal: str,
    stage: str,
    *,
    occurred_at: str = "2026-11-10T09:00:00Z",
    pipeline: str = "sales",
    previous: str | None = None,
    amount: str | None = None,
    currency: str | None = None,
    payment_reference: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"id": deal, "pipeline": pipeline, "stage": stage}
    if previous is not None:
        item["previous_stage"] = previous
    if amount is not None:
        item["amount"], item["currency"] = amount, currency
    if payment_reference is not None:
        item["payment_reference"] = payment_reference
    return {
        "type": "deal.stage_changed",
        "id": f"evt-{deal}-{stage}",
        "occurred_at": occurred_at,
        "deal": item,
    }


def signed_contract(body: dict[str, Any], secret: str, at: int | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    moment = int(time.time()) if at is None else at
    header = f"t={moment},v1={sign_webhook(secret, moment, raw)}"
    return raw, {"x-tracking-signature": header, "content-type": "application/json"}
