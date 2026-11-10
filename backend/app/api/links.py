"""Managed-link administration and public redirects (specification 005, D-033).

Mutations require an Owner/Admin browser session with the platform Origin and CSRF token, and
are audited. Lists are readable by principals authorized for the client (client:read: granted
members and read keys); ingest keys and other clients' principals are denied. The redirect
route is public and read-only: it never writes telemetry, sets cookies, or contacts the network.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import BrowserDep, ReaderDep, SessionDep
from app.api.link_schemas import (
    CampaignInput,
    CampaignResponse,
    CampaignUpdate,
    ChallengeResponse,
    ContentInput,
    ContentResponse,
    ContentUpdate,
    DomainInput,
    DomainResponse,
    DomainUpdate,
    LinkInput,
    LinkResponse,
    LinkUpdate,
    OriginInput,
    OriginResponse,
    OriginUpdate,
    TemplateInput,
    TemplateResponse,
    TemplateUpdate,
)
from app.api.schemas import ErrorResponse
from app.models import (
    LinkCampaign,
    LinkContentReference,
    LinkDestinationOrigin,
    LinkDomain,
    LinkUtmTemplate,
    ManagedLink,
)
from app.services.access import resolve_scope
from app.services.links import PAGE_DEFAULT, PAGE_MAX, LinkAdmin, list_scoped, resolve_redirect

router = APIRouter(tags=["Managed links"])
redirect_router = APIRouter(tags=["Redirects"])
CLIENT = "/agencies/{agency_id}/clients/{client_id}"
Limit = Annotated[int, Query(ge=1, le=PAGE_MAX)]
Offset = Annotated[int, Query(ge=0, le=100000)]
CONFLICT = {409: {"model": ErrorResponse, "description": "Host or uniqueness conflict."}}


def _admin(request: Request, session, browser) -> LinkAdmin:
    return LinkAdmin(session, browser.user.id, request.app.state.settings)


def _list(session, principal, model, agency_id: UUID, client_id: UUID, limit: int, offset: int):
    resolve_scope(session, principal, agency_id, client_id)
    return list_scoped(session, model, agency_id, client_id, limit=limit, offset=offset)


def _fields(data) -> dict:
    if not data.model_fields_set:
        raise ValueError("An update field is required.")
    return {name: getattr(data, name) for name in data.model_fields_set}


@router.post(f"{CLIENT}/link-campaigns", status_code=201, response_model=CampaignResponse)
def create_campaign(
    agency_id: UUID,
    client_id: UUID,
    data: CampaignInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> CampaignResponse:
    item = _admin(request, session, browser).create_campaign(
        agency_id, client_id, public_code=data.public_code, label=data.label
    )
    return CampaignResponse.model_validate(item)


@router.get(f"{CLIENT}/link-campaigns", response_model=list[CampaignResponse])
def list_campaigns(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    limit: Limit = PAGE_DEFAULT,
    offset: Offset = 0,
) -> list[CampaignResponse]:
    rows = _list(session, principal, LinkCampaign, agency_id, client_id, limit, offset)
    return [CampaignResponse.model_validate(item) for item in rows]


@router.patch(f"{CLIENT}/link-campaigns/{{campaign_id}}", response_model=CampaignResponse)
def update_campaign(
    agency_id: UUID,
    client_id: UUID,
    campaign_id: UUID,
    data: CampaignUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> CampaignResponse:
    item = _admin(request, session, browser).update_campaign(
        agency_id, client_id, campaign_id, **_fields(data)
    )
    return CampaignResponse.model_validate(item)


@router.post(f"{CLIENT}/link-content-references", status_code=201, response_model=ContentResponse)
def create_content(
    agency_id: UUID,
    client_id: UUID,
    data: ContentInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ContentResponse:
    item = _admin(request, session, browser).create_content(
        agency_id, client_id, external_code=data.external_code, platform_label=data.platform_label
    )
    return ContentResponse.model_validate(item)


@router.get(f"{CLIENT}/link-content-references", response_model=list[ContentResponse])
def list_content(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    limit: Limit = PAGE_DEFAULT,
    offset: Offset = 0,
) -> list[ContentResponse]:
    rows = _list(session, principal, LinkContentReference, agency_id, client_id, limit, offset)
    return [ContentResponse.model_validate(item) for item in rows]


@router.patch(f"{CLIENT}/link-content-references/{{content_id}}", response_model=ContentResponse)
def update_content(
    agency_id: UUID,
    client_id: UUID,
    content_id: UUID,
    data: ContentUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ContentResponse:
    item = _admin(request, session, browser).update_content(
        agency_id, client_id, content_id, **_fields(data)
    )
    return ContentResponse.model_validate(item)


@router.post(f"{CLIENT}/link-utm-templates", status_code=201, response_model=TemplateResponse)
def create_template(
    agency_id: UUID,
    client_id: UUID,
    data: TemplateInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> TemplateResponse:
    item = _admin(request, session, browser).create_template(
        agency_id, client_id, name=data.name, parameters=data.parameters
    )
    return TemplateResponse.model_validate(item)


@router.get(f"{CLIENT}/link-utm-templates", response_model=list[TemplateResponse])
def list_templates(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    limit: Limit = PAGE_DEFAULT,
    offset: Offset = 0,
) -> list[TemplateResponse]:
    rows = _list(session, principal, LinkUtmTemplate, agency_id, client_id, limit, offset)
    return [TemplateResponse.model_validate(item) for item in rows]


@router.patch(f"{CLIENT}/link-utm-templates/{{template_id}}", response_model=TemplateResponse)
def update_template(
    agency_id: UUID,
    client_id: UUID,
    template_id: UUID,
    data: TemplateUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> TemplateResponse:
    item = _admin(request, session, browser).update_template(
        agency_id, client_id, template_id, **_fields(data)
    )
    return TemplateResponse.model_validate(item)


@router.post(
    f"{CLIENT}/link-destination-origins",
    status_code=201,
    response_model=OriginResponse,
    responses=CONFLICT,
)
def create_origin(
    agency_id: UUID,
    client_id: UUID,
    data: OriginInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> OriginResponse:
    item = _admin(request, session, browser).create_origin(
        agency_id, client_id, origin=data.origin, query_names=data.query_names
    )
    return OriginResponse.model_validate(item)


@router.get(f"{CLIENT}/link-destination-origins", response_model=list[OriginResponse])
def list_origins(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    limit: Limit = PAGE_DEFAULT,
    offset: Offset = 0,
) -> list[OriginResponse]:
    rows = _list(session, principal, LinkDestinationOrigin, agency_id, client_id, limit, offset)
    return [OriginResponse.model_validate(item) for item in rows]


@router.patch(
    f"{CLIENT}/link-destination-origins/{{origin_id}}",
    response_model=OriginResponse,
    responses=CONFLICT,
)
def update_origin(
    agency_id: UUID,
    client_id: UUID,
    origin_id: UUID,
    data: OriginUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> OriginResponse:
    item = _admin(request, session, browser).update_origin(
        agency_id, client_id, origin_id, **_fields(data)
    )
    return OriginResponse.model_validate(item)


@router.post(
    f"{CLIENT}/link-domains", status_code=201, response_model=DomainResponse, responses=CONFLICT
)
def create_domain(
    agency_id: UUID,
    client_id: UUID,
    data: DomainInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> DomainResponse:
    item = _admin(request, session, browser).create_domain(
        agency_id, client_id, hostname=data.hostname
    )
    return DomainResponse.model_validate(item)


@router.get(f"{CLIENT}/link-domains", response_model=list[DomainResponse])
def list_domains(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    limit: Limit = PAGE_DEFAULT,
    offset: Offset = 0,
) -> list[DomainResponse]:
    rows = _list(session, principal, LinkDomain, agency_id, client_id, limit, offset)
    return [DomainResponse.model_validate(item) for item in rows]


# Disabling is the only direct status change; it revokes the domain immediately.
@router.patch(f"{CLIENT}/link-domains/{{domain_id}}", response_model=DomainResponse)
def update_domain(
    agency_id: UUID,
    client_id: UUID,
    domain_id: UUID,
    data: DomainUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> DomainResponse:
    item = _admin(request, session, browser).disable_domain(agency_id, client_id, domain_id)
    return DomainResponse.model_validate(item)


# Issue a new TXT ownership challenge; the raw value appears only in this response.
@router.post(
    f"{CLIENT}/link-domains/{{domain_id}}/challenge",
    status_code=201,
    response_model=ChallengeResponse,
)
def issue_challenge(
    agency_id: UUID,
    client_id: UUID,
    domain_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> ChallengeResponse:
    issued = _admin(request, session, browser).issue_challenge(agency_id, client_id, domain_id)
    target = request.app.state.settings.link_service_target or None
    return ChallengeResponse(
        domain=DomainResponse.model_validate(issued.domain),
        record_name=issued.record_name,
        record_value=issued.record_value,
        expires_at=issued.domain.challenge_expires_at,
        cname_target=target,
    )


@router.post(
    f"{CLIENT}/managed-links", status_code=201, response_model=LinkResponse, responses=CONFLICT
)
def create_link(
    agency_id: UUID,
    client_id: UUID,
    data: LinkInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> LinkResponse:
    item = _admin(request, session, browser).create_link(
        agency_id, client_id, **data.model_dump(exclude_unset=True)
    )
    return LinkResponse.model_validate(item)


@router.get(f"{CLIENT}/managed-links", response_model=list[LinkResponse])
def list_links(
    agency_id: UUID,
    client_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    limit: Limit = PAGE_DEFAULT,
    offset: Offset = 0,
) -> list[LinkResponse]:
    rows = _list(session, principal, ManagedLink, agency_id, client_id, limit, offset)
    return [LinkResponse.model_validate(item) for item in rows]


@router.patch(f"{CLIENT}/managed-links/{{link_id}}", response_model=LinkResponse)
def update_link(
    agency_id: UUID,
    client_id: UUID,
    link_id: UUID,
    data: LinkUpdate,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> LinkResponse:
    fields = _fields(data)
    item = _admin(request, session, browser).update_link(
        agency_id,
        client_id,
        link_id,
        status=fields.get("status"),
        expires_at=fields.get("expires_at"),
        clear_expiry="expires_at" in fields and fields["expires_at"] is None,
    )
    return LinkResponse.model_validate(item)


def _redirect(request: Request, session, slug: str) -> Response:
    target = resolve_redirect(
        session, request.app.state.settings, request.headers.get("host"), slug
    )
    if target is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return Response(status_code=302, headers={"Location": target.url})


REDIRECT_RESPONSES = {
    302: {"description": "Redirect to the link's issued destination; no body, no cookie."},
    404: {"model": ErrorResponse, "description": "Unknown, disabled, or expired link or host."},
    503: {"model": ErrorResponse, "description": "Link storage is temporarily unavailable."},
}


# Public short link: 302 to the issued target with no-store and no-referrer headers. The
# request's own query string is ignored. HEAD answers identically without a body.
@redirect_router.get(
    "/r/{slug}", status_code=302, response_class=Response, responses=REDIRECT_RESPONSES
)
def follow_link(slug: str, request: Request, session: SessionDep) -> Response:
    return _redirect(request, session, slug)


@redirect_router.head("/r/{slug}", include_in_schema=False)
def head_link(slug: str, request: Request, session: SessionDep) -> Response:
    return _redirect(request, session, slug)
