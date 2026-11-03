"""Invitations, service credentials, and live scope resolution for trusted consumers."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Agency,
    AgencyInvitation,
    AgencyMembership,
    ClientWorkspace,
    InvitationClientGrant,
    ServiceClientGrant,
    ServiceCredential,
    User,
)
from app.security import AuthError, digest, new_token, normalize_email, now_utc
from app.services.mail import queue_mail
from app.services.tenancy import MANAGERS, AccessDenied, MembershipConflict, Role, TenancyService


@dataclass(frozen=True)
class ClientPermission:
    client_id: UUID
    can_view_financials: bool = False


@dataclass(frozen=True)
class Principal:
    """Internal identity from authenticated HTTP or trusted server-created job context."""

    kind: Literal["user", "service"]
    identifier: UUID


@dataclass(frozen=True)
class ScopedAccess:
    principal: Principal
    agency_id: UUID
    client_id: UUID
    permission: Literal["client:read", "finance:read"]

    def cache_key(self, resource: str) -> str:
        # A cache partition is not authorization. Re-resolve access before using this key.
        if not resource or ":" in resource or len(resource) > 100:
            raise ValueError("Use a non-empty, bounded cache resource name without colons.")
        return (
            f"v1:{self.agency_id}:{self.client_id}:{self.principal.kind}:"
            f"{self.principal.identifier}:{self.permission}:{resource}"
        )


def live_service_credential(session: Session, identifier: UUID) -> ServiceCredential:
    credential = session.scalar(
        select(ServiceCredential)
        .join(Agency, Agency.id == ServiceCredential.agency_id)
        .join(
            AgencyMembership,
            (
                (AgencyMembership.id == ServiceCredential.creator_membership_id)
                & (AgencyMembership.agency_id == ServiceCredential.agency_id)
            ),
        )
        .join(User, User.id == AgencyMembership.user_id)
        .where(
            ServiceCredential.id == identifier,
            ServiceCredential.status == "active",
            ServiceCredential.expires_at > now_utc(),
            Agency.status == "active",
            AgencyMembership.status == "active",
            AgencyMembership.role.in_(["owner", "admin"]),
            User.status == "active",
            User.email_verified_at.is_not(None),
        )
        .execution_options(populate_existing=True)
    )
    if credential is None:
        raise AuthError("authentication_required")
    return credential


def authenticate_service_key(session: Session, raw: str) -> Principal:
    if not raw.startswith("tsk_") or not 32 <= len(raw) <= 128:
        raise AuthError("authentication_required")
    identifier = session.scalar(
        select(ServiceCredential.id).where(ServiceCredential.token_digest == digest(raw))
    )
    if identifier is None:
        raise AuthError("authentication_required")
    credential = live_service_credential(session, identifier)
    return Principal("service", credential.id)


def resolve_scope(
    session: Session,
    principal: Principal,
    agency_id: UUID,
    client_id: UUID,
    permission: Literal["client:read", "finance:read"] = "client:read",
) -> ScopedAccess:
    if permission not in {"client:read", "finance:read"}:
        raise AccessDenied()
    if principal.kind == "user":
        user = session.scalar(
            select(User.id).where(
                User.id == principal.identifier,
                User.status == "active",
                User.email_verified_at.is_not(None),
            )
        )
        if user is None:
            raise AccessDenied()
        service = TenancyService(session, principal.identifier)
        if permission == "finance:read":
            service.require_financial_access(agency_id, client_id)
        else:
            service.get_client(agency_id, client_id)
    elif principal.kind == "service":
        credential = live_service_credential(session, principal.identifier)
        if credential.agency_id != agency_id:
            raise AccessDenied()
        grant = session.scalar(
            select(ServiceClientGrant)
            .join(
                ClientWorkspace,
                (
                    (ClientWorkspace.id == ServiceClientGrant.client_id)
                    & (ClientWorkspace.agency_id == ServiceClientGrant.agency_id)
                ),
            )
            .where(
                ServiceClientGrant.agency_id == agency_id,
                ServiceClientGrant.client_id == client_id,
                ServiceClientGrant.credential_id == credential.id,
                ClientWorkspace.status == "active",
            )
            .execution_options(populate_existing=True)
        )
        if grant is None or (permission == "finance:read" and not grant.can_view_financials):
            raise AccessDenied()
    else:
        raise AccessDenied()
    return ScopedAccess(principal, agency_id, client_id, permission)


class AccessService(TenancyService):
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    def _check_grants(self, agency_id: UUID, grants: list[ClientPermission]) -> None:
        if len(grants) > 100 or len({item.client_id for item in grants}) != len(grants):
            raise ValueError("Client grants must be unique and limited to 100 clients.")
        for grant in grants:
            self.get_client(agency_id, grant.client_id)

    def invite(
        self,
        agency_id: UUID,
        email: str,
        role: Role,
        grants: list[ClientPermission],
    ) -> AgencyInvitation:
        actor = self._manager(agency_id, write=True)
        role = Role(role)
        if role == Role.OWNER and actor.role != Role.OWNER:
            raise AccessDenied()
        email = normalize_email(email)
        self._check_grants(agency_id, grants)
        member = self.session.scalar(
            select(AgencyMembership.id)
            .join(User, User.id == AgencyMembership.user_id)
            .where(AgencyMembership.agency_id == agency_id, User.email_normalized == email)
        )
        pending = self.session.scalar(
            select(AgencyInvitation.id).where(
                AgencyInvitation.agency_id == agency_id,
                AgencyInvitation.email_normalized == email,
                AgencyInvitation.status == "pending",
                AgencyInvitation.expires_at > now_utc(),
            )
        )
        if member is not None or pending is not None:
            raise MembershipConflict("The agency already has this member or a pending invitation.")
        raw = new_token()
        invitation = AgencyInvitation(
            agency_id=agency_id,
            inviter_membership_id=actor.id,
            email_normalized=email,
            role=role.value,
            token_digest=digest(raw),
            expires_at=now_utc() + timedelta(seconds=self.settings.invitation_lifetime_seconds),
        )
        self.session.add(invitation)
        self.session.flush()
        self.session.add_all(
            [
                InvitationClientGrant(
                    agency_id=agency_id,
                    invitation_id=invitation.id,
                    client_id=item.client_id,
                    can_view_financials=item.can_view_financials,
                )
                for item in grants
            ]
        )
        queue_mail(self.session, self.settings, email, "invitation", raw)
        self._audit(agency_id, "invitation.created", "invitation", invitation.id)
        return invitation

    def list_invitations(
        self, agency_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[AgencyInvitation]:
        self._manager(agency_id)
        return list(
            self.session.scalars(
                select(AgencyInvitation)
                .where(AgencyInvitation.agency_id == agency_id)
                .order_by(AgencyInvitation.created_at, AgencyInvitation.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def revoke_invitation(self, agency_id: UUID, invitation_id: UUID) -> None:
        actor = self._manager(agency_id, write=True)
        item = self.session.scalar(
            select(AgencyInvitation)
            .where(AgencyInvitation.agency_id == agency_id, AgencyInvitation.id == invitation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None or (item.role == Role.OWNER and actor.role != Role.OWNER):
            raise AccessDenied()
        if item.status == "pending":
            item.status = "revoked"
            self._audit(agency_id, "invitation.revoked", "invitation", item.id)

    def accept_invitation(self, raw: str) -> AgencyMembership:
        user = self._active_user(self.actor_user_id)
        if user.email_verified_at is None:
            raise AuthError("email_verification_required", 403)
        agency_id = self.session.scalar(
            select(AgencyInvitation.agency_id).where(AgencyInvitation.token_digest == digest(raw))
        )
        if agency_id is None:
            raise AuthError("invalid_or_expired_token", 400)
        agency = self.session.scalar(
            select(Agency.id)
            .where(Agency.id == agency_id, Agency.status == "active")
            .with_for_update()
        )
        item = self.session.scalar(
            select(AgencyInvitation)
            .where(AgencyInvitation.token_digest == digest(raw))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            agency is None
            or item is None
            or item.status != "pending"
            or item.expires_at <= now_utc()
            or item.email_normalized != user.email_normalized
        ):
            raise AuthError("invalid_or_expired_token", 400)
        inviter = self._target_member(agency_id, item.inviter_membership_id)
        if (
            inviter.status != "active"
            or inviter.role not in MANAGERS
            or (item.role == Role.OWNER and inviter.role != Role.OWNER)
        ):
            raise AuthError("invalid_or_expired_token", 400)
        grants = list(
            self.session.scalars(
                select(InvitationClientGrant).where(
                    InvitationClientGrant.agency_id == agency_id,
                    InvitationClientGrant.invitation_id == item.id,
                )
            )
        )
        issuer = TenancyService(self.session, inviter.user_id)
        for grant in grants:
            issuer.get_client(agency_id, grant.client_id)
        member = issuer.add_member(agency_id, user.id, Role(item.role))
        for grant in grants:
            issuer.grant_client(
                agency_id, grant.client_id, member.id, can_view_financials=grant.can_view_financials
            )
        item.status, item.accepted_by_user_id = "accepted", user.id
        self._audit(agency_id, "invitation.accepted", "invitation", item.id)
        return member

    def issue_service_key(
        self,
        agency_id: UUID,
        name: str,
        grants: list[ClientPermission],
        *,
        expires_in_days: int = 90,
    ) -> tuple[ServiceCredential, str]:
        actor = self._manager(agency_id, write=True)
        if not grants or not 1 <= expires_in_days <= 90 or len(name.strip()) > 100:
            raise ValueError("Provide client grants, a name up to 100 characters, and 1-90 days.")
        self._check_grants(agency_id, grants)
        raw = "tsk_" + new_token()
        item = ServiceCredential(
            agency_id=agency_id,
            creator_membership_id=actor.id,
            name=self._name(name),
            token_digest=digest(raw),
            expires_at=now_utc() + timedelta(days=expires_in_days),
        )
        self.session.add(item)
        self.session.flush()
        self.session.add_all(
            [
                ServiceClientGrant(
                    agency_id=agency_id,
                    credential_id=item.id,
                    client_id=grant.client_id,
                    can_view_financials=grant.can_view_financials,
                )
                for grant in grants
            ]
        )
        self._audit(agency_id, "credential.created", "credential", item.id)
        return item, raw

    def list_service_keys(
        self, agency_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[ServiceCredential]:
        self._manager(agency_id)
        return list(
            self.session.scalars(
                select(ServiceCredential)
                .where(ServiceCredential.agency_id == agency_id)
                .order_by(ServiceCredential.created_at, ServiceCredential.id)
                .limit(limit)
                .offset(offset)
            )
        )

    def revoke_service_key(self, agency_id: UUID, credential_id: UUID) -> None:
        self._manager(agency_id, write=True)
        item = self.session.scalar(
            select(ServiceCredential)
            .where(ServiceCredential.agency_id == agency_id, ServiceCredential.id == credential_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AccessDenied()
        if item.status == "active":
            item.status = "revoked"
            self._audit(agency_id, "credential.revoked", "credential", item.id)
