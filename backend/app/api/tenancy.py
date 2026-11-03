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

router = APIRouter(tags=["Agency access"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]


@router.post("/agencies", status_code=201, response_model=AgencyResponse)
def create_agency(data: AgencyInput, session: SessionDep, browser: BrowserDep) -> AgencyResponse:
    return AgencyResponse.model_validate(
        TenancyService(session, browser.user.id).create_agency(data.name)
    )


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


@router.get("/agencies/{agency_id}", response_model=AgencyResponse)
def get_agency(agency_id: UUID, session: SessionDep, browser: BrowserDep) -> AgencyResponse:
    return AgencyResponse.model_validate(
        TenancyService(session, browser.user.id).get_agency(agency_id)
    )


@router.patch("/agencies/{agency_id}", response_model=AgencyResponse)
def update_agency(
    agency_id: UUID, data: AgencyInput, session: SessionDep, browser: BrowserDep
) -> AgencyResponse:
    return AgencyResponse.model_validate(
        TenancyService(session, browser.user.id).rename_agency(agency_id, data.name)
    )


@router.post("/agencies/{agency_id}/clients", status_code=201, response_model=ClientResponse)
def create_client(
    agency_id: UUID, data: AgencyInput, session: SessionDep, browser: BrowserDep
) -> ClientResponse:
    return ClientResponse.model_validate(
        TenancyService(session, browser.user.id).create_client(agency_id, data.name)
    )


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


@router.delete("/agencies/{agency_id}/members/{membership_id}/clients/{client_id}", status_code=204)
def revoke_client(
    agency_id: UUID, membership_id: UUID, client_id: UUID, session: SessionDep, browser: BrowserDep
) -> Response:
    TenancyService(session, browser.user.id).revoke_client(agency_id, client_id, membership_id)
    return Response(status_code=204)


@router.get("/agencies/{agency_id}/audit", response_model=list[AuditResponse])
def list_audit(
    agency_id: UUID, session: SessionDep, browser: BrowserDep, limit: Limit = 100
) -> list[AuditResponse]:
    return [
        AuditResponse.model_validate(event)
        for event in TenancyService(session, browser.user.id).list_audit(agency_id, limit=limit)
    ]


def access(request: Request, session: SessionDep, browser: BrowserDep) -> AccessService:
    return AccessService(session, browser.user.id, request.app.state.settings)


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


@router.delete(
    "/agencies/{agency_id}/invitations/{invitation_id}", status_code=204, tags=["Invitations"]
)
def revoke_invitation(
    agency_id: UUID, invitation_id: UUID, request: Request, session: SessionDep, browser: BrowserDep
) -> Response:
    access(request, session, browser).revoke_invitation(agency_id, invitation_id)
    return Response(status_code=204)


@router.post("/invitations/accept", response_model=MembershipResponse, tags=["Invitations"])
def accept_invitation(
    data: TokenInput, request: Request, session: SessionDep, browser: BrowserDep
) -> MembershipResponse:
    return MembershipResponse.model_validate(
        access(request, session, browser).accept_invitation(data.token.get_secret_value())
    )


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
