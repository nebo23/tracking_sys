"""Agency branding routes: the white-label delivery contract (specification 016-C, D-095 D11).

Below /agencies/{agency_id}/branding, for browser sessions only:

- GET returns the profile to every active member, client viewers included; without a profile
  it answers configured=false with null fields, so no internal agency name is shown.
- PUT sets the display name and the accent color (Owners and Admins; audited).
- PUT /logo takes a raw image/png body of at most 256 KiB (route limit) that passes the PNG
  structure check; anything else, SVG included, is refused. DELETE /logo removes it. Both are
  for Owners and Admins and audited; a profile must exist first.
- GET /logo serves the stored PNG to members with nosniff, no-store and
  Content-Security-Policy: default-src 'none'.

The frontend may apply the profile to its clients' screens later (018); nothing here renders a
branded page.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import StringConstraints

from app.api.dependencies import BrowserDep, RawBody, SessionDep
from app.api.schemas import Input, Output
from app.models import AgencyBranding
from app.reporting.common import ReportError
from app.services.branding import BrandingService

router = APIRouter(tags=["Report delivery"])
BASE = "/agencies/{agency_id}/branding"
LOGO_HEADERS = {
    "Content-Security-Policy": "default-src 'none'",
    "Content-Disposition": 'inline; filename="logo.png"',
}
PNG_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
    }
}
PNG_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
        "description": "The stored PNG logo.",
    }
}


class BrandingInput(Input):
    display_name: Annotated[
        str,
        StringConstraints(
            min_length=1, max_length=100, strip_whitespace=True, pattern=r"^[^\x00-\x1f\x7f]+$"
        ),
    ]
    accent_color: Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]


class BrandingLogo(Output):
    width: int
    height: int
    byte_size: int


class AgencyBrandingView(Output):
    agency_id: UUID
    configured: bool
    display_name: str | None
    accent_color: str | None
    logo: BrandingLogo | None
    updated_at: datetime | None


def branding_view(agency_id: UUID, profile: AgencyBranding | None) -> AgencyBrandingView:
    if profile is None:
        return AgencyBrandingView(
            agency_id=agency_id,
            configured=False,
            display_name=None,
            accent_color=None,
            logo=None,
            updated_at=None,
        )
    logo = None
    if profile.logo is not None:
        assert profile.logo_width is not None and profile.logo_height is not None
        logo = BrandingLogo(
            width=profile.logo_width, height=profile.logo_height, byte_size=len(profile.logo)
        )
    return AgencyBrandingView(
        agency_id=agency_id,
        configured=True,
        display_name=profile.display_name,
        accent_color=profile.accent_color,
        logo=logo,
        updated_at=profile.updated_at,
    )


@router.get(BASE, response_model=AgencyBrandingView)
def read_branding(agency_id: UUID, session: SessionDep, browser: BrowserDep) -> AgencyBrandingView:
    return branding_view(agency_id, BrandingService(session, browser.user.id).read(agency_id))


@router.put(BASE, response_model=AgencyBrandingView)
def save_branding(
    agency_id: UUID, data: BrandingInput, session: SessionDep, browser: BrowserDep
) -> AgencyBrandingView:
    profile = BrandingService(session, browser.user.id).save(
        agency_id, data.display_name, data.accent_color
    )
    return branding_view(agency_id, profile)


@router.put(f"{BASE}/logo", response_model=AgencyBrandingView, openapi_extra=PNG_BODY)
def save_branding_logo(
    agency_id: UUID, request: Request, body: RawBody, session: SessionDep, browser: BrowserDep
) -> AgencyBrandingView:
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media != "image/png":
        raise ReportError("unsupported_media_type", 415)
    profile = BrandingService(session, browser.user.id).set_logo(agency_id, body)
    return branding_view(agency_id, profile)


@router.delete(f"{BASE}/logo", response_model=AgencyBrandingView)
def delete_branding_logo(
    agency_id: UUID, session: SessionDep, browser: BrowserDep
) -> AgencyBrandingView:
    profile = BrandingService(session, browser.user.id).remove_logo(agency_id)
    return branding_view(agency_id, profile)


@router.get(f"{BASE}/logo", responses=PNG_RESPONSE)
def read_branding_logo(agency_id: UUID, session: SessionDep, browser: BrowserDep) -> Response:
    data = BrandingService(session, browser.user.id).logo(agency_id)
    return Response(content=data, media_type="image/png", headers=LOGO_HEADERS)
