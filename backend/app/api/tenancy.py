"""Authenticated tenant administration and client-scoped service reads."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import and_, or_, select

from app.api.dependencies import BrowserDep, ReaderDep, SessionDep
from app.api.schemas import (
    PLAN_LIMIT,
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
    MemberClientGrant,
    MemberDetail,
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
from app.services.auth import enforce_rate_limit
from app.services.tenancy import AccessDenied, MemberDetailRow, TenancyService

# Tenant administration router. Every route authenticates through BrowserDep or ReaderDep and
# delegates authorization to the tenancy/access services; mutations commit with their audit
# events in the request's SessionDep transaction. Limit/Offset bound list pagination.
router = APIRouter(tags=["Agency access"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]
# active (the default) or archived, which only Owners and Admins may list (018-B plan, B2).
ClientStatus = Annotated[Literal["active", "archived"], Query()]


# Create an agency; the authenticated verified user becomes its Owner. Audited.
@router.post("/agencies", status_code=201, response_model=AgencyResponse)
def create_agency(data: AgencyInput, session: SessionDep, browser: BrowserDep) -> AgencyResponse:
    return AgencyResponse.model_validate(
        TenancyService(session, browser.user.id).create_agency(data.name)
    )


# List the caller's active memberships in active agencies (agency ID, role and status), and
# the closing agencies in which the caller is an active Owner (017-A, D8).
@router.get("/agencies", response_model=list[AgencyAccess])
def list_agencies(
    session: SessionDep, browser: BrowserDep, limit: Limit = 100, offset: Offset = 0
) -> list[AgencyAccess]:
    # Client viewers learn their scope IDs without receiving the private agency profile.
    rows = session.execute(
        select(AgencyMembership.agency_id, AgencyMembership.role, Agency.status)
        .join(Agency, Agency.id == AgencyMembership.agency_id)
        .where(
            AgencyMembership.user_id == browser.user.id,
            AgencyMembership.status == "active",
            or_(
                Agency.status == "active",
                and_(Agency.status == "closing", AgencyMembership.role == "owner"),
            ),
        )
        .order_by(AgencyMembership.agency_id)
        .limit(limit)
        .offset(offset)
    )
    return [
        AgencyAccess(agency_id=agency_id, role=role, status=status)
        for agency_id, role, status in rows
    ]


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


# Create a client workspace in the agency (Owner/Admin) within the plan's client limit;
# audited.
@router.post(
    "/agencies/{agency_id}/clients",
    status_code=201,
    response_model=ClientResponse,
    responses=PLAN_LIMIT,
)
def create_client(
    agency_id: UUID, data: AgencyInput, session: SessionDep, browser: BrowserDep
) -> ClientResponse:
    return ClientResponse.model_validate(
        TenancyService(session, browser.user.id).create_client(agency_id, data.name)
    )


# List active clients readable by the principal: managers see all, restricted members see
# explicit grants, and a service key sees only its own granted clients in its own agency. With
# status=archived, Owners and Admins list the archived clients they may restore (018-B plan, B2);
# everyone else, service keys included, is denied.
@router.get("/agencies/{agency_id}/clients", response_model=list[ClientResponse])
def list_clients(
    agency_id: UUID,
    session: SessionDep,
    principal: ReaderDep,
    limit: Limit = 100,
    offset: Offset = 0,
    status: ClientStatus = "active",
) -> list[ClientResponse]:
    if principal.kind == "user":
        clients = TenancyService(session, principal.identifier).list_clients(
            agency_id, status=status, limit=limit, offset=offset
        )
    else:
        key = live_service_credential(session, principal.identifier)
        if key.agency_id != agency_id or status != "active":
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


# Rename or archive/reactivate a client (Owner/Admin); requires at least one field; a
# reactivation must fit the plan's client limit; audited.
@router.patch(
    "/agencies/{agency_id}/clients/{client_id}", response_model=ClientResponse, responses=PLAN_LIMIT
)
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


# One member as Owners and Admins see it: a closed account's pseudonyms are never returned.
def _member_detail(row: MemberDetailRow) -> MemberDetail:
    named = row.account != "closed"
    return MemberDetail(
        id=row.membership.id,
        agency_id=row.membership.agency_id,
        user_id=row.membership.user_id,
        role=row.membership.role,
        status=row.membership.status,
        joined_at=row.membership.created_at,
        display_name=row.user.display_name if named else None,
        email_normalized=row.user.email_normalized if named else None,
        account=row.account,
        clients=[MemberClientGrant.model_validate(grant) for grant in row.grants],
    )


# List agency memberships with each person's name, email, account state and client grants
# (Owner/Admin only; 018-B plan, B1; D-101).
@router.get("/agencies/{agency_id}/members", response_model=list[MemberDetail])
def list_members(
    agency_id: UUID,
    session: SessionDep,
    browser: BrowserDep,
    limit: Limit = 100,
    offset: Offset = 0,
) -> list[MemberDetail]:
    return [
        _member_detail(row)
        for row in TenancyService(session, browser.user.id).list_member_details(
            agency_id, limit=limit, offset=offset
        )
    ]


# Change a member's role or status under Owner rules and last-active-Owner protection; enabling
# a disabled member must fit the plan's seat limit; audited.
@router.patch(
    "/agencies/{agency_id}/members/{membership_id}",
    response_model=MembershipResponse,
    responses=PLAN_LIMIT,
)
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
        agency_id,
        client_id,
        membership_id,
        can_view_financials=data.can_view_financials,
        can_view_identities=data.can_view_identities,
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
    responses=PLAN_LIMIT,
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


# Persistent per-peer throttle for invitation acceptance in its own "invitation-ip" namespace.
# As a decorator dependency it is resolved before BrowserDep, so it runs before session
# authentication and its user-row lock. The counter commits through the security engine.
def invitation_peer_limit(request: Request) -> None:
    settings = request.app.state.settings
    peer = request.client.host if request.client else "unknown"
    enforce_rate_limit(
        request.app.state.security_engine,
        settings,
        "invitation-ip",
        peer,
        limit=settings.auth_requests_per_minute,
        period=60,
    )


# Accept an invitation token as the logged-in verified recipient. Creates the membership and
# grants atomically with audit events. The per-peer limit runs first; after authentication a
# per-user "invitation-accept" limit is counted before any invitation lookup or agency lock.
# Both counters commit independently, so invalid, replayed, or denied attempts stay counted
# when the business transaction rolls back. Over a limit, the sanitized 429 has Retry-After.
@router.post(
    "/invitations/accept",
    response_model=MembershipResponse,
    tags=["Invitations"],
    dependencies=[Depends(invitation_peer_limit)],
)
def accept_invitation(
    data: TokenInput, request: Request, session: SessionDep, browser: BrowserDep
) -> MembershipResponse:
    settings = request.app.state.settings
    enforce_rate_limit(
        request.app.state.security_engine,
        settings,
        "invitation-accept",
        str(browser.user.id),
        limit=settings.invitation_attempts_per_minute,
        period=60,
    )
    return MembershipResponse.model_validate(
        access(request, session, browser).accept_invitation(data.token.get_secret_value())
    )


# Issue an expiring read or ingest service key with explicit client grants (Owner/Admin). The
# raw key is returned once in this response and only its digest is stored; audited.
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
        kind=data.kind,
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
