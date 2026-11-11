"""Custom-domain verification logic and live adapters on loopback only (specification 005-E).

DNS answers come from an in-process fake or a loopback UDP responder; TLS uses loopback servers
with synthetic certificates. Nothing contacts real DNS, certificate authorities, or customer
infrastructure, so these results are synthetic evidence, not live custom-domain validation.
"""

import hashlib
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import dns.exception
import dns.message
import dns.name
import dns.rrset
import pytest

from app.links.verification import (
    CHALLENGE_PREFIX,
    DnsResolver,
    DomainVerifier,
    PinnedTlsProbe,
    TlsInvalid,
    VerificationUnavailable,
    is_global_address,
)

HOST = "go.brand.test"
TARGET = "links.platform.test"
RAW = "synthetic-challenge-value"
DIGEST = hashlib.sha256(RAW.encode()).hexdigest()
PUBLIC = "203.0.113.10"  # documentation range; is_global is False, so tests inject a policy


class FakeResolver:
    def __init__(self, txt=None, cname=None, addresses=None):
        self.zone_txt = (
            txt if txt is not None else {f"_tracking-verification.{HOST}": [CHALLENGE_PREFIX + RAW]}
        )
        self.zone_cname = cname if cname is not None else {HOST: TARGET}
        self.zone_addresses = addresses if addresses is not None else [[PUBLIC]]
        self.calls = []

    def txt(self, name, timeout):
        self.calls.append(("txt", name))
        return self.zone_txt.get(name, [])

    def cname(self, name, timeout):
        self.calls.append(("cname", name))
        return self.zone_cname.get(name)

    def addresses(self, name, timeout):
        self.calls.append(("addresses", name))
        answers = self.zone_addresses
        return answers.pop(0) if len(answers) > 1 else answers[0]


class FakeTls:
    def __init__(self, expiry=None, error=None):
        self.expiry = expiry or datetime.now(UTC) + timedelta(days=30)
        self.error = error
        self.calls = []

    def certificate_expiry(self, address, hostname, timeout):
        self.calls.append((address, hostname))
        if self.error:
            raise self.error
        return self.expiry


def verifier(resolver=None, tls=None, **kwargs):
    kwargs.setdefault("address_allowed", lambda address: address == PUBLIC)
    return DomainVerifier(resolver or FakeResolver(), tls or FakeTls(), **kwargs)


def test_success_needs_ownership_routing_addresses_and_a_valid_certificate():
    resolver, tls = FakeResolver(), FakeTls()
    result = verifier(resolver, tls).check(HOST, DIGEST, TARGET)
    assert result.ok and result.certificate_expires_at == tls.expiry
    assert tls.calls == [(PUBLIC, HOST)]
    assert [call[0] for call in resolver.calls] == ["txt", "cname", "addresses"]


@pytest.mark.parametrize(
    ("resolver", "failure"),
    [
        (FakeResolver(txt={}), "ownership_missing"),
        (
            FakeResolver(txt={f"_tracking-verification.{HOST}": ["tracking-verification=wrong"]}),
            "ownership_missing",
        ),
        (FakeResolver(txt={f"_tracking-verification.{HOST}": [RAW]}), "ownership_missing"),
        (FakeResolver(txt={HOST: [CHALLENGE_PREFIX + RAW]}), "ownership_missing"),
        (FakeResolver(cname={}), "routing_mismatch"),
        (FakeResolver(cname={HOST: "elsewhere.example.test"}), "routing_mismatch"),
        (FakeResolver(cname={HOST: "a.example.test", "a.example.test": HOST}), "routing_mismatch"),
        (FakeResolver(cname={HOST: "bad_label.example.test"}), "routing_mismatch"),
        (
            FakeResolver(
                cname={
                    HOST: "h1.example.test",
                    **{f"h{i}.example.test": f"h{i + 1}.example.test" for i in range(1, 9)},
                    "h9.example.test": TARGET,
                }
            ),
            "routing_mismatch",
        ),
        (FakeResolver(addresses=[[]]), "routing_mismatch"),
        (FakeResolver(addresses=[["10.0.0.5"]]), "address_not_allowed"),
        (FakeResolver(addresses=[[PUBLIC, "127.0.0.1"]]), "address_not_allowed"),
    ],
)
def test_ownership_routing_and_address_failures_never_verify(resolver, failure):
    tls = FakeTls()
    assert verifier(resolver, tls).check(HOST, DIGEST, TARGET).failure == failure
    assert tls.calls == []


