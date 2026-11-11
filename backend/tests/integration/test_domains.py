"""Specification 005-E custom-domain verification through the API (D-033).

DNS answers are synthetic and injected; TLS runs against loopback servers presenting synthetic
certificates from a test-only authority. This is synthetic verification of the implemented
logic, not live DNS, certificate issuance, or custom-domain operation.
"""

import hashlib
import ssl
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import dns.resolver
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.links.verification import (
    CHALLENGE_PREFIX,
    DnsResolver,
    DomainVerifier,
    PinnedTlsProbe,
)
from app.models import AuditEvent, LinkDestinationOrigin, LinkDomain
from app.security import now_utc

pytestmark = pytest.mark.integration

HOST = "go.brand.test"
TARGET = "links.platform.test"
SHOP = "https://shop.example.test"


class ZoneResolver:
    """Synthetic DNS: answers from a mutable zone and runs an optional hook on the TXT query."""

    def __init__(self):
        self.txt_values: list[str] = []
        self.cnames = {HOST: TARGET}
        self.address_list = ["127.0.0.1"]
        self.hook = None
        self.queries = 0

    def txt(self, name, timeout):
        self.queries += 1
        if self.hook is not None:
            hook, self.hook = self.hook, None
            hook()
        return list(self.txt_values) if name == f"_tracking-verification.{HOST}" else []

    def cname(self, name, timeout):
        return self.cnames.get(name)

    def addresses(self, name, timeout):
        return list(self.address_list)


def domain_row(db, domain_id) -> LinkDomain:
    with Session(db.migration) as session:
        return session.get(LinkDomain, UUID(str(domain_id)))


@pytest.fixture
def dom(authenticated_world, api, synthetic_pki, tls_server):
    w = authenticated_world
    certificate = synthetic_pki.issue(HOST, valid_for=timedelta(days=10))
    server = tls_server(certificate)
    resolver = ZoneResolver()
    verifier = DomainVerifier(
        resolver,
        PinnedTlsProbe(port=server.port, context_factory=synthetic_pki.context),
        address_allowed=lambda address: address == "127.0.0.1",
    )
    config = api.config.model_copy(update={"link_service_target": TARGET})

    def signed_in(name, settings=config):
        client = api.new_client(settings)
        client.app.state.domain_verifier = verifier
        api.login(client, f"{name}@example.test")
        return client

    owner = signed_in("owner_a")
    path = f"/agencies/{w.a}/clients/{w.a1}"
    claimed = owner.post(f"{path}/link-domains", json={"hostname": HOST})
    assert claimed.status_code == 201, claimed.text
    domain_id = claimed.json()["id"]

    def challenge(client=owner):
        issued = client.post(f"{path}/link-domains/{domain_id}/challenge")
        assert issued.status_code == 201, issued.text
        body = issued.json()
        assert body["record_name"] == f"_tracking-verification.{HOST}"
        assert body["cname_target"] == TARGET
        resolver.txt_values = [body["record_value"]]
        return body

    def verify(client=owner):
        return client.post(f"{path}/link-domains/{domain_id}/verify")

    return SimpleNamespace(
        w=w,
        api=api,
        db=w.db,
        config=config,
        owner=owner,
        signed_in=signed_in,
        path=path,
        domain_id=domain_id,
        resolver=resolver,
        server=server,
        certificate=certificate,
        synthetic_pki=synthetic_pki,
        tls_server=tls_server,
        verifier=verifier,
        challenge=challenge,
        verify=verify,
    )


def test_verified_domain_resolves_its_links_and_stores_no_challenge(dom, capfd):
    issued = dom.challenge()
    raw = issued["record_value"][len(CHALLENGE_PREFIX) :]
    assert len(raw) >= 43
    stored = domain_row(dom.db, dom.domain_id)
    assert stored.challenge_digest == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in str(vars(stored))
    started = now_utc()
    response = dom.verify()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "verified"
    assert body["domain"]["status"] == "verified" and body["domain"]["failure_code"] is None
    assert dom.server.names == [HOST] and dom.server.data == [b""]
    row = domain_row(dom.db, dom.domain_id)
    certificate_bound = row.certificate_expires_at - timedelta(hours=1)
    assert row.verification_expires_at == min(
        row.verified_at + timedelta(hours=24), certificate_bound
    )
    assert row.verification_expires_at <= started + timedelta(hours=24, minutes=1)
    origin = dom.owner.post(f"{dom.path}/link-destination-origins", json={"origin": SHOP})
    assert origin.status_code == 201
    link = dom.owner.post(
        f"{dom.path}/managed-links",
        json={"slug": "brand-offer", "destination": f"{SHOP}/offer", "domain_id": dom.domain_id},
    )
    assert link.status_code == 201
    branded = dom.api.new_client()
    branded.base_url = f"https://{HOST}"
    redirect = branded.get("/r/brand-offer", follow_redirects=False)
    assert (redirect.status_code, redirect.headers["location"]) == (302, link.json()["target_url"])
    with Session(dom.db.migration) as session:
        actions = set(
            session.scalars(select(AuditEvent.action).where(AuditEvent.resource_id == row.id))
        )
    assert actions == {"domain.created", "domain.challenge_issued", "domain.checked"}
    assert raw not in "".join(capfd.readouterr())
    listed = dom.owner.get(f"{dom.path}/link-domains").json()
    assert raw not in str(listed) and "challenge_digest" not in listed[0]


