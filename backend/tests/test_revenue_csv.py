"""Transaction CSV files and manual declarations without a database (specification 015-C).

D-067 decisions D8 and D9: fixed columns, closed row error codes, formula-injection and
personal-data refusals, and the size and row limits. Every value is synthetic.
"""

from datetime import UTC, datetime

import pytest

from app.declarations import (
    MAX_ROWS,
    Declaration,
    FileRefused,
    parse_csv,
    validate_declaration,
)
from app.ledger import OperationKind

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
HEADER = (
    "operation_id,kind,amount,currency,effective_at,parent_operation_id,source_reference,reason"
)


def _file(*rows: str, header: str = HEADER) -> bytes:
    return ("\r\n".join((header, *rows)) + "\r\n").encode()


def _errors(body: bytes) -> list[tuple[str, ...]]:
    return [row.errors for row in parse_csv(body, NOW).rows]


def test_valid_rows_become_declarations():
    parsed = parse_csv(
        _file(
            "INV-1001,sale,1500.00,EGP,2026-11-10T10:00:00+02:00,,order 1001,",
            'INV-1002,refund,250.5,EGP,2026-11-11T10:00:00Z,INV-1001,,"Customer, partial"',
            "INV-1003,sale,99,JPY,2026-11-12T00:00:00+09:00,,,",
        ),
        NOW,
    )
    assert [row.status for row in parsed.rows] == ["valid", "valid", "valid"]
    sale, refund, yen = parsed.valid
    assert (sale.kind, sale.amount.minor, sale.amount.currency.code) == (
        OperationKind.SALE,
        150_000,
        "EGP",
    )
    assert sale.effective_at == datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    assert (refund.kind, refund.parent_operation_id, refund.amount.minor) == (
        OperationKind.REFUND,
        "INV-1001",
        25_050,
    )
    assert refund.reason == "Customer, partial"
    assert yen.amount.minor == 99
    assert len(parsed.digest) == 64
    assert sale.delivery_id.startswith("declaration:INV-1001:")


def test_optional_columns_and_byte_order_mark():
    body = (
        "\ufeffkind,operation_id,currency,amount,effective_at\n"
        "sale,A-1,USD,10.00,2026-11-01T00:00:00Z\n"
    )
    (row,) = parse_csv(body.encode(), NOW).rows
    assert row.status == "valid" and row.declaration.amount.minor == 1_000


@pytest.mark.parametrize(
    ("row", "codes"),
    [
        ("A-2,sale,10.00,EGP,2026-11-01T00:00:00Z,,,,extra", ("wrong_field_count",)),
        ("A-3,payout,10.00,EGP,2026-11-01T00:00:00Z,,,", ("invalid_kind",)),
        ("A-4,sale,10.001,EGP,2026-11-01T00:00:00Z,,,", ("invalid_amount",)),
        ("A-5,sale,0,EGP,2026-11-01T00:00:00Z,,,", ("invalid_amount",)),
        ("A-6,sale,ten,EGP,2026-11-01T00:00:00Z,,,", ("invalid_amount",)),
        ("A-7,sale,10.00,XYZ,2026-11-01T00:00:00Z,,,", ("unsupported_currency",)),
        ("A-8,sale,10.00,EGP,2026-11-01T00:00:00,,,", ("invalid_time",)),  # no offset
        ("A-9,sale,10.00,EGP,2026-11-25T00:00:00Z,,,", ("invalid_time",)),  # in the future
        ("A-10,refund,10.00,EGP,2026-11-01T00:00:00Z,,,", ("invalid_parent",)),
        ("A-11,sale,10.00,EGP,2026-11-01T00:00:00Z,A-1,,", ("invalid_parent",)),
        ("A-12,refund,10.00,EGP,2026-11-01T00:00:00Z,A-12,,", ("invalid_parent",)),
        (",sale,10.00,EGP,2026-11-01T00:00:00Z,,,", ("missing_value",)),
        ("A-13,sale,,EGP,,,,", ("missing_value",)),
        ("A-14,sale,10.00,EGP,2026-11-01T00:00:00Z,,," + "r" * 1025, ("value_too_long",)),
        ("A-15,sale,10.00,EGP,2026-11-01T00:00:00Z,," + "s" * 257 + ",", ("value_too_long",)),
        ("A-16,sale,10.00,EGP,2026-11-01T00:00:00Z,,,buyer@example.test", ("prohibited_value",)),
        ("A-17,sale,10.00,EGP,2026-11-01T00:00:00Z,,+20 100 000 0931,", ("prohibited_value",)),
        ("A-18,sale,10.00,EGP,2026-11-01T00:00:00Z,,,card 4111111111111111", ("prohibited_value",)),
        ("A-19,sale,10.00,EGP,2026-11-01T00:00:00Z,,,=HYPERLINK(1)", ("formula_cell",)),
        ("A-20,sale,-10.00,EGP,2026-11-01T00:00:00Z,,,", ("formula_cell", "invalid_amount")),
        ("A-21,sale,10.00,EGP,2026-11-01T00:00:00Z,,@SUM(1),", ("formula_cell",)),
        ("A-22,sale,10.00,EGP,2026-11-01T00:00:00Z,,+cmd,", ("formula_cell",)),
        ('A-23,sale,10.00,EGP,2026-11-01T00:00:00Z,,"\tTAB",', ("formula_cell",)),
    ],
)
def test_row_error_codes(row, codes):
    # T-30: every row is validated with closed codes; the rejected value is never echoed.
    (result,) = parse_csv(_file(row), NOW).rows
    assert result.status == "rejected"
    assert set(codes) <= set(result.errors)
    assert result.declaration is None


