"""Authenticated tenant administration and client-scoped service reads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from app.api.dependencies import BrowserDep, ReaderDep, SessionDep
from app.api.schemas import (
    AgencyAccess,
    AgencyInput,
    AgencyResponse,
    AuditResponse,
    ClientResponse,
    ClientUpdate,
    FinancialGrant,
    InvitationInput,
    InvitationResponse,
    IssuedServiceKey,
    MembershipResponse,
    MembershipUpdate,
    ServiceKeyInput,
    ServiceKeyResponse,
    TokenInput,
)
from app.models import Agency, AgencyMembership, ClientWorkspace, ServiceClientGrant
from app.services.access import (
    AccessService,
    ClientPermission,
    live_service_credential,
    resolve_scope,
)
from app.services.tenancy import AccessDenied, TenancyService

# Tenant administration router. Every route authenticates through BrowserDep or ReaderDep and
# delegates authorization to the tenancy/access services; mutations commit with their audit
# events in the request's SessionDep transaction. Limit/Offset bound list pagination.
router = APIRouter(tags=["Agency access"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]


# Create an agency; the authenticated verified user becomes its Owner. Audited.
@router.post("/agencies", status_code=201, response_model=AgencyResponse)
def create_agency(data: AgencyInput, session: SessionDep, browser: BrowserDep) -> AgencyResponse:
    return AgencyResponse.model_validate(
        TenancyService(session, browser.user.id).create_agency(data.name)
    )


# List the caller's active memberships in active agencies (agency ID and role only).
@router.get("/agencies", response_model=list[AgencyAccess])
def list_agencies(
    session: SessionDep, browser: BrowserDep, limit: Limit = 100, offset: Offset = 0
) -> list[AgencyAccess]:
    # Client viewers learn their scope IDs without receiving the private agency profile.
    memberships = session.scalars(
        select(AgencyMembership)
        .join(Agency, Agency.id == AgencyMembership.agency_id)
        .where(
            AgencyMembership.user_id == browser.user.id,
            AgencyMembership.status == "active",
            Agency.status == "active",
        )
        .order_by(AgencyMembership.agency_id)
        .limit(limit)
        .offset(offset)
    )
    return [AgencyAccess.model_validate(member) for member in memberships]


# Read an agency profile; denied to ClientViewer members and non-members.
@router.get("/agencies/{agency_id}", response_model=AgencyResponse)
def get_agency(agency_id: UUID, session: SessionDep, browser: BrowserDep) -> AgencyResponse:
    return AgencyResponse.model_validate(
        TenancyService(session, browser.user.id).get_agency(agency_id)
    )


# Rename an agency (Owner/Admin) under the agency write lock; audited.
@router.patch("/agencies/{agency_id}", response_model=AgencyResponse)
def update_agency(
    agency_id: UUID, data: AgencyInput, session: SessionDep, browser: BrowserDep
) -> AgencyResponse:
    return AgencyResponse.model_validate(
        TenancyService(session, browser.user.id).rename_agency(agency_id, data.name)
    )


# Create a client workspace in the agency (Owner/Admin); audited.
@router.post("/agencies/{agency_id}/clients", status_code=201, response_model=ClientResponse)
def create_client(
    agency_id: UUID, data: AgencyInput, session: SessionDep, browser: BrowserDep
) -> ClientResponse:
    return ClientResponse.model_validate(
        TenancyService(session, browser.user.id).create_client(agency_id, data.name)
    )


# List active clients readable by the principal: managers see all, restricted members see
# explicit grants, and a service key sees only its own granted clients in its own agency.
@router.get("/agencies/{agency_id}/clients", response_model=list[ClientResponse])
def list_clients(
    agency_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[ClientResponse]:
    if principal.kind == "user":
        clients = TenancyService(session, principal.identifier).list_clients(
            agency_id, limit=limit, offset=offset
        )
    else:
        key = live_service_credential(session, principal.identifier)
        if key.agency_id != agency_id:
            raise AccessDenied()
        clients = session.scalars(
            select(ClientWorkspace)
            .join(
                ServiceClientGrant,
                (
                    (ServiceClientGrant.agency_id == ClientWorkspace.agency_id)
                    & (ServiceClientGrant.client_id == ClientWorkspace.id)
                ),
            )
            .where(
                ClientWorkspace.agency_id == agency_id,
                ClientWorkspace.status == "active",
                ServiceClientGrant.credential_id == key.id,
            )
            .order_by(ClientWorkspace.id)
            .limit(limit)
            .offset(offset)
        )
    return [ClientResponse.model_validate(client) for client in clients]


# Read one client after live scope resolution for a user or service principal.
@router.get("/agencies/{agency_id}/clients/{client_id}", response_model=ClientResponse)
def get_client(
    agency_id: UUID, client_id: UUID, session: SessionDep, principal: ReaderDep
) -> ClientResponse:
    resolve_scope(session, principal, agency_id, client_id)
    client = session.scalar(
        select(ClientWorkspace).where(
            ClientWorkspace.id == client_id, ClientWorkspace.agency_id == agency_id
        )
    )
    return ClientResponse.model_validate(client)


# Rename or archive/reactivate a client (Owner/Admin); requires at least one field; audited.
@router.patch("/agencies/{agency_id}/clients/{client_id}", response_model=ClientResponse)
def update_client(
    agency_id: UUID, client_id: UUID, data: ClientUpdate, session: SessionDep, browser: BrowserDep
) -> ClientResponse:
    if data.name is None and data.status is None:
        raise ValueError("An update field is required.")
    return ClientResponse.model_validate(
        TenancyService(session, browser.user.id).update_client(
            agency_id, client_id, name=data.name, status=data.status
        )
    )


# List agency memberships (Owner/Admin only).
@router.get("/agencies/{agency_id}/members", response_model=list[MembershipResponse])
def list_members(
    agency_id: UUID,
    session: SessionDep,
    browser: BrowserDep,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[MembershipResponse]:
    return [
        MembershipResponse.model_validate(member)
        for member in TenancyService(session, browser.user.id).list_members(
            agency_id, limit=limit, offset=offset
        )
    ]


# Change a member's role or status under Owner rules and last-active-Owner protection; audited.
@router.patch("/agencies/{agency_id}/members/{membership_id}", response_model=MembershipResponse)
def update_member(
    agency_id: UUID,
    membership_id: UUID,
    data: MembershipUpdate,
    session: SessionDep,
    browser: BrowserDep,
) -> MembershipResponse:
    if data.role is None and data.status is None:
        raise ValueError("An update field is required.")
    return MembershipResponse.model_validate(
        TenancyService(session, browser.user.id).update_member(
            agency_id, membership_id, role=data.role, status=data.status
        )
    )


# Create or update an explicit client grant, including financial visibility; audited.
@router.put("/agencies/{agency_id}/members/{membership_id}/clients/{client_id}", status_code=204)
def grant_client(
    agency_id: UUID,
    membership_id: UUID,
    client_id: UUID,
    data: FinancialGrant,
    session: SessionDep,
    browser: BrowserDep,
) -> Response:
    TenancyService(session, browser.user.id).grant_client(
        agency_id, client_id, membership_id, can_view_financials=data.can_view_financials
    )
    return Response(status_code=204)


# Remove an explicit client grant; idempotent when no grant exists; audited when removed.
@router.delete("/agencies/{agency_id}/members/{membership_id}/clients/{client_id}", status_code=204)
def revoke_client(
    agency_id: UUID, membership_id: UUID, client_id: UUID, session: SessionDep, browser: BrowserDep
) -> Response:
    TenancyService(session, browser.user.id).revoke_client(agency_id, client_id, membership_id)
    return Response(status_code=204)


# Read the most recent agency audit events (Owner/Admin), newest first, at most 100.
@router.get("/agencies/{agency_id}/audit", response_model=list[AuditResponse])
def list_audit(
    agency_id: UUID, session: SessionDep, browser: BrowserDep, limit: Limit = 100
) -> list[AuditResponse]:
    return [
        AuditResponse.model_validate(event)
        for event in TenancyService(session, browser.user.id).list_audit(agency_id, limit=limit)
    ]


# Helper used by invitation and service-key routes: an AccessService for the browser user that
# shares the request transaction and application settings.
def access(request: Request, session: SessionDep, browser: BrowserDep) -> AccessService:
    return AccessService(session, browser.user.id, request.app.state.settings)


# Invite a member by email with a role and explicit client grants (only an Owner may invite an
# Owner). Stores a token digest, queues an encrypted invitation link, and audits.
@router.post(
    "/agencies/{agency_id}/invitations",
    status_code=201,
    response_model=InvitationResponse,
    tags=["Invitations"],
)
def issue_invitation(
    agency_id: UUID,
    data: InvitationInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> InvitationResponse:
    result = access(request, session, browser).invite(
        agency_id,
        data.email,
        data.role,
        [ClientPermission(**item.model_dump()) for item in data.clients],
    )
    return InvitationResponse.model_validate(result)


# List agency invitations for Owner/Admin managers.
@router.get(
    "/agencies/{agency_id}/invitations",
    response_model=list[InvitationResponse],
    tags=["Invitations"],
)
def list_invitations(
    agency_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[InvitationResponse]:
    return [
        InvitationResponse.model_validate(item)
        for item in access(request, session, browser).list_invitations(
            agency_id, limit=limit, offset=offset
        )
    ]


# Revoke a pending invitation; Owner invitations require an Owner; audited when it changes.
@router.delete(
    "/agencies/{agency_id}/invitations/{invitation_id}", status_code=204, tags=["Invitations"]
)
def revoke_invitation(
    agency_id: UUID, invitation_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> Response:
    access(request, session, browser).revoke_invitation(agency_id, invitation_id)
    return Response(status_code=204)


# Accept an invitation token as the logged-in verified recipient. Creates the membership and
# grants atomically with audit events. No route-specific persistent throttle is applied here.
@router.post("/invitations/accept", response_model=MembershipResponse, tags=["Invitations"])
def accept_invitation(
    data: TokenInput, request: Request, session: SessionDep, browser: BrowserDep
) -> MembershipResponse:
    return MembershipResponse.model_validate(
        access(request, session, browser).accept_invitation(data.token.get_secret_value())
    )


# Issue an expiring read-only service key with explicit client grants (Owner/Admin). The raw
# key is returned once in this response and only its digest is stored; audited.
@router.post(
    "/agencies/{agency_id}/service-credentials",
    status_code=201,
    response_model=IssuedServiceKey,
    tags=["Service credentials"],
)
def issue_service_key(
    agency_id: UUID,
    data: ServiceKeyInput,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
) -> IssuedServiceKey:
    item, raw = access(request, session, browser).issue_service_key(
        agency_id,
        data.name,
        [ClientPermission(**grant.model_dump()) for grant in data.clients],
        expires_in_days=data.expires_in_days,
    )
    return IssuedServiceKey(credential=ServiceKeyResponse.model_validate(item), key=raw)


# List service key metadata (Owner/Admin); key values and digests are never returned.
@router.get(
    "/agencies/{agency_id}/service-credentials",
    response_model=list[ServiceKeyResponse],
    tags=["Service credentials"],
)
def list_service_keys(
    agency_id: UUID,
    request: Request,
    session: SessionDep,
    browser: BrowserDep,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[ServiceKeyResponse]:
    return [
        ServiceKeyResponse.model_validate(item)
        for item in access(request, session, browser).list_service_keys(
            agency_id, limit=limit, offset=offset
        )
    ]


# Revoke a service key (Owner/Admin); later Bearer use fails immediately; audited if active.
@router.delete(
    "/agencies/{agency_id}/service-credentials/{credential_id}",
    status_code=204,
    tags=["Service credentials"],
)
def revoke_service_key(
    agency_id: UUID, credential_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> Response:
    access(request, session, browser).revoke_service_key(agency_id, credential_id)
    return Response(status_code=204)