def test_a_chain_of_eight_hops_reaching_the_target_is_accepted():
    chain = {HOST: "h1.example.test"}
    chain.update({f"h{i}.example.test": f"h{i + 1}.example.test" for i in range(1, 7)})
    chain["h7.example.test"] = TARGET
    assert verifier(FakeResolver(cname=chain)).check(HOST, DIGEST, TARGET).ok


def test_certificate_and_deadline_failures():
    soon = FakeTls(expiry=datetime.now(UTC) + timedelta(minutes=30))
    assert verifier(tls=soon).check(HOST, DIGEST, TARGET).failure == "tls_invalid"
    assert verifier(tls=FakeTls(error=TlsInvalid())).check(HOST, DIGEST, TARGET).failure == (
        "tls_invalid"
    )
    unavailable = FakeTls(error=VerificationUnavailable())
    assert verifier(tls=unavailable).check(HOST, DIGEST, TARGET).failure == (
        "verification_unavailable"
    )
    ticks = iter([0.0, 1.0, 2.0, 6.0, 7.0, 8.0])
    slow = verifier(clock=lambda: next(ticks), deadline_seconds=5.0)
    assert slow.check(HOST, DIGEST, TARGET).failure == "verification_unavailable"


def test_addresses_are_resolved_once_and_the_connection_is_pinned_to_them():
    rebinding = FakeResolver(addresses=[[PUBLIC], ["127.0.0.1"]])
    tls = FakeTls()
    assert verifier(rebinding, tls).check(HOST, DIGEST, TARGET).ok
    assert [call for call in rebinding.calls if call[0] == "addresses"] == [("addresses", HOST)]
    assert tls.calls == [(PUBLIC, HOST)]


def test_live_address_policy_rejects_private_special_and_mapped_addresses():
    assert is_global_address("8.8.8.8") and is_global_address("2001:4860:4860::8888")
    for address in (
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "203.0.113.10",
        "not-an-address",
    ):
        assert not is_global_address(address), address
    # Without an injected test policy, a loopback answer can never pass.
    live = DomainVerifier(FakeResolver(addresses=[["127.0.0.1"]]), FakeTls())
    assert live.check(HOST, DIGEST, TARGET).failure == "address_not_allowed"


# Adapters take an absolute deadline on the monotonic clock.
def soon(seconds):
    return time.monotonic() + seconds


def probe(server, synthetic_pki, **kwargs):
    return PinnedTlsProbe(port=server.port, context_factory=synthetic_pki.context, **kwargs)


