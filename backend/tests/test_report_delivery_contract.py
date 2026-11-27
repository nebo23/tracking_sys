"""Contract tests of 016-C report delivery without a database (specification 016-C, D-095).

They cover the binding of an export's seal (RV02), the stored report parameters, the run
slots and periods of schedules (RV11), the report_ready email text (RV14) and the PNG
checks of the branding logo (RV17). Every identifier and file is synthetic.
"""

import os
import zlib
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from cryptography.exceptions import InvalidTag

from app.privacy.token_secrets import (
    LocalKeyring,
    SecretContext,
    open_bytes,
    open_secret,
    seal,
    seal_bytes,
)
from app.reporting.common import ReportError
from app.reporting.periods import Period
from app.reporting.schedules import Timing
from app.services.branding import SIGNATURE, check_png
from app.services.mail import ReportReady, report_ready_message
from app.services.report_exports import query_of, stored_parameters
from app.services.reporting import ReportQuery

KEYRING = LocalKeyring({"k1": os.urandom(32)}, "k1")


def _context(agency, client, export):
    return SecretContext(agency, client, export, export, "report_export", 1)


def test_rv02_seal_is_bound_to_export_agency_and_client():
    agency, client, export = uuid4(), uuid4(), uuid4()
    data = b'"row_type","family"\r\n"metadata","social"\r\n'
    sealed = seal_bytes(KEYRING, data, _context(agency, client, export))
    assert data not in sealed.ciphertext and len(sealed.ciphertext) == len(data) + 16
    assert open_bytes(KEYRING, sealed, _context(agency, client, export)) == data
    for other in (
        _context(uuid4(), client, export),
        _context(agency, uuid4(), export),
        _context(agency, client, uuid4()),
        SecretContext(agency, client, export, export, "conversion_payload", 1),
        SecretContext(agency, client, export, export, "report_export", 2),
    ):
        with pytest.raises(InvalidTag):
            open_bytes(KEYRING, sealed, other)


def test_text_secrets_keep_their_envelope():
    context = SecretContext(uuid4(), uuid4(), uuid4(), uuid4(), "access_token", 1)
    sealed = seal(KEYRING, "synthetic-token-value", context)
    assert open_secret(KEYRING, sealed, context) == "synthetic-token-value"
    assert open_bytes(KEYRING, sealed, context) == b"synthetic-token-value"


@pytest.mark.parametrize(
    "query",
    [
        ReportQuery(
            "social",
            date(2026, 11, 1),
            date(2026, 11, 8),
            True,
            connection_id=uuid4(),
            view="daily",
            metrics=("views", "reach"),
        ),
        ReportQuery("spend", date(2026, 11, 1), date(2026, 11, 8), False, uuid4(), level="ad"),
        ReportQuery("revenue", date(2026, 11, 1), date(2026, 11, 8), True),
        ReportQuery(
            "attribution",
            date(2026, 11, 1),
            date(2026, 11, 8),
            False,
            view="models",
            group_by="link",
        ),
        ReportQuery(
            "roas",
            date(2026, 11, 1),
            date(2026, 11, 8),
            False,
            uuid4(),
            level="campaign",
            model_version=uuid4(),
        ),
        ReportQuery("funnel", date(2026, 11, 1), date(2026, 11, 8), True, group_by="content"),
    ],
)
def test_stored_parameters_rebuild_the_same_query(query):
    stored = stored_parameters(query)
    assert "start" not in stored and "family" not in stored
    assert query_of(query.family, stored, query.start, query.end) == query


def test_stored_parameters_keep_the_route_rules():
    with pytest.raises(ReportError, match="comparison_unsupported"):
        query_of(
            "social",
            {"compare": True, "view": "content_cohort"},
            date(2026, 11, 1),
            date(2026, 11, 8),
        )
    with pytest.raises(ReportError, match="invalid_period"):
        query_of("revenue", {"compare": False}, date(2026, 11, 1), date(2026, 12, 3))


def utc(*parts):
    return datetime(*parts, tzinfo=UTC)


