"""Agency branding profile: the white-label delivery contract (specification 016-C, D-095 D11).

Each agency may keep one profile: a display name its clients see (1-100 characters, no control
character), an accent color (#RRGGBB, stored in upper case) and an optional PNG logo of at most
256 KiB and 1024 by 1024 pixels. Owners and Admins write it, audited as branding.updated; every
active member of the agency, client viewers included, reads it. Report emails use the display
name, or the agency's name without a profile.

check_png reads the bytes without decoding the image: the PNG signature; chunks whose length
fits the remaining bytes, whose type is four ASCII letters and whose CRC-32 matches; IHDR first,
13 bytes, with a width and a height of 1-1024, a bit depth valid for its color type, compression
and filter method 0 and interlace 0 or 1; at least one IDAT; and IEND last, empty, with nothing
after it. Anything else, an SVG file included, is refused. Branded screens, printable pages and
PDF files wait for the frontend round and the owner's brief (D-039).
"""

import re
import zlib
from uuid import UUID

from sqlalchemy import select

from app.models import Agency, AgencyBranding
from app.models.report_delivery import MAX_LOGO_BYTES
from app.reporting.common import ReportError
from app.security import now_utc
from app.services.tenancy import TenancyService

SIGNATURE = bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A])
MIN_PNG_BYTES = 67
MAX_DIMENSION = 1024
# Bit depths allowed for each PNG color type (PNG specification, section 11.2.2).
DEPTHS = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


def _refuse() -> ReportError:
    return ReportError("invalid_png", 422)


def check_png(data: bytes) -> tuple[int, int]:
    """The width and height of a structurally valid PNG; raises invalid_png otherwise."""
    if not MIN_PNG_BYTES <= len(data) <= MAX_LOGO_BYTES or not data.startswith(SIGNATURE):
        raise _refuse()
    offset, index, width, height, images = len(SIGNATURE), 0, 0, 0, 0
    while True:
        if offset + 12 > len(data):
            raise _refuse()
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        if length > len(data) - offset - 12 or not (kind.isascii() and kind.isalpha()):
            raise _refuse()
        body = data[offset + 8 : offset + 8 + length]
        crc = data[offset + 8 + length : offset + 12 + length]
        if zlib.crc32(kind + body).to_bytes(4, "big") != crc:
            raise _refuse()
        if index == 0:
            if kind != b"IHDR" or length != 13:
                raise _refuse()
            width = int.from_bytes(body[0:4], "big")
            height = int.from_bytes(body[4:8], "big")
            depth, color, compression, method, interlace = body[8:13]
            if not (1 <= width <= MAX_DIMENSION and 1 <= height <= MAX_DIMENSION):
                raise _refuse()
            if depth not in DEPTHS.get(color, set()) or compression or method or interlace > 1:
                raise _refuse()
        elif kind == b"IHDR":
            raise _refuse()
        images += kind == b"IDAT"
        offset += 12 + length
        index += 1
        if kind == b"IEND":
            if length != 0 or offset != len(data) or not images:
                raise _refuse()
            return width, height


def _display_name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ReportError("invalid_branding", 422)
    return value


def _accent(value: str) -> str:
    if not COLOR.fullmatch(value):
        raise ReportError("invalid_branding", 422)
    return value.upper()


class BrandingService(TenancyService):
    """Branding profile operations; the request session commits."""

    def read(self, agency_id: UUID) -> AgencyBranding | None:
        self._membership(agency_id)
        return self.session.scalar(
            select(AgencyBranding)
            .where(AgencyBranding.agency_id == agency_id)
            .execution_options(populate_existing=True)
        )

    def _profile(self, agency_id: UUID) -> AgencyBranding | None:
        return self.session.scalar(
            select(AgencyBranding)
            .where(AgencyBranding.agency_id == agency_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def save(self, agency_id: UUID, display_name: str, accent_color: str) -> AgencyBranding:
        actor = self._manager(agency_id, write=True)
        name, color = _display_name(display_name), _accent(accent_color)
        profile = self._profile(agency_id)
        if profile is None:
            profile = AgencyBranding(agency_id=agency_id)
            self.session.add(profile)
        profile.display_name, profile.accent_color = name, color
        profile.updated_at, profile.updated_by_membership_id = now_utc(), actor.id
        self._audit(agency_id, "branding.updated", "agency_branding", agency_id)
        return profile

    def set_logo(self, agency_id: UUID, data: bytes) -> AgencyBranding:
        actor = self._manager(agency_id, write=True)
        profile = self._profile(agency_id)
        if profile is None:
            raise ReportError("branding_profile_required", 409)
        width, height = check_png(data)
        profile.logo, profile.logo_width, profile.logo_height = data, width, height
        profile.updated_at, profile.updated_by_membership_id = now_utc(), actor.id
        self._audit(agency_id, "branding.updated", "agency_branding", agency_id)
        return profile

    def remove_logo(self, agency_id: UUID) -> AgencyBranding | None:
        actor = self._manager(agency_id, write=True)
        profile = self._profile(agency_id)
        if profile is None or profile.logo is None:
            return profile
        profile.logo = profile.logo_width = profile.logo_height = None
        profile.updated_at, profile.updated_by_membership_id = now_utc(), actor.id
        self._audit(agency_id, "branding.updated", "agency_branding", agency_id)
        return profile

    def logo(self, agency_id: UUID) -> bytes:
        profile = self.read(agency_id)
        if profile is None or profile.logo is None:
            raise ReportError("logo_not_found", 404)
        return profile.logo


# The name report emails carry: the profile's display name, or the agency's name.
def display_name(session, agency_id: UUID) -> str:
    branded = session.scalar(
        select(AgencyBranding.display_name).where(AgencyBranding.agency_id == agency_id)
    )
    if branded is not None:
        return branded
    return session.scalar(select(Agency.name).where(Agency.id == agency_id)) or ""