def test_pinned_tls_probe_checks_chain_hostname_and_expiry_with_sni(synthetic_pki, tls_server):
    good = synthetic_pki.issue(HOST)
    server = tls_server(good)
    expiry = probe(server, synthetic_pki).certificate_expiry("127.0.0.1", HOST, soon(3))
    assert abs((expiry - good.not_after).total_seconds()) < 2
    assert server.names == [HOST]
    for case in (
        synthetic_pki.issue("other.example.test"),
        synthetic_pki.issue(HOST, valid_for=timedelta(hours=-1), age=timedelta(days=2)),
        synthetic_pki.issue(HOST, ca=synthetic_pki.untrusted),
    ):
        with pytest.raises(TlsInvalid):
            probe(tls_server(case), synthetic_pki).certificate_expiry("127.0.0.1", HOST, soon(3))
    with pytest.raises(TlsInvalid):
        PinnedTlsProbe(port=server.port).certificate_expiry("127.0.0.1", HOST, soon(3))
    closed = socket.create_server(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    with pytest.raises(VerificationUnavailable):
        PinnedTlsProbe(port=port).certificate_expiry("127.0.0.1", HOST, soon(1))


def test_the_probe_sends_no_application_data(synthetic_pki, tls_server):
    server = tls_server(synthetic_pki.issue(HOST))
    probe(server, synthetic_pki).certificate_expiry("127.0.0.1", HOST, soon(3))
    deadline = datetime.now(UTC) + timedelta(seconds=3)
    while not server.data and datetime.now(UTC) < deadline:
        pass
    assert server.handshakes == 1 and server.data == [b""]


class LoopbackDns:
    """A minimal UDP responder answering from a fixed synthetic zone."""

    def __init__(self, zone, silent=False):
        self.zone, self.silent, self.queries = zone, silent, []
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.settimeout(0.2)
        self.port = self.socket.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.stop.is_set():
            try:
                data, peer = self.socket.recvfrom(4096)
            except (TimeoutError, OSError):
                continue
            query = dns.message.from_wire(data)
            question = query.question[0]
            kind = dns.rdatatype.to_text(question.rdtype)
            name = question.name.to_text(omit_final_dot=True)
            self.queries.append((name, kind))
            if self.silent:
                continue
            response = dns.message.make_response(query)
            values = self.zone.get((name, kind))
            if values is None and not any(key[0] == name for key in self.zone):
                response.set_rcode(dns.rcode.NXDOMAIN)
            elif values:
                response.answer.append(dns.rrset.from_text(question.name, 60, "IN", kind, *values))
            self.socket.sendto(response.to_wire(), peer)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        self.socket.close()


def test_dnspython_adapter_reads_txt_cname_and_addresses_without_search(monkeypatch):
    zone = {
        (f"_tracking-verification.{HOST}", "TXT"): [f'"{CHALLENGE_PREFIX}{RAW}"'],
        (HOST, "CNAME"): [f"{TARGET}."],
        (HOST, "A"): ["198.51.100.7"],
        (HOST, "AAAA"): ["2001:db8::7"],
        ("empty.example.test", "A"): [],
    }
    server = LoopbackDns(zone)
    try:
        resolver = DnsResolver(["127.0.0.1"], port=server.port)
        assert resolver.txt(f"_tracking-verification.{HOST}", soon(2)) == [CHALLENGE_PREFIX + RAW]
        assert resolver.cname(HOST, soon(2)) == TARGET
        assert resolver.addresses(HOST, soon(2)) == ["198.51.100.7", "2001:db8::7"]
        assert resolver.addresses("missing.example.test", soon(2)) == []
        assert resolver.cname("empty.example.test", soon(2)) is None
        assert all(not name.endswith(".local") for name, _ in server.queries)
    finally:
        server.close()
    silent = LoopbackDns({}, silent=True)
    try:
        with pytest.raises(VerificationUnavailable):
            DnsResolver(["127.0.0.1"], port=silent.port).txt(HOST, soon(0.5))
    finally:
        silent.close()


def test_end_to_end_with_loopback_dns_and_tls(synthetic_pki, tls_server):
    server = tls_server(synthetic_pki.issue(HOST, valid_for=timedelta(days=10)))
    zone = {
        (f"_tracking-verification.{HOST}", "TXT"): [f'"{CHALLENGE_PREFIX}{RAW}"'],
        (HOST, "CNAME"): [f"{TARGET}."],
        (HOST, "A"): ["127.0.0.1"],
        (HOST, "AAAA"): [],
    }
    dns_server = LoopbackDns(zone)
    try:
        checker = DomainVerifier(
            DnsResolver(["127.0.0.1"], port=dns_server.port),
            probe(server, synthetic_pki),
            address_allowed=lambda address: address == "127.0.0.1",
        )
        result = checker.check(HOST, DIGEST, TARGET)
        assert result.ok, result
        assert server.names == [HOST]
        wrong = checker.check(HOST, hashlib.sha256(b"other").hexdigest(), TARGET)
        assert wrong.failure == "ownership_missing"
    finally:
        dns_server.close()


def test_configuration_selects_only_live_adapters_or_none(settings):
    from app.main import create_app

    assert create_app(settings).state.domain_verifier is None
    live = settings.model_copy(
        update={"link_domain_verification": "live", "link_service_target": "links.platform.test"}
    )
    verifier = create_app(live).state.domain_verifier
    assert isinstance(verifier.resolver, DnsResolver)
    assert isinstance(verifier.tls, PinnedTlsProbe) and verifier.tls.port == 443
    assert verifier.address_allowed is is_global_address
    assert verifier.deadline_seconds == 5.0


def test_link_settings_refuse_wildcards_and_live_mode_without_a_target(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    base = {
        "database_password": "synthetic",
        "auth_secret": "ab" * 32,
        "otp_secret": "cd" * 32,
        "mail_encryption_key": "dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHQ=",
    }
    for name in [n for n in __import__("os").environ if n.startswith("TRACKING_")]:
        monkeypatch.delenv(name)
    for bad in (
        {"link_platform_hosts": ["*.example.test"]},
        {"link_platform_hosts": []},
        {"link_platform_hosts": ["user@host"]},
        {"link_service_target": "printer.local"},
        {"link_domain_verification": "live"},
        {"link_domain_verification": "synthetic"},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **base, **bad)
    assert Settings(_env_file=None, **base).link_domain_verification == "disabled"


# Review corrections of 2026-11-11 (R005-10, R005-11).


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def test_dns_subqueries_share_one_total_deadline():
    clock = FakeClock()
    lifetimes = []
    resolver = DnsResolver(["127.0.0.1"], port=9)
    resolver.clock = clock

    def slow_resolve(name, rdtype, **kwargs):
        lifetime = kwargs["lifetime"]
        lifetimes.append(round(lifetime, 3))
        clock.value += min(4.0, lifetime)
        if lifetime < 4.0:
            raise dns.exception.Timeout()
        if rdtype == "TXT":
            return SimpleNamespace(
                rrset=[SimpleNamespace(strings=[(CHALLENGE_PREFIX + RAW).encode()])]
            )
        if rdtype == "CNAME":
            return SimpleNamespace(rrset=[SimpleNamespace(target=dns.name.from_text(TARGET))])
        return SimpleNamespace(rrset=[SimpleNamespace(address=PUBLIC)])

    resolver.resolver.resolve = slow_resolve
    checker = DomainVerifier(
        resolver, FakeTls(), address_allowed=lambda a: a == PUBLIC, clock=clock, deadline_seconds=13
    )
    result = checker.check(HOST, DIGEST, TARGET)
    assert result.failure == "verification_unavailable"
    # TXT and CNAME use 4 s each; A gets the remaining 5 s and AAAA only the last 1 s.
    assert lifetimes == [13.0, 9.0, 5.0, 1.0]
    assert clock.value <= 13.0


def test_connect_and_handshake_share_one_total_deadline(monkeypatch, synthetic_pki):
    silent = socket.create_server(("127.0.0.1", 0))  # accepts TCP, never answers TLS
    clock = FakeClock()
    real_connect = socket.create_connection

    def slow_connect(address, timeout=None, *args, **kwargs):
        clock.value += 4.0  # the TCP connection used four of the five seconds
        return real_connect(address, timeout=timeout)

    monkeypatch.setattr(socket, "create_connection", slow_connect)
    tls = PinnedTlsProbe(port=silent.getsockname()[1], context_factory=synthetic_pki.context)
    tls.clock = clock
    checker = DomainVerifier(
        FakeResolver(addresses=[["127.0.0.1"]]),
        tls,
        address_allowed=lambda a: a == "127.0.0.1",
        clock=clock,
        deadline_seconds=5.0,
    )
    started = time.monotonic()
    try:
        assert checker.check(HOST, DIGEST, TARGET).failure == "verification_unavailable"
    finally:
        silent.close()
    assert time.monotonic() - started < 2.5  # one remaining second, not a fresh five


def test_service_target_comparison_is_case_insensitive(settings):
    mixed = settings.model_copy(update={"link_service_target": "Links.Platform.TEST"})
    from app.config import Settings

    validated = Settings.model_validate(mixed.model_dump())
    assert validated.link_service_target == TARGET
    for target in (TARGET, "Links.Platform.TEST", "LINKS.PLATFORM.TEST"):
        assert verifier().check(HOST, DIGEST, target).ok, target
