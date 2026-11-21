"""Declared revenue: transaction CSV files and manual declarations (specification 015-C).

D-067 decisions D8 and D9; format in design-015a.md section 5.1. Pure functions only: no
database and no network. A declaration is a sale or a refund entered by an Owner or Admin, kept
as unverified manual_declaration evidence (007-A A1): it never enters verified totals and is
never delivered by 014-B.

parse_csv validates a whole file: the encoding, the header (a fixed set of columns; a column
outside it, or one naming personal data, refuses the file) and the row count, then every row
with closed error codes. validate_declaration applies the same row rules to one manual
declaration. Neither echoes a rejected value.
"""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.advertising.currencies import currency
from app.ledger import LedgerInputError, Money, OperationKind
from app.privacy.collection import contains_card_number

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10_000
REQUIRED = ("operation_id", "kind", "amount", "currency", "effective_at")
OPTIONAL = ("parent_operation_id", "source_reference", "reason")
COLUMNS = REQUIRED + OPTIONAL
MAX_OPERATION = 128
MAX_REFERENCE = 256
MAX_REASON = 1024
MAX_MINOR = 10**15
FUTURE = timedelta(days=1)
SOURCE_ACCOUNT = "declared"
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
PERSONAL_HEADERS = frozenset(
    {
        "name",
        "firstname",
        "lastname",
        "fullname",
        "customer",
        "customername",
        "buyer",
        "email",
        "mail",
        "phone",
        "phonenumber",
        "mobile",
        "telephone",
        "tel",
        "address",
        "street",
        "city",
        "postcode",
        "postalcode",
        "zip",
        "zipcode",
    }
)
PERSONAL_PARTS = ("email", "phone", "address")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
# A phone number in international form: a plus sign and 8 to 15 digits, with separators.
_PHONE = re.compile(r"\+\s*\d(?:[\s().-]*\d){7,14}")