def test_rv11_periods():
    daily = Timing("daily", None, 6, "Africa/Cairo")
    # A run exactly at its slot is the latest one at that instant; the next is a day later.
    assert daily.latest_at(utc(2026, 11, 27, 4)) == (date(2026, 11, 27), utc(2026, 11, 27, 4))
    assert daily.latest_at(utc(2026, 11, 27, 3, 59))[0] == date(2026, 11, 26)
    assert daily.next_after(utc(2026, 11, 27, 4)) == (date(2026, 11, 28), utc(2026, 11, 28, 4))
    assert daily.period(date(2026, 11, 27)) == Period(date(2026, 11, 26), date(2026, 11, 27))
    weekly = Timing("weekly", 1, 9, "Asia/Tokyo")
    day, slot = weekly.next_after(utc(2026, 11, 27))
    assert (day, slot) == (date(2026, 11, 30), utc(2026, 11, 30))
    assert day.isoweekday() == 1
    assert weekly.period(day) == Period(date(2026, 11, 23), date(2026, 11, 30))
    assert weekly.latest_at(utc(2026, 11, 29, 23, 59))[0] == date(2026, 11, 23)
    pacific = Timing("weekly", 7, 23, "America/Los_Angeles")
    day, slot = pacific.next_after(utc(2026, 11, 27))
    assert (day, slot) == (date(2026, 11, 29), utc(2026, 11, 30, 7))
    # A schedule's local date decides the period even when it is another UTC date.
    kiritimati = Timing("monthly", None, 8, "Pacific/Kiritimati")
    day, slot = kiritimati.next_after(utc(2026, 11, 30, 17))
    assert (day, slot) == (date(2026, 12, 1), utc(2026, 11, 30, 18))
    assert kiritimati.period(day) == Period(date(2026, 11, 1), date(2026, 12, 1))
    # A missed slot is not repeated: the latest slot decides, the next one follows it.
    late = utc(2026, 11, 30, 12)
    assert daily.latest_at(late)[0] == date(2026, 11, 30)
    assert daily.next_after(late)[0] == date(2026, 12, 1)


def test_rv11_daylight_saving_runs():
    new_york = Timing("daily", None, 2, "America/New_York")
    # 02:00 does not exist on 2026-03-08: the run is at the change (03:00 EDT).
    assert new_york.instant(date(2026, 3, 7)) == utc(2026, 3, 7, 7)
    assert new_york.instant(date(2026, 3, 8)) == utc(2026, 3, 8, 7)
    assert new_york.instant(date(2026, 3, 9)) == utc(2026, 3, 9, 6)
    # 01:00 occurs twice on 2026-11-01: the run is at the first one (EDT).
    assert Timing("daily", None, 1, "America/New_York").instant(date(2026, 11, 1)) == utc(
        2026, 11, 1, 5
    )
    cairo = Timing("daily", None, 0, "Africa/Cairo")
    skipped = cairo.instant(date(2026, 4, 24))
    assert skipped == utc(2026, 4, 23, 22)
    assert skipped.astimezone(ZoneInfo("Africa/Cairo")).date() == date(2026, 4, 24)
    assert cairo.period(date(2026, 4, 24)) == Period(date(2026, 4, 23), date(2026, 4, 24))
    # Across both changes every local date runs exactly once, in order.
    for timing, start in (
        (new_york, utc(2026, 3, 5)),
        (Timing("daily", None, 1, "America/New_York"), utc(2026, 10, 29)),
        (cairo, utc(2026, 4, 21)),
        (Timing("daily", None, 1, "Europe/London"), utc(2026, 3, 27)),
    ):
        moment, days = start, []
        for _ in range(8):
            day, moment = timing.next_after(moment)
            days.append(day)
        assert days == [days[0] + timedelta(days=offset) for offset in range(8)]


def test_rv11_month_ends():
    monthly = Timing("monthly", None, 0, "UTC")
    cases = {
        date(2026, 3, 1): (date(2026, 2, 1), 28),
        date(2028, 3, 1): (date(2028, 2, 1), 29),
        date(2026, 5, 1): (date(2026, 4, 1), 30),
        date(2026, 1, 1): (date(2025, 12, 1), 31),
    }
    for day, (start, days) in cases.items():
        period = monthly.period(day)
        assert (period.start, period.end, period.days) == (start, day, days)
    assert monthly.latest_at(utc(2026, 3, 15)) == (date(2026, 3, 1), utc(2026, 3, 1))
    assert monthly.next_after(utc(2026, 3, 1)) == (date(2026, 4, 1), utc(2026, 4, 1))
    assert monthly.next_after(utc(2026, 2, 28, 23, 59)) == (date(2026, 3, 1), utc(2026, 3, 1))