def test_order_numbers_are_not_mistaken_for_phones():
    (row,) = parse_csv(
        _file("A-30,sale,10.00,EGP,2026-11-01T00:00:00Z,,INV-2026-000123-77,"), NOW
    ).rows
    assert row.status == "valid"


def test_duplicate_operations_in_one_file():
    rows = _errors(
        _file(
            "A-40,sale,10.00,EGP,2026-11-01T00:00:00Z,,,",
            "A-40,sale,10.00,EGP,2026-11-01T00:00:00Z,,,",
        )
    )
    assert rows == [(), ("duplicate_row",)]


@pytest.mark.parametrize(
    ("header", "code"),
    [
        ("operation_id,kind,amount,currency,effective_at,email", "personal_data_column"),
        ("operation_id,kind,amount,currency,effective_at,Customer Name", "personal_data_column"),
        ("operation_id,kind,amount,currency,effective_at,phone_number", "personal_data_column"),
        ("operation_id,kind,amount,currency,effective_at,Billing Address", "personal_data_column"),
        ("operation_id,kind,amount,currency,effective_at,city", "personal_data_column"),
        ("operation_id,kind,amount,currency,effective_at,notes", "unknown_column"),
        ("operation_id,kind,amount,currency", "missing_column"),
        ("operation_id,kind,amount,currency,effective_at,kind", "duplicate_column"),
    ],
)
def test_header_refusals(header, code):
    # T-33: personal-data headers and any column outside the fixed set refuse the file.
    with pytest.raises(FileRefused) as refused:
        parse_csv(_file("A-50,sale,10.00,EGP,2026-11-01T00:00:00Z,x", header=header), NOW)
    assert refused.value.code == code


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"", "empty_file"),
        (HEADER.encode() + b"\r\n", "empty_file"),
        (b"\xff\xfe" + HEADER.encode(), "invalid_encoding"),
        (HEADER.encode() + b'\r\n"A-60,sale', "invalid_csv"),
        (HEADER.encode() + b"\r\nA\x00,sale,1,EGP,2026-11-01T00:00:00Z,,,", "invalid_csv"),
    ],
)
def test_file_refusals(body, code):
    with pytest.raises(FileRefused) as refused:
        parse_csv(body, NOW)
    assert refused.value.code == code


def test_size_and_row_limits():
    # T-34: at most 10,000 data rows and 2 MiB per file.
    row = "A-{},sale,1.00,EGP,2026-11-01T00:00:00Z,,,"
    allowed = _file(*(row.format(index) for index in range(MAX_ROWS)))
    assert len(parse_csv(allowed, NOW).rows) == MAX_ROWS
    with pytest.raises(FileRefused) as refused:
        parse_csv(_file(*(row.format(index) for index in range(MAX_ROWS + 1))), NOW)
    assert refused.value.code == "too_many_rows"
    with pytest.raises(FileRefused) as refused:
        parse_csv(b"x" * (2 * 1024 * 1024 + 1), NOW)
    assert refused.value.code == "file_too_large"


def test_manual_declaration_needs_a_reason():
    # T-36: a manual declaration has the same validation and a required reason.
    values = {
        "operation_id": "M-1",
        "kind": "sale",
        "amount": "75.00",
        "currency": "EGP",
        "effective_at": "2026-11-20T09:00:00+02:00",
    }
    assert validate_declaration(values, NOW, reason_required=True) == ("missing_value",)
    declared = validate_declaration({**values, "reason": "Paid in cash"}, NOW, reason_required=True)
    assert isinstance(declared, Declaration) and declared.reason == "Paid in cash"
    assert validate_declaration({**values, "reason": "x\x07"}, NOW, reason_required=True) == (
        "invalid_text",
    )