class FileRefused(ValueError):
    """The whole file is refused with a closed code; no row result is returned."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Declaration:
    """One validated declared sale or refund."""

    operation_id: str
    kind: OperationKind
    amount: Money
    effective_at: datetime
    parent_operation_id: str | None
    source_reference: str | None
    reason: str | None

    # The delivery ID of the economic terms: the same declaration committed again, through any
    # file, is an exact redelivery (design section 5.2).
    @property
    def delivery_id(self) -> str:
        state = json.dumps(
            {
                "kind": self.kind.value,
                "minor": self.amount.minor,
                "currency": self.amount.currency.code,
                "exponent": self.amount.currency.exponent,
                "effective_at": self.effective_at.isoformat(timespec="microseconds"),
                "parent": self.parent_operation_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(state.encode()).hexdigest()[:32]
        return f"declaration:{self.operation_id}:{digest}"


@dataclass(frozen=True)
class RowResult:
    row: int  # 1-based data row number, the header excluded
    errors: tuple[str, ...]
    declaration: Declaration | None = field(default=None, repr=False)

    @property
    def status(self) -> str:
        return "valid" if not self.errors else "rejected"


@dataclass(frozen=True)
class ParsedFile:
    digest: str  # SHA-256 of the exact file bytes: the import ID
    rows: tuple[RowResult, ...]

    @property
    def valid(self) -> tuple[Declaration, ...]:
        return tuple(row.declaration for row in self.rows if row.declaration is not None)


def file_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _normalized(header: str) -> str:
    return re.sub(r"[\s_-]+", "", header.strip().lower())


def _personal(header: str) -> bool:
    name = _normalized(header)
    return name in PERSONAL_HEADERS or any(part in name for part in PERSONAL_PARTS)


def _prohibited(value: str) -> bool:
    return bool(_EMAIL.search(value) or _PHONE.search(value) or contains_card_number(value))


def _time(value: str, now: datetime) -> datetime | None:
    if not 10 <= len(value) <= 40:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None or moment.utcoffset() is None:
        return None
    moment = moment.astimezone(UTC)
    return moment if moment <= now + FUTURE else None


def _text_ok(value: str) -> bool:
    return value.isprintable() and value == value.strip()


# Validate one declaration given as text fields (a CSV row or a manual entry). Returns the
# declaration, or the sorted closed error codes; a rejected value is never returned.
def validate_declaration(
    values: dict[str, str | None], now: datetime, *, reason_required: bool = False
) -> Declaration | tuple[str, ...]:
    errors: set[str] = set()
    cells = {
        key: (value.strip() if isinstance(value, str) else None) for key, value in values.items()
    }
    for value, stripped in zip(values.values(), cells.values(), strict=True):
        if isinstance(value, str) and (
            value.startswith(FORMULA_PREFIXES) or (stripped or "").startswith(FORMULA_PREFIXES)
        ):
            errors.add("formula_cell")
    raw = {key: cells.get(key) or None for key in COLUMNS}
    for key in REQUIRED:
        if raw[key] is None:
            errors.add("missing_value")
    if reason_required and raw["reason"] is None:
        errors.add("missing_value")
    operation = raw["operation_id"]
    if operation is not None and (len(operation) > MAX_OPERATION or not _text_ok(operation)):
        errors.add("invalid_operation_id")
    kind = None
    if raw["kind"] is not None:
        if raw["kind"] in {"sale", "refund"}:
            kind = OperationKind(raw["kind"])
        else:
            errors.add("invalid_kind")
    unit = currency(raw["currency"]) if raw["currency"] is not None else None
    if raw["currency"] is not None and unit is None:
        errors.add("unsupported_currency")
    amount = None
    if raw["amount"] is not None and unit is not None:
        try:
            amount = Money.parse(raw["amount"], unit)
        except LedgerInputError:
            amount = None
        if amount is None or not 0 < amount.minor <= MAX_MINOR:
            errors.add("invalid_amount")
            amount = None
    effective = _time(raw["effective_at"], now) if raw["effective_at"] is not None else None
    if raw["effective_at"] is not None and effective is None:
        errors.add("invalid_time")
    parent = raw["parent_operation_id"]
    if parent is not None and (len(parent) > MAX_OPERATION or not _text_ok(parent)):
        errors.add("invalid_parent")
    if kind is OperationKind.REFUND and (parent is None or parent == operation):
        errors.add("invalid_parent")
    if kind is OperationKind.SALE and parent is not None:
        errors.add("invalid_parent")
    for key, limit in (("source_reference", MAX_REFERENCE), ("reason", MAX_REASON)):
        value = raw[key]
        if value is None:
            continue
        if len(value) > limit:
            errors.add("value_too_long")
        elif not _text_ok(value):
            errors.add("invalid_text")
        elif _prohibited(value):
            errors.add("prohibited_value")
    if errors:
        return tuple(sorted(errors))
    assert operation is not None and kind is not None and amount is not None
    assert effective is not None
    return Declaration(
        operation, kind, amount, effective, parent, raw["source_reference"], raw["reason"]
    )


# Validate a whole CSV file (design section 5.1). Raises FileRefused for a file-level refusal.
def parse_csv(body: bytes, now: datetime) -> ParsedFile:
    if len(body) > MAX_FILE_BYTES:
        raise FileRefused("file_too_large")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FileRefused("invalid_encoding") from error
    text = text.removeprefix("\ufeff")
    if "\x00" in text:
        raise FileRefused("invalid_csv")
    try:
        records = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as error:
        raise FileRefused("invalid_csv") from error
    records = [record for record in records if record != []]
    if not records:
        raise FileRefused("empty_file")
    header = [cell.strip() for cell in records[0]]
    if any(_personal(name) for name in header):
        raise FileRefused("personal_data_column")
    if len(set(header)) != len(header):
        raise FileRefused("duplicate_column")
    if any(name not in COLUMNS for name in header):
        raise FileRefused("unknown_column")
    if any(name not in header for name in REQUIRED):
        raise FileRefused("missing_column")
    data = records[1:]
    if not data:
        raise FileRefused("empty_file")
    if len(data) > MAX_ROWS:
        raise FileRefused("too_many_rows")
    seen: set[str] = set()
    results = []
    for number, record in enumerate(data, start=1):
        if len(record) != len(header):
            results.append(RowResult(number, ("wrong_field_count",)))
            continue
        outcome = validate_declaration(dict(zip(header, record, strict=True)), now)
        if isinstance(outcome, Declaration):
            if outcome.operation_id in seen:
                outcome = ("duplicate_row",)
            else:
                seen.add(outcome.operation_id)
        if isinstance(outcome, Declaration):
            results.append(RowResult(number, (), outcome))
        else:
            results.append(RowResult(number, outcome))
    return ParsedFile(file_digest(body), tuple(results))