@pytest.mark.parametrize(
    ("change", "failure"),
    [
        ("no_txt", "ownership_missing"),
        ("wrong_txt", "ownership_missing"),
        ("cname_elsewhere", "routing_mismatch"),
        ("cname_loop", "routing_mismatch"),
        ("private_address", "address_not_allowed"),
        ("mixed_addresses", "address_not_allowed"),
        ("wrong_certificate", "tls_invalid"),
        ("untrusted_certificate", "tls_invalid"),
        ("expired_certificate", "tls_invalid"),
        ("expiring_certificate", "tls_invalid"),
    ],
)
def test_failed_checks_never_activate_a_domain(dom, change, failure):
    dom.challenge()
    pki = dom.synthetic_pki
    certificate = {
        "wrong_certificate": lambda: pki.issue("other.example.test"),
        "untrusted_certificate": lambda: pki.issue(HOST, ca=pki.untrusted),
        "expired_certificate": lambda: pki.issue(
            HOST, valid_for=timedelta(hours=-1), age=timedelta(days=3)
        ),
        "expiring_certificate": lambda: pki.issue(HOST, valid_for=timedelta(minutes=30)),
    }.get(change)
    if certificate is not None:
        server = dom.tls_server(certificate())
        dom.verifier.tls = PinnedTlsProbe(port=server.port, context_factory=pki.context)
    if change == "no_txt":
        dom.resolver.txt_values = []
    elif change == "wrong_txt":
        dom.resolver.txt_values = [CHALLENGE_PREFIX + "not-the-challenge"]
    elif change == "cname_elsewhere":
        dom.resolver.cnames = {HOST: "elsewhere.example.test"}
    elif change == "cname_loop":
        dom.resolver.cnames = {HOST: "a.example.test", "a.example.test": HOST}
    elif change == "private_address":
        dom.verifier.address_allowed = lambda address: False
    elif change == "mixed_addresses":
        dom.resolver.address_list = ["127.0.0.1", "10.0.0.8"]
    response = dom.verify()
    assert response.status_code == 200
    assert response.json()["outcome"] == "failed"
    row = domain_row(dom.db, dom.domain_id)
    assert (row.status, row.failure_code, row.verified_at) == ("pending", failure, None)


def test_reissued_and_expired_challenges_do_not_verify(dom):
    old = dom.challenge()
    dom.challenge()
    dom.resolver.txt_values = [old["record_value"]]
    assert dom.verify().json()["domain"]["failure_code"] == "ownership_missing"
    dom.challenge()
    with Session(dom.db.migration) as session, session.begin():
        session.execute(
            text("UPDATE link_domains SET challenge_expires_at = now() - interval '1 second'")
        )
    queries = dom.resolver.queries
    response = dom.verify().json()
    assert (response["outcome"], response["domain"]["failure_code"]) == (
        "failed",
        "challenge_expired",
    )
    assert dom.resolver.queries == queries  # no network check for an expired challenge


def test_results_completing_after_concurrent_changes_are_stale(dom):
    dom.challenge()
    disabled = dom.signed_in("owner_a")
    dom.resolver.hook = lambda: disabled.patch(
        f"{dom.path}/link-domains/{dom.domain_id}", json={"status": "disabled"}
    )
    assert dom.verify().json()["outcome"] == "stale"
    assert domain_row(dom.db, dom.domain_id).status == "disabled"
    dom.challenge()
    rotated = dom.signed_in("owner_a")
    dom.resolver.hook = lambda: rotated.post(f"{dom.path}/link-domains/{dom.domain_id}/challenge")
    assert dom.verify().json()["outcome"] == "stale"
    assert domain_row(dom.db, dom.domain_id).status == "pending"
    dom.challenge()
    second = dom.signed_in("admin")
    dom.resolver.hook = lambda: second.post(f"{dom.path}/link-domains/{dom.domain_id}/verify")
    assert dom.verify().json()["outcome"] == "stale"
    assert domain_row(dom.db, dom.domain_id).status == "verified"