@pytest.mark.parametrize(
    "cadence, weekday, hour, zone, code",
    [
        ("weekly", None, 5, "UTC", "invalid_schedule"),
        ("daily", 3, 5, "UTC", "invalid_schedule"),
        ("weekly", 8, 5, "UTC", "invalid_schedule"),
        ("daily", None, 24, "UTC", "invalid_schedule"),
        ("hourly", None, 5, "UTC", "invalid_schedule"),
        ("daily", None, 5, "Mars/Olympus_Mons", "invalid_time_zone"),
    ],
)
def test_rv11_invalid_timing(cadence, weekday, hour, zone, code):
    with pytest.raises(ReportError, match=code):
        Timing(cadence, weekday, hour, zone)


def test_rv14_email_text():
    agency, client, export = (
        UUID("00000000-0000-4000-8000-00000000000a"),
        UUID("00000000-0000-4000-8000-00000000000c"),
        UUID("00000000-0000-4000-8000-00000000000e"),
    )
    subject, body = report_ready_message(
        SimpleNamespace(frontend_origin="http://127.0.0.1:5173"),
        ReportReady(
            display_name="Synthetic Studio",
            schedule_name="Monthly revenue",
            family="revenue",
            period_start=date(2026, 11, 1),
            period_end=date(2026, 12, 1),
            agency_id=agency,
            client_id=client,
            export_id=export,
            expires_at=utc(2026, 12, 8, 6, 0, 30),
        ),
    )
    assert subject == "Report ready: Monthly revenue"
    assert body == (
        "Synthetic Studio\n\n"
        'The scheduled report "Monthly revenue" is ready.\n\n'
        "Report: Revenue\n"
        "Period: 2026-11-01 to 2026-11-30\n\n"
        "Open it in the application:\n"
        f"http://127.0.0.1:5173/agencies/{agency}/clients/{client}/reports/exports/{export}\n\n"
        "The report can be downloaded until 2026-12-08 06:00 UTC. You receive this message "
        "because you are a recipient of this schedule.\n"
    )


def chunk(kind: bytes, body: bytes) -> bytes:
    return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")


def header(width=1, height=1, depth=8, color=6, compression=0, method=0, interlace=0) -> bytes:
    return (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes([depth, color, compression, method, interlace])
    )


def png(chunks=None, tail=b"", **fields) -> bytes:
    image = zlib.compress(bytes(1 + 4 * fields.get("width", 1)))
    parts = chunks or [(b"IHDR", header(**fields)), (b"IDAT", image), (b"IEND", b"")]
    return SIGNATURE + b"".join(chunk(kind, body) for kind, body in parts) + tail


def test_rv17_png_checks():
    assert check_png(png()) == (1, 1)
    assert check_png(png(width=1024, height=7, depth=1, color=0, interlace=1)) == (1024, 7)
    assert check_png(png(color=3, depth=4)) == (1, 1)
    image = zlib.compress(bytes(5))
    split = [
        (b"IHDR", header()),
        (b"tEXt", b"Comment" + bytes(1) + b"synthetic"),
        (b"IDAT", image[:4]),
        (b"IDAT", image[4:]),
        (b"IEND", b""),
    ]
    assert check_png(png(chunks=split)) == (1, 1)
    valid = png()
    broken_crc = valid[:-5] + bytes([valid[-5] ^ 1]) + valid[-4:]
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><script/></svg>' * 2
    refused = [
        svg,
        b"GIF89a" + valid[6:],
        broken_crc,
        valid[:40],
        png(tail=b"x"),
        png(width=0),
        png(width=1025),
        png(height=2000),
        png(color=2, depth=4),
        png(color=5),
        png(compression=1),
        png(method=1),
        png(interlace=2),
        png(chunks=[(b"IHDR", header() + b"x"), (b"IDAT", image), (b"IEND", b"")]),
        png(chunks=[(b"IDAT", image), (b"IHDR", header()), (b"IEND", b"")]),
        png(chunks=[(b"IHDR", header()), (b"IHDR", header()), (b"IDAT", image), (b"IEND", b"")]),
        png(chunks=[(b"IHDR", header()), (b"IEND", b"")]),
        png(chunks=[(b"IHDR", header()), (b"IDAT", image), (b"IEND", b"x")]),
        png(chunks=[(b"IHDR", header()), (b"IDAT", image)]),
        png(chunks=[(b"IHDR", header()), (b"ID1T", image), (b"IDAT", image), (b"IEND", b"")]),
        png(chunks=[(b"IHDR", header()), (b"IDAT", bytes(256 * 1024)), (b"IEND", b"")]),
    ]
    for data in refused:
        with pytest.raises(ReportError, match="invalid_png"):
            check_png(data)
