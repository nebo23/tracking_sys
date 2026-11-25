"""Versioned identifier normalizers and verification methods (specification 006 section 5, D4).

email:v1 uses the 003 email canonicalization (syntax check, then lowercase; no dot or plus
rewriting). phone:v1 accepts international ASCII input only: after trimming ASCII spaces the
whole value must match ^(\\+|00)[1-9][0-9 ()-]*$ and carry 8-15 digits after the prefix; only
then is the 003 helper called, without a default country. National input of ASCII digits and
formatting is refused as phone_country_required and every other invalid value as
identifier_invalid. ref:v1 is the client's exact account ID, 1-128 characters of
[A-Za-z0-9_.:-], case-sensitive and never rewritten. Raw values exist only transiently in the
caller; nothing here logs or stores them.
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.privacy.deletion import canonical_identifier

Kind = Literal["email", "phone", "customer_ref"]
KINDS: tuple[Kind, ...] = ("email", "phone", "customer_ref")
NORMALIZERS: dict[str, str] = {"email": "email:v1", "phone": "phone:v1", "customer_ref": "ref:v1"}
KEY_VERSION = 1
# Allowed declared methods per kind (design section 4.1). staff_verified requires the client's
# explicit attestation for the named kind; no attestation setting exists in this slice, so it
# is refused as method_invalid rather than accepted without one.
METHODS: dict[str, frozenset[str]] = {
    "email": frozenset({"email_code", "email_link", "account_verified_email"}),
    "phone": frozenset({"phone_code", "account_verified_phone"}),
    "customer_ref": frozenset({"account_login"}),
}
_PHONE = re.compile(r"(\+|00)[1-9][0-9 ()\-]*")
_NATIONAL = re.compile(r"[0-9 ()\-]*[0-9][0-9 ()\-]*")
_REFERENCE = re.compile(r"[A-Za-z0-9_.:\-]{1,128}")


class IdentifierRejected(ValueError):
    """A request-level rejection with a closed public reason code."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Canonical:
    kind: Kind
    normalizer: str
    value: str  # canonical value; transient, never stored


def canonical(kind: str, value: str) -> Canonical:
    if kind not in NORMALIZERS or not isinstance(value, str):
        raise IdentifierRejected("identifier_invalid")
    if kind == "email":
        if len(value) > 320:
            raise IdentifierRejected("identifier_invalid")
        try:
            return Canonical("email", NORMALIZERS[kind], canonical_identifier("email", value))
        except ValueError as error:
            raise IdentifierRejected("identifier_invalid") from error
    if kind == "phone":
        text = value.strip(" ")
        if len(text) > 64:
            raise IdentifierRejected("identifier_invalid")
        if not text.isascii() or _PHONE.fullmatch(text) is None:
            if text.isascii() and _NATIONAL.fullmatch(text) is not None:
                raise IdentifierRejected("phone_country_required")
            raise IdentifierRejected("identifier_invalid")
        digits = "".join(character for character in text if character in "0123456789")
        national = digits[2:] if text.startswith("00") else digits
        if not 8 <= len(national) <= 15:
            raise IdentifierRejected("identifier_invalid")
        try:
            result = canonical_identifier("phone", text)
        except ValueError as error:
            raise IdentifierRejected("identifier_invalid") from error
        if result != "+" + national:
            raise IdentifierRejected("identifier_invalid")
        return Canonical("phone", NORMALIZERS[kind], result)
    if _REFERENCE.fullmatch(value) is None:
        raise IdentifierRejected("identifier_invalid")
    return Canonical("customer_ref", NORMALIZERS[kind], value)


def check_method(kind: str, method: str) -> None:
    if method not in METHODS.get(kind, frozenset()):
        raise IdentifierRejected("method_invalid")
