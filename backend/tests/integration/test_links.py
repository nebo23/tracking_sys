"""Specification 005-B managed links and redirects on disposable PostgreSQL (D-033).

Every case asserts stored rows (or their absence) as well as HTTP outcomes. Synthetic hosts
only; nothing is resolved or fetched.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT
from app.database import expected_revision
from app.main import create_app
from app.models import (
    AuditEvent,
    ClientWorkspace,
    CollectedEvent,
    CollectionSubject,
    EventDiagnostic,
    LinkDestinationOrigin,
    LinkDomain,
    ManagedLink,
    StoredConsentRecord,
)
from app.security import now_utc
from app.services import collection as collection_service
from app.services.links import LinkAdmin, LinkConflict

pytestmark = pytest.mark.integration

SHOP = "https://shop.example.test"
TELEMETRY = (CollectedEvent, EventDiagnostic, CollectionSubject, StoredConsentRecord)


def rows(db, query):
    with Session(db.migration) as session:
        return list(session.scalars(query))


def total(db, model, *conditions) -> int:
    with Session(db.migration) as session:
        return session.scalar(select(func.count()).select_from(model).where(*conditions))


@pytest.fixture
def links(authenticated_world, api):
    w = authenticated_world
    owner = w.signed_in("owner_a")
    path = f"/agencies/{w.a}/clients/{w.a1}"

    def post(resource, body, *, client=owner, status=201, scope=path):
        response = client.post(f"{scope}/{resource}", json=body)
        assert response.status_code == status, response.text
        return response.json()

    origin = post("link-destination-origins", {"origin": SHOP, "query_names": ["ref"]})
    campaign = post("link-campaigns", {"public_code": "spring-2026", "label": "Spring"})
    content = post(
        "link-content-references", {"external_code": "post:123", "platform_label": "Instagram"}
    )
    template = post(
        "link-utm-templates",
        {"name": "Social", "parameters": {"utm_source": "social", "utm_medium": "organic"}},
    )
    return SimpleNamespace(
        w=w,
        api=api,
        db=w.db,
        owner=owner,
        path=path,
        post=post,
        origin=origin,
        campaign=campaign,
        content=content,
        template=template,
    )


def new_link(links, slug="spring-offer", **extra):
    body = {
        "slug": slug,
        "destination": f"{SHOP}/offer?ref=spring&utm_source=destination",
        "template_id": links.template["id"],
        "campaign_id": links.campaign["id"],
        "content_reference_id": links.content["id"],
        "utm": {"utm_content": "hero"},
        **extra,
    }
    return links.post("managed-links", body)


def visit(client, slug, **kwargs):
    return client.get(f"/r/{slug}", follow_redirects=False, **kwargs)


def test_owner_and_admin_manage_readers_list_and_others_are_denied(links):
    w = links.w
    admin = w.signed_in("admin")
    link = new_link(links)
    second = links.post(
        "link-campaigns", {"public_code": "autumn", "label": "Autumn"}, client=admin
    )
    assert second["public_code"] == "autumn"
    analyst = w.signed_in("analyst")
    listed = analyst.get(f"{links.path}/managed-links")
    assert listed.status_code == 200 and [item["id"] for item in listed.json()] == [link["id"]]
    assert w.signed_in("viewer").get(f"{links.path}/link-campaigns").status_code == 200
    denied = [
        analyst.post(f"{links.path}/link-campaigns", json={"public_code": "x1", "label": "X"}),
        analyst.patch(f"{links.path}/managed-links/{link['id']}", json={"status": "disabled"}),
        w.signed_in("viewer").post(
            f"{links.path}/link-campaigns", json={"public_code": "x2", "label": "X"}
        ),
        w.signed_in("outsider").get(f"{links.path}/managed-links"),
        w.signed_in("owner_b").get(f"{links.path}/managed-links"),
        w.signed_in("owner_b").post(
            f"{links.path}/link-campaigns", json={"public_code": "x3", "label": "X"}
        ),
        analyst.get(f"/agencies/{w.a}/clients/{w.a2}/managed-links"),
    ]
    assert [response.status_code for response in denied] == [403] * len(denied)
    keys = {}
    for kind in ("read", "ingest"):
        issued = links.owner.post(
            f"/agencies/{w.a}/service-credentials",
            json={"name": kind, "kind": kind, "clients": [{"client_id": str(w.a1)}]},
        )
        assert issued.status_code == 201, issued.text
        keys[kind] = links.api.new_client()
        keys[kind].headers["Authorization"] = "Bearer " + issued.json()["key"]
    assert keys["read"].get(f"{links.path}/managed-links").status_code == 200
    assert keys["read"].post(f"{links.path}/managed-links", json={}).status_code == 401
    assert keys["ingest"].get(f"{links.path}/managed-links").status_code == 401
    member = links.owner.patch(f"/agencies/{w.a}/members/{w.admin}", json={"status": "disabled"})
    assert member.status_code == 200, member.text
    disabled = admin.post(f"{links.path}/link-campaigns", json={"public_code": "x4", "label": "X"})
    assert disabled.status_code == 403
    audits = rows(
        links.db,
        select(AuditEvent).where(AuditEvent.client_id == w.a1, AuditEvent.action.like("%.created")),
    )
    assert {item.action for item in audits} >= {
        "origin.created",
        "campaign.created",
        "content.created",
        "template.created",
        "link.created",
    }
    assert all(item.agency_id == w.a for item in audits)
    assert {item.resource_id for item in audits if item.action == "link.created"} == {
        UUID(link["id"])
    }


def test_redirect_issues_the_immutable_target_with_utm_precedence(links):
    link = new_link(links)
    target = urlsplit(link["target_url"])
    assert (target.scheme, target.netloc, target.path) == ("https", "shop.example.test", "/offer")
    assert parse_qsl(target.query) == [
        ("ref", "spring"),
        ("utm_content", "hero"),
        ("utm_id", "spring-2026"),
        ("utm_medium", "organic"),
        ("utm_source", "social"),
        ("ts_link", link["id"]),
    ]
    client = links.api.new_client()
    for response in (
        visit(client, "spring-offer"),
        visit(client, "spring-offer", params={"next": "https://evil.example.test", "ts_link": "x"}),
    ):
        assert response.status_code == 302
        assert response.headers["location"] == link["target_url"]
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "set-cookie" not in response.headers
    head = client.head("/r/spring-offer", follow_redirects=False)
    assert head.status_code == 302 and head.headers["location"] == link["target_url"]
    assert head.content == b""
    assert client.post("/r/spring-offer").status_code == 405
    changed = links.owner.patch(
        f"{links.path}/link-utm-templates/{links.template['id']}",
        json={"parameters": {"utm_source": "changed"}},
    )
    assert changed.status_code == 200 and changed.json()["revision"] == 2
    archived = links.owner.patch(
        f"{links.path}/link-campaigns/{links.campaign['id']}", json={"status": "archived"}
    )
    assert archived.status_code == 200
    assert visit(client, "spring-offer").headers["location"] == link["target_url"]
    [stored] = rows(links.db, select(ManagedLink))
    assert (stored.template_revision, stored.target_url) == (1, link["target_url"])
    second = new_link(links, "spring-offer-2", campaign_id=None)
    assert dict(parse_qsl(urlsplit(second["target_url"]).query))["utm_source"] == "changed"
    assert dict(parse_qsl(urlsplit(second["target_url"]).query))["ts_link"] == second["id"]


def test_link_provenance_columns_are_immutable_for_the_runtime(links):
    new_link(links)
    for statement in (
        "UPDATE managed_links SET target_url = 'https://evil.example.test/'",
        "UPDATE managed_links SET slug = 'other-slug'",
        "UPDATE managed_links SET campaign_id = NULL",
        "UPDATE link_domains SET hostname = 'x.example.test'",
        "UPDATE link_campaigns SET public_code = 'changed'",
        "UPDATE link_destination_origins SET origin = 'https://evil.example.test'",
        "DELETE FROM managed_links",
        "DELETE FROM link_domains",
    ):
        with pytest.raises(DBAPIError), links.db.runtime.begin() as connection:
            connection.execute(text(statement))


def test_unsafe_destinations_and_unregistered_origins_are_rejected(links):
    for destination in (
        "javascript:alert(1)",
        "http://shop.example.test/offer",
        "https://other.example.test/offer",
        "https://shop.example.test/offer?unknown=1",
        "https://shop.example.test/offer?ref=a&ref=b",
        "https://shop.example.test/u/someone@example.test",
        "https://shop.example.test/offer#x",
        "https://shop.example.test/a%2F..%2Fadmin",
    ):
        response = links.owner.post(
            f"{links.path}/managed-links", json={"slug": "unsafe-1", "destination": destination}
        )
        assert response.status_code == 422, destination
    for origin in ("http://shop.example.test", "https://10.0.0.1", "https://printer.local"):
        response = links.owner.post(
            f"{links.path}/link-destination-origins", json={"origin": origin}
        )
        assert response.status_code == 422, origin
    foreign = links.post(
        "link-campaigns",
        {"public_code": "other", "label": "Other"},
        scope=f"/agencies/{links.w.a}/clients/{links.w.a2}",
    )
    response = links.owner.post(
        f"{links.path}/managed-links",
        json={"slug": "foreign-ref", "destination": f"{SHOP}/x", "campaign_id": foreign["id"]},
    )
    assert response.status_code == 422
    assert total(links.db, ManagedLink) == 0


def raw_link(links, origin_id, slug):
    return ManagedLink(
        id=uuid4(),
        agency_id=links.w.a,
        client_id=links.w.a1,
        slug=slug,
        origin_id=origin_id,
        destination=f"{SHOP}/x",
        utm={},
        target_url=f"{SHOP}/x",
    )


def wait_for_lock_wait(db, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with db.migration.connect() as connection:
            waiting = connection.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'transactionid' AND NOT granted"
                )
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("No transaction waited for the lock.")


def test_concurrent_duplicate_slugs_have_one_winner(links):
    first = links.post("managed-links", {"slug": "race-slug", "destination": f"{SHOP}/x"})
    admin = links.w.signed_in("admin")
    duplicate = admin.post(
        f"{links.path}/managed-links", json={"slug": "race-slug", "destination": f"{SHOP}/y"}
    )
    assert (duplicate.status_code, duplicate.json()) == (409, {"error": "state_conflict"})
    [origin] = rows(links.db, select(LinkDestinationOrigin))
    # Two uncoordinated writers that bypass the service's agency lock: the database unique
    # index alone decides, so the second insert waits for the first and then fails.
    with Session(links.db.runtime) as holder:
        holder.begin()
        holder.add(raw_link(links, origin.id, "raw-race"))
        holder.flush()

        def contender():
            with Session(links.db.runtime) as session, session.begin():
                session.add(raw_link(links, origin.id, "raw-race"))

        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(contender)
            wait_for_lock_wait(links.db)
            assert not pending.done()
            holder.commit()
            with pytest.raises(IntegrityError):
                pending.result(timeout=10)
    assert total(links.db, ManagedLink, ManagedLink.slug == "raw-race") == 1
    # Service-level writers in two threads serialize on the agency lock; one wins.
    barrier = threading.Barrier(2)

    def create(user_id):
        barrier.wait()
        try:
            with Session(links.db.runtime) as session, session.begin():
                LinkAdmin(session, user_id, links.api.config).create_link(
                    links.w.a, links.w.a1, slug="service-race", destination=f"{SHOP}/x"
                )
            return "created"
        except IntegrityError:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        outcomes = sorted(pool.map(create, [links.w.users.owner_a, links.w.users.admin]))
    assert outcomes == ["conflict", "created"]
    links.owner.patch(f"{links.path}/managed-links/{first['id']}", json={"status": "disabled"})
    reused = links.owner.post(
        f"{links.path}/managed-links", json={"slug": "race-slug", "destination": f"{SHOP}/y"}
    )
    assert reused.status_code == 409  # disabled slugs are never recycled


def mark_verified(db, domain_id, *, expires_in=timedelta(hours=1)):
    now = now_utc()
    with Session(db.migration) as session, session.begin():
        session.execute(
            update(LinkDomain)
            .where(LinkDomain.id == domain_id)
            .values(status="verified", verified_at=now, verification_expires_at=now + expires_in)
        )


def test_managed_hosts_cannot_become_destinations_and_hosts_resolve_exactly(links):
    w = links.w
    platform = links.owner.post(
        f"{links.path}/link-destination-origins", json={"origin": "https://localhost:8000"}
    )
    assert platform.status_code == 422  # HTTPS on a non-default port is never registered
    domain = links.post("link-domains", {"hostname": "Go.Brand.Test"})
    assert domain["hostname"] == "go.brand.test" and domain["status"] == "pending"
    conflict = links.owner.post(
        f"{links.path}/link-destination-origins", json={"origin": "https://go.brand.test"}
    )
    assert (conflict.status_code, conflict.json()) == (409, {"error": "host_conflict"})
    owner_b = w.signed_in("owner_b")
    b_path = f"/agencies/{w.b}/clients/{w.b1}"
    claimed = owner_b.post(f"{b_path}/link-domains", json={"hostname": "go.brand.test"})
    assert claimed.status_code == 409
    shop_claim = owner_b.post(f"{b_path}/link-domains", json={"hostname": "shop.example.test"})
    assert (shop_claim.status_code, shop_claim.json()) == (409, {"error": "host_conflict"})
    link = new_link(links, "brand-offer", domain_id=domain["id"])
    branded = links.api.new_client()
    branded.base_url = "https://go.brand.test"
    assert visit(branded, "brand-offer").status_code == 404  # pending: never redirects
    mark_verified(links.db, UUID(domain["id"]))
    assert visit(branded, "brand-offer").headers["location"] == link["target_url"]
    platform_client = links.api.new_client()
    assert visit(platform_client, "brand-offer").status_code == 404  # domain links need the host
    spoofed = visit(platform_client, "brand-offer", headers={"X-Forwarded-Host": "go.brand.test"})
    assert spoofed.status_code == 404
    other_port = links.api.new_client()
    other_port.base_url = "http://go.brand.test:8080"
    assert visit(other_port, "brand-offer").status_code == 404
    links.owner.patch(f"{links.path}/link-domains/{domain['id']}", json={"status": "disabled"})
    assert visit(branded, "brand-offer").status_code == 404
    reclaim = links.owner.post(f"{links.path}/link-domains", json={"hostname": "go.brand.test"})
    assert reclaim.status_code == 409  # the disabled hostname stays reserved


def test_expired_verification_and_disabled_or_expired_links_fail_closed(links):
    domain = links.post("link-domains", {"hostname": "go.brand.test"})
    new_link(links, "brand-offer", domain_id=domain["id"])
    mark_verified(links.db, UUID(domain["id"]), expires_in=timedelta(seconds=-1))
    branded = links.api.new_client()
    branded.base_url = "https://go.brand.test"
    assert visit(branded, "brand-offer").status_code == 404
    link = new_link(links, "plain-offer")
    client = links.api.new_client()
    assert visit(client, "plain-offer").status_code == 302
    soon = (now_utc() + timedelta(days=1)).isoformat()
    assert links.owner.patch(
        f"{links.path}/managed-links/{link['id']}", json={"expires_at": soon}
    ).json()["expires_at"]
    with Session(links.db.migration) as session, session.begin():
        session.execute(
            update(ManagedLink)
            .where(ManagedLink.id == UUID(link["id"]))
            .values(expires_at=now_utc() - timedelta(seconds=1))
        )
    assert visit(client, "plain-offer").status_code == 404
    cleared = links.owner.patch(
        f"{links.path}/managed-links/{link['id']}", json={"expires_at": None}
    )
    assert cleared.status_code == 200 and cleared.json()["expires_at"] is None
    assert visit(client, "plain-offer").status_code == 302
    links.owner.patch(
        f"{links.path}/link-destination-origins/{links.origin['id']}", json={"status": "disabled"}
    )
    assert visit(client, "plain-offer").status_code == 404
    links.owner.patch(
        f"{links.path}/link-destination-origins/{links.origin['id']}", json={"status": "active"}
    )
    assert visit(client, "plain-offer").status_code == 302
    with Session(links.db.migration) as session, session.begin():
        session.execute(
            update(ClientWorkspace)
            .where(ClientWorkspace.id == links.w.a1)
            .values(status="archived")
        )
    assert visit(client, "plain-offer").status_code == 404
    for slug in ("unknown-slug", "UPPER", "ab", "a" * 70):
        response = visit(client, slug)
        assert (response.status_code, response.json()) == (404, {"error": "not_found"})


def test_later_platform_configuration_cannot_create_a_loop(links):
    new_link(links, "plain-offer")
    looping = links.api.config.model_copy(
        update={"link_platform_hosts": ["localhost:8000", "shop.example.test"]}
    )
    client = links.api.new_client(looping)
    assert visit(client, "plain-offer").status_code == 404
    assert visit(links.api.new_client(), "plain-offer").status_code == 302


def test_concurrent_origin_and_domain_claims_never_create_a_loop(links):
    w = links.w
    barrier = threading.Barrier(2)

    def claim(kind):
        barrier.wait()
        try:
            if kind == "origin":
                with Session(w.db.runtime) as session, session.begin():
                    LinkAdmin(session, w.users.owner_a, links.api.config).create_origin(
                        w.a, w.a1, origin="https://race.example.test", query_names=[]
                    )
            else:
                with Session(w.db.runtime) as session, session.begin():
                    LinkAdmin(session, w.users.owner_b, links.api.config).create_domain(
                        w.b, w.b1, hostname="race.example.test"
                    )
            return "created"
        except LinkConflict:
            return "conflict"

    for _ in range(3):
        with ThreadPoolExecutor(2) as pool:
            outcomes = sorted(pool.map(claim, ["origin", "domain"]))
        assert outcomes == ["conflict", "created"]
        origins = total(
            links.db, LinkDestinationOrigin, LinkDestinationOrigin.hostname == "race.example.test"
        )
        domains = total(links.db, LinkDomain, LinkDomain.hostname == "race.example.test")
        assert origins + domains == 1
        with Session(w.db.migration) as session, session.begin():
            session.execute(
                text(
                    "DELETE FROM audit_events WHERE action IN ('origin.created', 'domain.created')"
                )
            )
            session.execute(
                text("DELETE FROM link_destination_origins WHERE hostname = 'race.example.test'")
            )
            session.execute(text("DELETE FROM link_domains WHERE hostname = 'race.example.test'"))
        barrier.reset()


def read_only_engine(settings):
    return create_engine(
        settings.database_url,
        connect_args={"options": "-c default_transaction_read_only=on -c timezone=UTC"},
    )


def test_redirect_is_independent_of_telemetry_and_writes_nothing(links, monkeypatch):
    link = new_link(links)

    def unavailable(*args, **kwargs):
        raise RuntimeError("telemetry unavailable")

    for name in ("admit", "count", "record_consent", "erase_subject"):
        monkeypatch.setattr(collection_service, name, unavailable)
    before = total(links.db, AuditEvent)
    with TestClient(create_app(links.api.config), base_url="http://localhost:8000") as client:
        client.app.state.engine.dispose()
        client.app.state.engine = read_only_engine(links.api.config)
        try:
            for headers in (
                {},
                {"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"},
                {"Sec-Purpose": "prefetch", "Purpose": "prefetch"},
                {"User-Agent": "Mozilla/5.0 HeadlessChrome"},
            ):
                response = visit(client, "spring-offer", headers=headers)
                assert response.status_code == 302
                assert response.headers["location"] == link["target_url"]
                assert "set-cookie" not in response.headers
                assert not response.cookies
            with pytest.raises(DBAPIError), client.app.state.engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO event_diagnostics (id) VALUES (gen_random_uuid())")
                )
        finally:
            client.app.state.engine.dispose()
    assert all(total(links.db, model) == 0 for model in TELEMETRY)
    assert total(links.db, AuditEvent) == before


def test_missing_link_storage_returns_503_without_a_fallback(links):
    new_link(links)
    broken = links.api.config.model_copy(update={"database_port": 1, "database_connect_timeout": 1})
    with TestClient(create_app(broken), base_url="http://localhost:8000") as client:
        response = visit(client, "spring-offer", params={"next": SHOP})
    assert response.status_code == 503
    assert response.json() == {"error": "temporarily_unavailable"}
    assert "location" not in response.headers


def test_scoped_foreign_keys_refuse_cross_client_references(links):
    w = links.w
    new_link(links)
    other = links.post(
        "link-destination-origins",
        {"origin": SHOP},
        scope=f"/agencies/{w.a}/clients/{w.a2}",
    )
    foreign_link = ManagedLink(
        id=uuid4(),
        agency_id=w.a,
        client_id=w.a1,
        slug="cross-client",
        origin_id=UUID(other["id"]),
        destination=f"{SHOP}/x",
        utm={},
        target_url=f"{SHOP}/x",
    )
    with pytest.raises(IntegrityError), Session(links.db.migration) as session, session.begin():
        session.add(foreign_link)
    with pytest.raises(IntegrityError), links.db.migration.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO managed_links (id, agency_id, client_id, slug, origin_id, "
                "destination, utm, target_url, campaign_id) VALUES (gen_random_uuid(), "
                ":agency, :client, 'cross-campaign', :origin, 'x', '{}', 'x', :campaign)"
            ),
            {
                "agency": w.a,
                "client": w.a2,
                "origin": UUID(other["id"]),
                "campaign": UUID(links.campaign["id"]),
            },
        )


def test_concurrent_duplicate_hostname_claims_have_one_winner(links):
    w = links.w
    barrier = threading.Barrier(2)

    def claim(args):
        user, agency, client = args
        barrier.wait()
        try:
            with Session(w.db.runtime) as session, session.begin():
                LinkAdmin(session, user, links.api.config).create_domain(
                    agency, client, hostname="claimed.example.test"
                )
            return "created"
        except IntegrityError:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        outcomes = sorted(
            pool.map(claim, [(w.users.owner_a, w.a, w.a1), (w.users.owner_b, w.b, w.b1)])
        )
    assert outcomes == ["conflict", "created"]
    assert total(links.db, LinkDomain, LinkDomain.hostname == "claimed.example.test") == 1


def test_downgrade_refuses_populated_link_state(links):
    new_link(links)
    with pytest.raises(RuntimeError, match="managed-link state"):
        command.downgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0007_event_collection")
    with links.db.migration.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            == expected_revision()
        )
    assert total(links.db, ManagedLink) == 1
