"""Managed-link administration and redirect resolution (specification 005-B, D-033).

Owner/Admin managers mutate campaigns, content references, UTM templates, destination origins,
custom domains, and links of an active client; every mutation is audited with object IDs only.
Readers are authorized by the caller with resolve_scope (client:read) before the list helpers.

Loop prevention: a destination may never be served by the platform itself. Registering or
re-enabling a destination origin, claiming a domain, and activating a verified domain all take
one global host-namespace advisory lock and then check the other side, so two concurrent
configuration changes cannot together create a managed-host loop. Lock order: the agency row
lock (manager write) first, then the host-namespace lock, then link rows. Collection never takes
the host-namespace lock, and the namespace lock is never taken while a client privacy lock is
held.

Redirect resolution reads only: it writes no event, counter, cookie, subject, or click row, and
never performs DNS, TLS, or HTTP requests.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.links.policy import (
    CAMPAIGN_CODE,
    CONTENT_CODE,
    SLUG,
    LinkRuleError,
    Origin,
    canonical_hostname,
    canonical_origin,
    compose_target,
    destination_origin,
    is_managed_target,
    merge_utm,
    parse_destination,
    platform_authorities,
    request_authority,
    validate_query_names,
    validate_slug,
    validate_utm,
)
from app.links.verification import CERTIFICATE_MARGIN, CheckResult
from app.models import (
    Agency,
    ClientWorkspace,
    LinkCampaign,
    LinkContentReference,
    LinkDestinationOrigin,
    LinkDomain,
    LinkUtmTemplate,
    ManagedLink,
)
from app.services.tenancy import AccessDenied, TenancyService

HOST_NAMESPACE = 5005
HOST_LOCK_KEY = 1
LOCK_TIMEOUT = "2s"
CHALLENGE_LIFETIME = timedelta(hours=24)
VERIFICATION_LIFETIME = timedelta(hours=24)
CHALLENGE_LABEL = "_tracking-verification"
CHALLENGE_PREFIX = "tracking-verification="
PAGE_DEFAULT, PAGE_MAX = 50, 100


# A configuration change that would make the platform serve one of its own destinations, or
# claim a hostname another configuration already uses. The API maps it to 409 host_conflict.
class LinkConflict(Exception):
    def __init__(self, code: str = "host_conflict") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class IssuedChallenge:
    domain: LinkDomain
    record_name: str
    record_value: str


def challenge_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def database_now(session: Session) -> datetime:
    return session.scalar(select(func.clock_timestamp()))


# Serialize every change to the managed-host namespace (origins, domains, activation).
def lock_host_namespace(session: Session) -> None:
    session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    session.execute(select(func.pg_advisory_xact_lock(HOST_NAMESPACE, HOST_LOCK_KEY)))


def _same_authority(a: tuple[str, int | None], b: tuple[str, int | None]) -> bool:
    if a[0] != b[0]:
        return False
    ports = {a[1], b[1]}
    return len(ports) == 1 or ports <= {None, 443} or ports <= {None, 80}


def is_platform_authority(settings: Settings, authority: tuple[str, int | None]) -> bool:
    return any(
        _same_authority(authority, item)
        for item in platform_authorities(settings.link_platform_hosts)
    )


# True when a destination origin would be served by the platform: a platform short-link
# authority or any claimed custom hostname of any client, whatever its status.
def origin_is_managed(session: Session, settings: Settings, origin: Origin) -> bool:
    claimed = session.scalars(
        select(LinkDomain.hostname).where(LinkDomain.hostname == origin.hostname)
    ).all()
    return is_managed_target(origin, platform_authorities(settings.link_platform_hosts), claimed)


# True when a hostname may not be claimed or activated as a custom domain: a platform host, or
# the host of any registered destination origin of any client.
def hostname_conflicts(session: Session, settings: Settings, hostname: str) -> bool:
    platform = platform_authorities(settings.link_platform_hosts)
    if any(host == hostname for host, _ in platform):
        return True
    return bool(session.scalar(select(exists().where(LinkDestinationOrigin.hostname == hostname))))


def _text(value: str, maximum: int) -> str:
    value = value.strip()
    if not value or len(value) > maximum or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("A label must contain between 1 and the allowed number of characters.")
    return value


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= PAGE_MAX or not 0 <= offset <= 100000:
        raise ValueError("Use a page size of 1-100.")
    return limit, offset


def list_scoped(
    session: Session,
    model,
    agency_id: UUID,
    client_id: UUID,
    *,
    limit: int = PAGE_DEFAULT,
    offset: int = 0,
):
    limit, offset = _page(limit, offset)
    return list(
        session.scalars(
            select(model)
            .where(model.agency_id == agency_id, model.client_id == client_id)
            .order_by(model.created_at, model.id)
            .limit(limit)
            .offset(offset)
        )
    )


# Owner/Admin administration of managed-link resources; audited in the caller's transaction.
class LinkAdmin(TenancyService):
    def __init__(self, session: Session, actor_user_id: UUID, settings: Settings) -> None:
        super().__init__(session, actor_user_id)
        self.settings = settings

    def _write(self, agency_id: UUID, client_id: UUID) -> None:
        self._manager(agency_id, write=True)
        self.get_client(agency_id, client_id)

    def _row(self, model, agency_id: UUID, client_id: UUID, identifier: UUID):
        item = self.session.scalar(
            select(model)
            .where(
                model.agency_id == agency_id, model.client_id == client_id, model.id == identifier
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            raise AccessDenied()
        return item

    @staticmethod
    def _status(value: str | None, allowed: set[str]) -> str | None:
        if value is not None and value not in allowed:
            raise ValueError("Invalid status.")
        return value

    # Campaigns: immutable public code, editable label and status.
    def create_campaign(
        self, agency_id: UUID, client_id: UUID, *, public_code: str, label: str
    ) -> LinkCampaign:
        self._write(agency_id, client_id)
        if not isinstance(public_code, str) or not CAMPAIGN_CODE.fullmatch(public_code):
            raise ValueError("Invalid campaign code.")
        item = LinkCampaign(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            public_code=public_code,
            label=_text(label, 100),
        )
        self.session.add(item)
        self._audit(agency_id, "campaign.created", "campaign", item.id, client_id)
        return item

    def update_campaign(
        self,
        agency_id: UUID,
        client_id: UUID,
        campaign_id: UUID,
        *,
        label: str | None = None,
        status: str | None = None,
    ) -> LinkCampaign:
        self._write(agency_id, client_id)
        item = self._row(LinkCampaign, agency_id, client_id, campaign_id)
        if label is not None:
            item.label = _text(label, 100)
        if self._status(status, {"active", "archived"}) is not None:
            item.status = status
        self._audit(agency_id, "campaign.updated", "campaign", item.id, client_id)
        return item

    # Content references: immutable external code, editable platform label and status.
    def create_content(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        external_code: str,
        platform_label: str | None = None,
    ) -> LinkContentReference:
        self._write(agency_id, client_id)
        if not isinstance(external_code, str) or not CONTENT_CODE.fullmatch(external_code):
            raise ValueError("Invalid content reference code.")
        item = LinkContentReference(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            external_code=external_code,
            platform_label=_text(platform_label, 64) if platform_label is not None else None,
        )
        self.session.add(item)
        self._audit(agency_id, "content.created", "content_reference", item.id, client_id)
        return item

    def update_content(
        self,
        agency_id: UUID,
        client_id: UUID,
        content_id: UUID,
        *,
        platform_label: str | None = None,
        status: str | None = None,
    ) -> LinkContentReference:
        self._write(agency_id, client_id)
        item = self._row(LinkContentReference, agency_id, client_id, content_id)
        if platform_label is not None:
            item.platform_label = _text(platform_label, 64)
        if self._status(status, {"active", "archived"}) is not None:
            item.status = status
        self._audit(agency_id, "content.updated", "content_reference", item.id, client_id)
        return item

    # UTM templates: a parameter change increases revision; issued links keep their snapshot.
    def create_template(
        self, agency_id: UUID, client_id: UUID, *, name: str, parameters: dict[str, str]
    ) -> LinkUtmTemplate:
        self._write(agency_id, client_id)
        item = LinkUtmTemplate(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            name=_text(name, 100),
            parameters=validate_utm(parameters, required=True),
            revision=1,
        )
        self.session.add(item)
        self._audit(agency_id, "template.created", "utm_template", item.id, client_id)
        return item

    def update_template(
        self,
        agency_id: UUID,
        client_id: UUID,
        template_id: UUID,
        *,
        parameters: dict[str, str] | None = None,
        status: str | None = None,
    ) -> LinkUtmTemplate:
        self._write(agency_id, client_id)
        item = self._row(LinkUtmTemplate, agency_id, client_id, template_id)
        if parameters is not None:
            item.parameters = validate_utm(parameters, required=True)
            item.revision += 1
        if self._status(status, {"active", "archived"}) is not None:
            item.status = status
        self._audit(agency_id, "template.updated", "utm_template", item.id, client_id)
        return item

    # Destination origins: exact, explicitly registered, never served by the platform itself.
    def create_origin(
        self, agency_id: UUID, client_id: UUID, *, origin: str, query_names: list[str]
    ) -> LinkDestinationOrigin:
        self._write(agency_id, client_id)
        parsed = canonical_origin(
            origin, allow_loopback=self.settings.link_allow_loopback_destinations
        )
        names = validate_query_names(query_names)
        lock_host_namespace(self.session)
        if origin_is_managed(self.session, self.settings, parsed):
            raise LinkConflict()
        item = LinkDestinationOrigin(
            id=uuid4(),
            agency_id=agency_id,
            client_id=client_id,
            origin=parsed.text,
            hostname=parsed.hostname,
            query_names=names,
        )
        self.session.add(item)
        self._audit(agency_id, "origin.created", "destination_origin", item.id, client_id)
        return item

    def update_origin(
        self,
        agency_id: UUID,
        client_id: UUID,
        origin_id: UUID,
        *,
        query_names: list[str] | None = None,
        status: str | None = None,
    ) -> LinkDestinationOrigin:
        self._write(agency_id, client_id)
        self._status(status, {"active", "disabled"})
        if status == "active":
            lock_host_namespace(self.session)
        item = self._row(LinkDestinationOrigin, agency_id, client_id, origin_id)
        if query_names is not None:
            item.query_names = validate_query_names(query_names)
        if status == "active" and item.status != "active":
            parsed = canonical_origin(
                item.origin, allow_loopback=self.settings.link_allow_loopback_destinations
            )
            if origin_is_managed(self.session, self.settings, parsed):
                raise LinkConflict()
        if status is not None:
            item.status = status
        self._audit(agency_id, "origin.updated", "destination_origin", item.id, client_id)
        return item

    # Custom domains: a globally unique hostname reserved to one client. Claiming one never
    # verifies it; see app.links.verification.
    def create_domain(self, agency_id: UUID, client_id: UUID, *, hostname: str) -> LinkDomain:
        self._write(agency_id, client_id)
        host = canonical_hostname(hostname)
        lock_host_namespace(self.session)
        if hostname_conflicts(self.session, self.settings, host):
            raise LinkConflict()
        item = LinkDomain(id=uuid4(), agency_id=agency_id, client_id=client_id, hostname=host)
        self.session.add(item)
        self._audit(agency_id, "domain.created", "domain", item.id, client_id)
        return item

    # Disabling revokes a domain immediately; the hostname stays reserved to this client.
    def disable_domain(self, agency_id: UUID, client_id: UUID, domain_id: UUID) -> LinkDomain:
        self._write(agency_id, client_id)
        item = self._row(LinkDomain, agency_id, client_id, domain_id)
        item.status = "disabled"
        item.version += 1
        self._audit(agency_id, "domain.updated", "domain", item.id, client_id)
        return item

    # Issue a new 256-bit ownership challenge; the raw value is returned once and only its
    # SHA-256 digest is stored. Reissue invalidates every earlier challenge and verification.
    def issue_challenge(self, agency_id: UUID, client_id: UUID, domain_id: UUID) -> IssuedChallenge:
        self._write(agency_id, client_id)
        item = self._row(LinkDomain, agency_id, client_id, domain_id)
        raw = secrets.token_urlsafe(32)
        now = database_now(self.session)
        item.challenge_digest = challenge_digest(raw)
        item.challenge_expires_at = now + CHALLENGE_LIFETIME
        item.challenge_generation += 1
        item.status = "pending"
        item.verified_at = None
        item.verification_expires_at = None
        item.certificate_expires_at = None
        item.failure_code = None
        item.version += 1
        self._audit(agency_id, "domain.challenge_issued", "domain", item.id, client_id)
        return IssuedChallenge(
            item, f"{CHALLENGE_LABEL}.{item.hostname}", f"{CHALLENGE_PREFIX}{raw}"
        )

    def _active(self, model, agency_id: UUID, client_id: UUID, identifier: UUID | None):
        if identifier is None:
            return None
        item = self.session.scalar(
            select(model).where(
                model.agency_id == agency_id,
                model.client_id == client_id,
                model.id == identifier,
                model.status == "active",
            )
        )
        if item is None:
            raise ValueError("The referenced resource is not active in this client.")
        return item

    # Issue a link. The destination must fall under an active registered origin of this client;
    # campaign, content, and template must be active. The issued target URL, UTM snapshot,
    # and provenance never change afterwards.
    def create_link(
        self,
        agency_id: UUID,
        client_id: UUID,
        *,
        slug: str,
        destination: str,
        domain_id: UUID | None = None,
        utm: dict[str, str] | None = None,
        template_id: UUID | None = None,
        campaign_id: UUID | None = None,
        content_reference_id: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> ManagedLink:
        self._write(agency_id, client_id)
        validate_slug(slug)
        loopback = self.settings.link_allow_loopback_destinations
        parts_origin = destination_origin(destination, allow_loopback=loopback)
        origin = self.session.scalar(
            select(LinkDestinationOrigin).where(
                LinkDestinationOrigin.agency_id == agency_id,
                LinkDestinationOrigin.client_id == client_id,
                LinkDestinationOrigin.origin == parts_origin.text,
                LinkDestinationOrigin.status == "active",
            )
        )
        if origin is None:
            raise LinkRuleError("origin_not_registered")
        parsed = parse_destination(
            destination, parts_origin, origin.query_names, allow_loopback=loopback
        )
        domain = None
        if domain_id is not None:
            domain = self._row(LinkDomain, agency_id, client_id, domain_id)
            if domain.status == "disabled":
                raise ValueError("The domain is disabled.")
        template = self._active(LinkUtmTemplate, agency_id, client_id, template_id)
        campaign = self._active(LinkCampaign, agency_id, client_id, campaign_id)
        content = self._active(LinkContentReference, agency_id, client_id, content_reference_id)
        now = database_now(self.session)
        if expires_at is not None and expires_at <= now:
            raise ValueError("A link expiry must be in the future.")
        merged = merge_utm(
            parsed.utm,
            template.parameters if template is not None else None,
            utm,
            campaign.public_code if campaign is not None else None,
        )
        link_id = uuid4()
        bare = f"{parsed.origin.text}{parsed.path}"
        if parsed.static:
            bare += "?" + "&".join(f"{name}={value}" for name, value in parsed.static)
        item = ManagedLink(
            id=link_id,
            agency_id=agency_id,
            client_id=client_id,
            domain_id=domain.id if domain is not None else None,
            slug=slug,
            origin_id=origin.id,
            destination=bare,
            utm=merged,
            target_url=compose_target(parsed, merged, link_id),
            campaign_id=campaign.id if campaign is not None else None,
            content_reference_id=content.id if content is not None else None,
            template_id=template.id if template is not None else None,
            template_revision=template.revision if template is not None else None,
            expires_at=expires_at,
        )
        self.session.add(item)
        self._audit(agency_id, "link.created", "link", item.id, client_id)
        return item

    # Status and expiry are the only mutable link fields.
    def update_link(
        self,
        agency_id: UUID,
        client_id: UUID,
        link_id: UUID,
        *,
        status: str | None = None,
        expires_at: datetime | None = None,
        clear_expiry: bool = False,
    ) -> ManagedLink:
        self._write(agency_id, client_id)
        item = self._row(ManagedLink, agency_id, client_id, link_id)
        if self._status(status, {"active", "disabled"}) is not None:
            item.status = status
        if clear_expiry:
            item.expires_at = None
        elif expires_at is not None:
            if expires_at <= database_now(self.session):
                raise ValueError("A link expiry must be in the future.")
            item.expires_at = expires_at
        self._audit(agency_id, "link.updated", "link", item.id, client_id)
        return item


# Values read before the network phase of a domain check; completion compares them again.
@dataclass(frozen=True)
class DomainSnapshot:
    hostname: str
    challenge_digest: str
    generation: int
    version: int
    expired: bool


# Phase 1 of a domain check (a short transaction): authorize an Owner/Admin of the active client
# and read the domain's current challenge. The network phase runs after this commits.
def begin_verification(
    session: Session,
    settings: Settings,
    actor_user_id: UUID,
    agency_id: UUID,
    client_id: UUID,
    domain_id: UUID,
) -> DomainSnapshot:
    admin = LinkAdmin(session, actor_user_id, settings)
    admin._manager(agency_id)
    admin.get_client(agency_id, client_id)
    domain = session.scalar(
        select(LinkDomain).where(
            LinkDomain.agency_id == agency_id,
            LinkDomain.client_id == client_id,
            LinkDomain.id == domain_id,
        )
    )
    if domain is None:
        raise AccessDenied()
    if domain.status == "disabled" or domain.challenge_digest is None:
        raise ValueError("Issue a challenge for an enabled domain before verifying it.")
    return DomainSnapshot(
        domain.hostname,
        domain.challenge_digest,
        domain.challenge_generation,
        domain.version,
        domain.challenge_expires_at <= database_now(session),
    )


# Phase 3 of a domain check: re-authorize the actor under the agency write lock, take the
# host-namespace lock and the domain row, and apply the result only if nothing changed since
# phase 1 (no disablement, reissued challenge, or other completed check). A stale result changes
# nothing. Success needs an unexpired challenge and no managed-host conflict; it is valid for at
# most 24 hours and ends one hour before the observed certificate expiry. A failure records its
# closed code and never extends an earlier verification deadline.
def complete_verification(
    session: Session,
    settings: Settings,
    actor_user_id: UUID,
    agency_id: UUID,
    client_id: UUID,
    domain_id: UUID,
    snapshot: DomainSnapshot,
    result: CheckResult,
) -> tuple[LinkDomain, str]:
    admin = LinkAdmin(session, actor_user_id, settings)
    admin._write(agency_id, client_id)
    lock_host_namespace(session)
    domain = admin._row(LinkDomain, agency_id, client_id, domain_id)
    current = (domain.version, domain.challenge_generation, domain.challenge_digest)
    expected = (snapshot.version, snapshot.generation, snapshot.challenge_digest)
    if current != expected or domain.status == "disabled":
        return domain, "stale"
    now = database_now(session)
    failure = result.failure
    if failure is None and domain.challenge_expires_at <= now:
        failure = "challenge_expired"
    if failure is None and hostname_conflicts(session, settings, domain.hostname):
        failure = "host_conflict"
    domain.last_checked_at = now
    domain.version += 1
    if failure is None and result.certificate_expires_at is not None:
        domain.status = "verified"
        domain.verified_at = now
        domain.certificate_expires_at = result.certificate_expires_at
        domain.verification_expires_at = min(
            now + VERIFICATION_LIFETIME, result.certificate_expires_at - CERTIFICATE_MARGIN
        )
        domain.failure_code = None
    else:
        domain.failure_code = failure or "verification_unavailable"
    admin._audit(agency_id, "domain.checked", "domain", domain.id, client_id)
    return domain, "verified" if domain.failure_code is None else "failed"


@dataclass(frozen=True)
class RedirectTarget:
    url: str
    link_id: UUID


# Resolve a short link by the request's Host header and the exact slug. Platform authorities
# resolve links without a domain; any other host must be a verified custom domain whose
# verification is current, on the configured custom-domain port. Missing, disabled, expired,
# or out-of-scope records all return None. Forwarded-host headers are never consulted.
def resolve_redirect(
    session: Session, settings: Settings, host_header: str | None, slug: str
) -> RedirectTarget | None:
    authority = request_authority(host_header)
    if authority is None or not SLUG.fullmatch(slug):
        return None
    query = (
        select(ManagedLink.target_url, ManagedLink.id, LinkDestinationOrigin.origin)
        .join(
            LinkDestinationOrigin,
            (LinkDestinationOrigin.id == ManagedLink.origin_id)
            & (LinkDestinationOrigin.client_id == ManagedLink.client_id),
        )
        .join(
            ClientWorkspace,
            (ClientWorkspace.agency_id == ManagedLink.agency_id)
            & (ClientWorkspace.id == ManagedLink.client_id),
        )
        .join(Agency, Agency.id == ManagedLink.agency_id)
        .where(
            ManagedLink.slug == slug,
            ManagedLink.status == "active",
            (ManagedLink.expires_at.is_(None)) | (ManagedLink.expires_at > func.now()),
            LinkDestinationOrigin.status == "active",
            ClientWorkspace.status == "active",
            Agency.status == "active",
        )
    )
    if is_platform_authority(settings, authority):
        query = query.where(ManagedLink.domain_id.is_(None))
    else:
        hostname, port = authority
        expected = settings.link_custom_domain_port
        if not (port == expected or (port is None and expected == 443)):
            return None
        query = query.join(
            LinkDomain,
            (LinkDomain.id == ManagedLink.domain_id)
            & (LinkDomain.client_id == ManagedLink.client_id),
        ).where(
            LinkDomain.hostname == hostname,
            LinkDomain.status == "verified",
            LinkDomain.verification_expires_at > func.now(),
        )
    row = session.execute(query).first()
    if row is None:
        return None
    try:
        origin = canonical_origin(
            row.origin, allow_loopback=settings.link_allow_loopback_destinations
        )
    except LinkRuleError:
        return None
    # Defense in depth: a later configuration change can never make a link loop.
    if origin_is_managed(session, settings, origin):
        return None
    return RedirectTarget(row.target_url, row.id)