def test_a_revoked_actor_cannot_complete_a_check(dom):
    dom.challenge()
    admin = dom.signed_in("admin")
    dom.resolver.hook = lambda: dom.owner.patch(
        f"/agencies/{dom.w.a}/members/{dom.w.admin}", json={"status": "disabled"}
    )
    response = dom.verify(admin)
    assert (response.status_code, response.json()) == (403, {"error": "access_denied"})
    assert domain_row(dom.db, dom.domain_id).status == "pending"


def test_a_conflicting_origin_blocks_activation(dom):
    dom.challenge()

    def conflicting_origin():
        with Session(dom.db.migration) as session, session.begin():
            session.add(
                LinkDestinationOrigin(
                    id=uuid4(),
                    agency_id=dom.w.b,
                    client_id=dom.w.b1,
                    origin=f"https://{HOST}",
                    hostname=HOST,
                    query_names=[],
                )
            )

    dom.resolver.hook = conflicting_origin
    response = dom.verify().json()
    assert (response["outcome"], response["domain"]["failure_code"]) == ("failed", "host_conflict")
    assert domain_row(dom.db, dom.domain_id).status == "pending"


def test_checks_are_rate_limited_scoped_and_unavailable_when_disabled(dom):
    dom.challenge()
    dom.resolver.txt_values = []
    statuses = [dom.verify().status_code for _ in range(6)]
    assert statuses == [200] * 5 + [429]
    outsider = dom.signed_in("owner_b")
    assert dom.verify(outsider).status_code == 403
    analyst = dom.signed_in("analyst")
    assert dom.verify(analyst).status_code == 403
    disabled = dom.api.new_client(dom.config)
    assert disabled.app.state.domain_verifier is None
    dom.api.login(disabled, "owner_a@example.test")
    before = domain_row(dom.db, dom.domain_id).version
    response = dom.verify(disabled)
    assert (response.status_code, response.json()) == (503, {"error": "verification_unavailable"})
    assert domain_row(dom.db, dom.domain_id).version == before
    foreign = dom.owner.post(
        f"/agencies/{dom.w.a}/clients/{dom.w.a2}/link-domains/{dom.domain_id}/verify"
    )
    assert foreign.status_code == 403


def test_redirects_never_probe_dns_or_tls(dom, monkeypatch):
    dom.challenge()
    assert dom.verify().json()["outcome"] == "verified"
    dom.owner.post(f"{dom.path}/link-destination-origins", json={"origin": SHOP})
    link = dom.owner.post(
        f"{dom.path}/managed-links",
        json={"slug": "brand-offer", "destination": f"{SHOP}/offer", "domain_id": dom.domain_id},
    ).json()
    probes = []

    def forbidden(*args, **kwargs):
        probes.append(args)
        raise AssertionError("A redirect attempted a network probe.")

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", forbidden)
    monkeypatch.setattr(DnsResolver, "txt", forbidden)
    monkeypatch.setattr(PinnedTlsProbe, "certificate_expiry", forbidden)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", forbidden)
    dom.resolver.hook = forbidden
    branded = dom.api.new_client()
    branded.base_url = f"https://{HOST}"
    for _ in range(3):
        response = branded.get("/r/brand-offer", follow_redirects=False)
        assert response.headers["location"] == link["target_url"]
    assert probes == []
    with Session(dom.db.migration) as session, session.begin():
        session.execute(
            text("UPDATE link_domains SET verification_expires_at = now() - interval '1 second'")
        )
    assert branded.get("/r/brand-offer", follow_redirects=False).status_code == 404
    with Session(dom.db.migration) as session:
        assert session.scalar(select(func.count()).select_from(LinkDomain)) == 1


def test_equivalent_service_target_spellings_verify_identically(dom):
    for spelling in ("LINKS.PLATFORM.TEST", "Links.Platform.Test"):
        client = dom.signed_in(
            "owner_a", dom.config.model_copy(update={"link_service_target": spelling})
        )
        issued = client.post(f"{dom.path}/link-domains/{dom.domain_id}/challenge")
        dom.resolver.txt_values = [issued.json()["record_value"]]
        assert issued.json()["cname_target"] == spelling
        response = dom.verify(client).json()
        assert (response["outcome"], response["domain"]["failure_code"]) == ("verified", None)
