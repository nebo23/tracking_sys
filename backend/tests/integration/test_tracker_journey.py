"""Full synthetic journey in real browsers against the real API (specification 005, E2E).

Branded short link -> destination -> explicit consent -> tracker page, form, and link events ->
scoped stored events -> withdrawal -> suppressed event -> erasure -> replay rejection. The API
runs in-process under uvicorn on loopback with the disposable database; the custom domain is
verified through the API with synthetic DNS answers and a loopback TLS server using a test-only
certificate authority. Browsers resolve the branded host to 127.0.0.1 by launch option. Requires
TRACKING_RUN_BROWSER_TESTS=1 and the tracker package's locally installed Playwright browsers.
This is synthetic evidence; no live DNS, certificate, hosting, or customer site is involved.
"""

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from uuid import UUID

import pytest
import uvicorn
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT
from app.links.verification import DomainVerifier, PinnedTlsProbe
from app.main import create_app
from app.models import (
    CollectedEvent,
    CollectionSubject,
    EventDiagnostic,
    StoredConsentRecord,
    StoredTombstone,
)

pytestmark = pytest.mark.integration

PACKAGE = PROJECT_ROOT / "packages" / "tracker-js"
BRANDED = "go.brand.test"
TARGET = "links.platform.test"
NOTICE = "c" * 64
FORBIDDEN = ("MARK-PASSWORD", "MARK-CARD", "MARK-OTP", "mark-person@example.test", "MARK-NOTES")
TRACKER_FORMS = {
    "lead": {
        "fields": [
            {"name": "password", "data_class": "form.code"},
            {"name": "card", "data_class": "form.code"},
            {"name": "otp", "data_class": "form.code"},
            {"name": "contact", "data_class": "form.code"},
            {"name": "notes", "data_class": "form.code"},
            {"name": "plan", "data_class": "form.option", "options": ["basic", "pro"]},
            {"name": "coupon", "data_class": "form.code"},
            {"name": "qty", "data_class": "form.quantity"},
        ]
    }
}
SERVER_FORM = {
    "fields": [
        {"name": "plan", "data_class": "form.option", "options": ["basic", "pro"]},
        {"name": "coupon", "data_class": "form.code"},
        {"name": "qty", "data_class": "form.quantity"},
    ]
}


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def browsers_ready() -> bool:
    return (
        os.environ.get("TRACKING_RUN_BROWSER_TESTS") == "1"
        and shutil.which("node") is not None
        and (PACKAGE / "node_modules" / "playwright").is_dir()
    )


class LiveServer:
    def __init__(self, app, port):
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("The API did not start.")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=15)


class Zone:
    def __init__(self):
        self.txt_values = []

    def txt(self, name, timeout):
        return list(self.txt_values) if name == f"_tracking-verification.{BRANDED}" else []

    def cname(self, name, timeout):
        return TARGET if name == BRANDED else None

    def addresses(self, name, timeout):
        return ["127.0.0.1"]


def rows(db, query):
    with Session(db.migration) as session:
        return list(session.scalars(query))


def counter(db, outcome, reason) -> int:
    with Session(db.migration) as session:
        return sum(
            session.scalars(
                select(EventDiagnostic.count).where(
                    EventDiagnostic.channel == "browser",
                    EventDiagnostic.outcome == outcome,
                    EventDiagnostic.reason == reason,
                )
            )
        )


