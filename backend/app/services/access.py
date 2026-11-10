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


# One requested client grant for an invitation or service key; finance access is opt-in.
@dataclass(frozen=True)
class ClientPermission:
    client_id: UUID
    can_view_financials: bool = False


# Authenticated actor for read authorization: a browser user ID or a service credential ID.
@dataclass(frozen=True)
class Principal:
    """Internal identity from authenticated HTTP or trusted server-created job context."""

    kind: Literal["user", "service"]
    identifier: UUID


# Proof that resolve_scope authorized one principal for one client and permission now. It is
# a short-lived result for the current unit of work, not a stored or transferable grant.
@dataclass(frozen=True)
class ScopedAccess:
    principal: Principal
    agency_id: UUID
    client_id: UUID
    permission: Literal["client:read", "finance:read", "events:write"]

    # Partition future cache entries by agency, client, principal, permission, and resource.
    def cache_key(self, resource: str) -> str:
        # A cache partition is not authorization. Re-resolve access before using this key.
        if not resource or ":" in resource or len(resource) > 100:
            raise ValueError("Use a non-empty, bounded cache resource name without colons.")
        return (
            f"v1:{self.agency_id}:{self.client_id}:{self.principal.kind}:"
            f"{self.principal.identifier}:{self.permission}:{resource}"
        )


# Load a service credential of the given kind only while it is active and unexpired, its agency
# is active, and its creator still has an active Owner/Admin membership as an active verified
# user. Every use rechecks these conditions, so revocation or demotion takes effect
# immediately. A key of another kind is treated as unknown (D-027: read and ingest keys never
# substitute for each other).
def live_service_credential(
    session: Session, identifier: UUID, kind: Literal["read", "ingest"] = "read"
) -> ServiceCredential:
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
            ServiceCredential.kind == kind,
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


# Authenticate a Bearer key: check its tsk_ prefix and length, find the credential by SHA-256
# digest, then require live_service_credential of the expected kind. Unknown keys and keys of
# another kind fail with the same generic error.
def authenticate_service_key(
    session: Session, raw: str, kind: Literal["read", "ingest"] = "read"
) -> Principal:
    if not raw.startswith("tsk_") or not 32 <= len(raw) <= 128:
        raise AuthError("authentication_required")
    identifier = session.scalar(
        select(ServiceCredential.id).where(ServiceCredential.token_digest == digest(raw))
    )
    if identifier is None:
        raise AuthError("authentication_required")
    credential = live_service_credential(session, identifier, kind)
    return Principal("service", credential.id)


# Shared live authorization for client reads by routes and future jobs, exports, and caches,
# and for event writes (D-027). Users are rechecked through TenancyService membership/grant
# rules and never hold events:write; service keys need their own agency, an active client, an
# explicit grant (with the financial flag for finance:read), and the matching kind: read keys
# for reads, ingest keys for events:write. Denials raise AccessDenied; success returns a
# ScopedAccess for this unit of work only.
def resolve_scope(
    session: Session,
    principal: Principal,
    agency_id: UUID,
    client_id: UUID,
    permission: Literal["client:read", "finance:read", "events:write"] = "client:read",
) -> ScopedAccess:
    if permission not in {"client:read", "finance:read", "events:write"}:
        raise AccessDenied()
    if principal.kind == "user" and permission == "events:write":
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
        kind: Literal["read", "ingest"] = "ingest" if permission == "events:write" else "read"
        credential = live_service_credential(session, principal.identifier, kind)
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


# Invitation and service-key operations. It reuses TenancyService authorization and audit
# helpers and the caller-owned transaction; it adds application settings for lifetimes/mail.
class AccessService(TenancyService):
    # Bind the transaction, trusted actor user ID from authentication, and settings.
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    # Reject duplicate or excessive grants and require each client to be readable by the actor in
    # the same agency, which prevents granting foreign or inaccessible clients.
    def _check_grants(self, agency_id: UUID, grants: list[ClientPermission]) -> None:
        if len(grants) > 100 or len({item.client_id for item in grants}) != len(grants):
            raise ValueError("Client grants must be unique and limited to 100 clients.")
        for grant in grants:
            self.get_client(agency_id, grant.client_id)

    # Create a pending invitation under the agency write lock (Owner/Admin; Owner role requires an
    # Owner). Existing members and live pending invitations conflict. Stores only the token digest
    # and explicit grants, queues an encrypted invitation link, and audits in one transaction.
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
        # The message expires with its link (D-024 decision 5), so a failing delivery is cleared
        # unsent instead of retrying a dead invitation link indefinitely.
        queue_mail(
            self.session,
            self.settings,
            email,
            "invitation",
            raw,
            expires_at=invitation.expires_at,
        )
        self._audit(agency_id, "invitation.created", "invitation", invitation.id)
        return invitation

    # List the agency's invitations for Owner/Admin managers in creation order.
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

    # Revoke a pending invitation under the agency write lock and an invitation row lock. Only an
    # Owner may revoke an Owner invitation; already accepted/revoked rows are left unchanged.
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

    # Accept as the authenticated verified actor whose email matches the invitation. Locks the
    # active agency and then the invitation row, rejects expired/used tokens, and requires the
    # inviter to still be an active manager (an Owner for Owner invitations). The membership and
    # grants are created through a TenancyService acting as the inviter, so those audit events are
    # attributed to the issuer; the final invitation.accepted event is attributed to the acceptor.
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

    # Create an expiring key (1-90 days) with explicit grants under the agency write lock: a
    # read key by default, or an ingest key (D-027) that can only write events and API consent
    # and therefore never carries financial visibility. Returns the raw tsk_ key once; only its
    # digest is stored. Audited.
    def issue_service_key(
        self,
        agency_id: UUID,
        name: str,
        grants: list[ClientPermission],
        *,
        expires_in_days: int = 90,
        kind: Literal["read", "ingest"] = "read",
    ) -> tuple[ServiceCredential, str]:
        actor = self._manager(agency_id, write=True)
        if not grants or not 1 <= expires_in_days <= 90 or len(name.strip()) > 100:
            raise ValueError("Provide client grants, a name up to 100 characters, and 1-90 days.")
        if kind not in {"read", "ingest"} or (
            kind == "ingest" and any(grant.can_view_financials for grant in grants)
        ):
            raise ValueError("Ingest keys cannot read financial data.")
        self._check_grants(agency_id, grants)
        raw = "tsk_" + new_token()
        item = ServiceCredential(
            agency_id=agency_id,
            creator_membership_id=actor.id,
            name=self._name(name),
            kind=kind,
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

    # List service key metadata for Owner/Admin managers in creation order.
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

    # Revoke an active key under the agency write lock and a credential row lock; audited.
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