@pytest.mark.skipif(not browsers_ready(), reason="Set TRACKING_RUN_BROWSER_TESTS=1 with browsers.")
@pytest.mark.parametrize("browser", ["chromium", "firefox"])
def test_branded_link_to_erasure_journey(
    browser, authenticated_world, api, synthetic_pki, tls_server
):
    w = authenticated_world
    api_port, site_port, stranger_port = free_port(), free_port(), free_port()
    site = f"http://127.0.0.1:{site_port}"
    collector = f"http://127.0.0.1:{api_port}"
    config = api.config.model_copy(
        update={
            "link_platform_hosts": [f"127.0.0.1:{api_port}"],
            "link_custom_domain_port": api_port,
            "link_allow_loopback_destinations": True,
            "link_service_target": TARGET,
            "consent_state_per_minute": 4,
        }
    )
    zone = Zone()
    certificate = tls_server(synthetic_pki.issue(BRANDED))
    admin = api.new_client(config)
    admin.app.state.domain_verifier = DomainVerifier(
        zone,
        PinnedTlsProbe(port=certificate.port, context_factory=synthetic_pki.context),
        address_allowed=lambda address: address == "127.0.0.1",
    )
    api.login(admin, "owner_a@example.test")
    path = f"/agencies/{w.a}/clients/{w.a1}"

    def post(resource, body, status=201):
        response = admin.post(f"{path}/{resource}", json=body)
        assert response.status_code == status, response.text
        return response.json()

    source = post(
        "ingestion-sources",
        {"kind": "browser", "name": "Shop", "allowed_origins": [site], "notice_sha256": NOTICE},
    )["source"]
    assert admin.put(f"{path}/collection-forms/lead", json=SERVER_FORM).status_code == 200
    post("link-destination-origins", {"origin": site, "query_names": ["ref"]})
    campaign = post("link-campaigns", {"public_code": "spring-2026", "label": "Spring"})
    domain = post("link-domains", {"hostname": BRANDED})
    zone.txt_values = [post(f"link-domains/{domain['id']}/challenge", {})["record_value"]]
    verified = admin.post(f"{path}/link-domains/{domain['id']}/verify")
    assert verified.json()["outcome"] == "verified", verified.text
    link = post(
        "managed-links",
        {
            "slug": "spring-offer",
            "destination": f"{site}/offer?ref=social",
            "domain_id": domain["id"],
            "campaign_id": campaign["id"],
            "utm": {"utm_source": "instagram", "utm_medium": "social"},
        },
    )
    options = {
        "browser": browser,
        "apiPort": api_port,
        "sitePort": site_port,
        "strangerPort": stranger_port,
        "siteOrigin": site,
        "collector": collector,
        "publicKey": source["public_key"],
        "brandedHost": BRANDED,
        "brandedUrl": f"http://{BRANDED}:{api_port}/r/spring-offer",
        "forms": TRACKER_FORMS,
    }
    with LiveServer(create_app(config), api_port):
        completed = subprocess.run(
            ["node", str(PACKAGE / "test" / "e2e" / "journey.js"), json.dumps(options)],
            cwd=PACKAGE,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0"},
        )
    assert completed.returncode == 0, completed.stderr[-2000:]
    report = json.loads(completed.stdout)
    assert "failure" not in report, report.get("failure")
    assert report["errors"] == []

    # Redirect: exact issued target, no cookie, no telemetry before consent.
    assert report["redirect"]["status"] == 302
    assert report["redirect"]["location"] == link["target_url"]
    assert report["redirect"]["landing"] == link["target_url"]
    assert (
        f"ts_link={link['id']}" in link["target_url"] and "utm_id=spring-2026" in link["target_url"]
    )
    assert report["brandedCookies"] == [] and report["cookies"] == []
    pre = [item for item in report["api"] if item["step"] == 0]
    assert [(item["method"], item["path"]) for item in pre] == [("GET", "/r/spring-offer")]
    assert report["preConsentStorage"] == [] and report["preConsentBlocked"] == "blocked"

    # Consent and collection.
    assert report["grant"]["status"] == "granted"
    stored_record = json.loads(report["storageRecord"])
    assert sorted(stored_record) == ["expiresAt", "purposes", "token", "v"]
    assert report["viewStatus"] == 202 and report["afterSubmit"].startswith(f"{site}/thanks")
    assert report["resume"]["status"] == "resumed"
    consent_writes = [item for item in report["api"] if item["path"].endswith("/consent")]
    assert len(consent_writes) == 2  # the grant and the withdrawal; resume never writes
    form_envelope = json.loads(report["formEnvelope"])
    click_envelope = json.loads(report["clickEnvelope"])
    assert form_envelope["link_id"] == link["id"] and "link_id" not in click_envelope
    for item in report["api"]:
        for marker in FORBIDDEN:
            assert marker not in (item["body"] or ""), marker

    # Stored events before erasure were checked through the replay outcomes below; verify the
    # erasure removed every row and left tombstones, then the counters for the replays.
    assert report["withdraw"]["confirmed"] is True and report["afterWithdraw"] == "blocked"
    assert report["replayAfterWithdrawal"] == {"status": 202, "body": {"status": "received"}}
    assert report["erase"] == {"status": "erased", "confirmed": True}
    assert report["storageAfterErasure"] == []
    assert report["replayAfterErasure"] == {"status": 202, "body": {"status": "received"}}
    assert report["stateAfterErasure"]["status"] == "unknown"
    assert report["retryAfter"]["status"] == 429 and report["retryAfter"]["header"].isdigit()
    assert report["stranger"]["readable"] is False
    assert rows(w.db, select(CollectedEvent)) == []
    assert rows(w.db, select(CollectionSubject)) == []
    assert rows(w.db, select(StoredConsentRecord)) == []
    assert len(rows(w.db, select(StoredTombstone))) == 4  # token plus three event IDs
    assert counter(w.db, "accepted", "new") == 3
    assert counter(w.db, "suppressed", "consent_withdrawn") == 1
    assert counter(w.db, "rejected", "subject_deleted") == 1
    assert UUID(report["withdrawnEventId"])


@pytest.mark.skipif(not browsers_ready(), reason="Set TRACKING_RUN_BROWSER_TESTS=1 with browsers.")
def test_journey_events_store_exactly_what_the_browser_sent(
    authenticated_world, api, synthetic_pki, tls_server
):
    """Stored payloads equal the browser-minimized envelopes (actual parity, M2)."""
    w = authenticated_world
    api_port, site_port = free_port(), free_port()
    site = f"http://127.0.0.1:{site_port}"
    config = api.config.model_copy(
        update={
            "link_platform_hosts": [f"127.0.0.1:{api_port}"],
            "link_allow_loopback_destinations": True,
        }
    )
    admin = api.new_client(config)
    api.login(admin, "owner_a@example.test")
    path = f"/agencies/{w.a}/clients/{w.a1}"
    source = admin.post(
        f"{path}/ingestion-sources",
        json={
            "kind": "browser",
            "name": "Shop",
            "allowed_origins": [site],
            "notice_sha256": NOTICE,
        },
    ).json()["source"]
    admin.put(f"{path}/collection-forms/lead", json=SERVER_FORM)
    admin.post(f"{path}/link-destination-origins", json={"origin": site})
    link = admin.post(
        f"{path}/managed-links",
        json={
            "slug": "plain-offer",
            "destination": f"{site}/offer?utm_source=newsletter",
            "utm": {"utm_campaign": "spring"},
        },
    ).json()
    script = PACKAGE / "test" / "e2e" / "parity-page.js"
    options = {
        "port": site_port,
        "collector": f"http://127.0.0.1:{api_port}",
        "publicKey": source["public_key"],
        "forms": TRACKER_FORMS,
        "url": f"http://127.0.0.1:{api_port}/r/plain-offer",
        "suffix": "&gclid=g1&email=someone%40example.test&card=4111+1111+1111+1111#frag",
    }
    with LiveServer(create_app(config), api_port):
        completed = subprocess.run(
            ["node", str(script), json.dumps(options)],
            cwd=PACKAGE,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0"},
        )
    assert completed.returncode == 0, completed.stderr[-2000:]
    sent = json.loads(completed.stdout)
    assert "failure" not in sent, sent.get("failure")
    stored = {str(row.event_id): row for row in rows(w.db, select(CollectedEvent))}
    assert len(sent["envelopes"]) == 2 and len(stored) == 2
    for raw in sent["envelopes"]:
        envelope = json.loads(raw)
        row = stored[envelope["event_id"]]
        assert row.payload == envelope["payload"]
        assert str(row.link_id) == envelope["link_id"] == link["id"]
        assert "gclid" not in raw and "someone" not in raw and "4111" not in raw
    assert counter(w.db, "minimized", "url_component") == 0
    with Session(w.db.migration) as session:
        reasons = session.execute(text("SELECT reason FROM event_diagnostics")).scalars().all()
    assert set(reasons) == {"new", "recorded"}
