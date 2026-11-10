"""Custom-domain ownership, routing, and TLS verification (specification 005-E, D-033).

A domain check proves three separate things, in order, within one total deadline:

1. Ownership: a TXT record at _tracking-verification.<host> carries the current challenge,
   compared by SHA-256 digest in constant time. Only the client's DNS control proves tenancy;
   a CNAME or a certificate never does, and certificate validation is not tenancy.
2. Routing: the host's CNAME chain (at most eight hops, no loops) reaches the operator-configured
   service target, and every A/AAAA answer for the host is an allowed (global) address. Mixed
   public and private answers fail.
3. TLS: one connection to a validated address, with the original hostname for SNI and
   certificate hostname checking, against the system trust store, rejecting certificates that
   expire within an hour. No HTTP request is sent and no redirect is followed.

The address is resolved once and the connection is bound to it, so a DNS answer cannot change
between validation and connection (rebinding). Adapters are injected: DnsResolver and
PinnedTlsProbe are the live implementations, used only when live verification is explicitly
enabled; tests construct synthetic resolvers, address policies, ports, and trust stores in
code. No customer input or setting can select them. Results carry closed reason codes; no raw
DNS answer, certificate, challenge, or address is logged or returned.
"""

import hashlib
import hmac
import ipaddress
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import dns.exception
import dns.resolver

from app.links.policy import LinkRuleError, canonical_hostname

DEADLINE_SECONDS = 5.0
MAX_CNAME_CHAIN = 8
CERTIFICATE_MARGIN = timedelta(hours=1)
CHALLENGE_LABEL = "_tracking-verification"
CHALLENGE_PREFIX = "tracking-verification="


class VerificationUnavailable(Exception):
    """A resolver or connection failure, or the total deadline elapsed."""


class TlsInvalid(Exception):
    """The certificate chain, hostname, or validity did not verify."""


# Adapters receive one absolute deadline on the monotonic clock (time.monotonic unless a test
# injects another clock) and recompute the remaining budget before each blocking operation.
class Resolver(Protocol):
    def txt(self, name: str, deadline: float) -> list[str]: ...

    def cname(self, name: str, deadline: float) -> str | None: ...

    def addresses(self, name: str, deadline: float) -> list[str]: ...


class TlsProbe(Protocol):
    def certificate_expiry(self, address: str, hostname: str, deadline: float) -> datetime: ...


def _remaining(clock: Callable[[], float], deadline: float) -> float:
    left = deadline - clock()
    if left <= 0:
        raise VerificationUnavailable()
    return left


@dataclass(frozen=True)
class CheckResult:
    failure: str | None
    certificate_expires_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


# Live address policy: a global unicast address. IPv4-mapped IPv6 addresses are judged as IPv4.
def is_global_address(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not (address.is_multicast or address.is_unspecified)


def _matches_challenge(values: list[str], digest: str) -> bool:
    found = False
    for value in values:
        if value.startswith(CHALLENGE_PREFIX):
            candidate = hashlib.sha256(value[len(CHALLENGE_PREFIX) :].encode()).hexdigest()
            found |= hmac.compare_digest(candidate, digest)
    return found


def _canonical(name: str) -> str | None:
    try:
        return canonical_hostname(name.rstrip(".").lower())
    except LinkRuleError:
        return None


class DomainVerifier:
    def __init__(
        self,
        resolver: Resolver,
        tls: TlsProbe,
        *,
        address_allowed: Callable[[str], bool] = is_global_address,
        deadline_seconds: float = DEADLINE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.resolver, self.tls = resolver, tls
        self.address_allowed = address_allowed
        self.deadline_seconds = deadline_seconds
        self.clock, self.now = clock, now

    # One total deadline covers every DNS query, the TCP connection and the TLS handshake. The
    # service target is compared in canonical form, like every CNAME answer (R005-11).
    def check(self, hostname: str, challenge_digest: str, service_target: str) -> CheckResult:
        deadline = self.clock() + self.deadline_seconds
        target_host = _canonical(service_target)

        def within() -> float:
            _remaining(self.clock, deadline)
            return deadline

        if target_host is None:
            return CheckResult("routing_mismatch")
        try:
            records = self.resolver.txt(f"{CHALLENGE_LABEL}.{hostname}", within())
            if not _matches_challenge(records, challenge_digest):
                return CheckResult("ownership_missing")
            name, seen, routed = hostname, {hostname}, False
            for _ in range(MAX_CNAME_CHAIN + 1):
                target = self.resolver.cname(name, within())
                if target is None:
                    break
                target = _canonical(target)
                if target is None or target in seen:
                    return CheckResult("routing_mismatch")
                seen.add(target)
                if target == target_host:
                    routed = True
                    break
                name = target
            if not routed or len(seen) - 1 > MAX_CNAME_CHAIN:
                return CheckResult("routing_mismatch")
            addresses = self.resolver.addresses(hostname, within())
            if not addresses:
                return CheckResult("routing_mismatch")
            if not all(self.address_allowed(address) for address in addresses):
                return CheckResult("address_not_allowed")
            expiry = self.tls.certificate_expiry(sorted(addresses)[0], hostname, within())
            within()
        except TlsInvalid:
            return CheckResult("tls_invalid")
        except VerificationUnavailable:
            return CheckResult("verification_unavailable")
        if expiry - CERTIFICATE_MARGIN <= self.now():
            return CheckResult("tls_invalid")
        return CheckResult(None, expiry)


# Live DNS adapter (dnspython). Each query, including the separate A and AAAA queries, gets only
# the budget left before the shared deadline and never uses the search list. A missing name or
# record is an empty answer; resolver failures and timeouts are VerificationUnavailable.
# nameservers/port exist for loopback tests only; clock is the monotonic clock.
class DnsResolver:
    clock: Callable[[], float] = staticmethod(time.monotonic)

    def __init__(self, nameservers: list[str] | None = None, port: int = 53) -> None:
        if nameservers is None:
            self.resolver = dns.resolver.Resolver()
        else:
            self.resolver = dns.resolver.Resolver(configure=False)
            self.resolver.nameservers = nameservers
            self.resolver.port = port

    def _query(self, name: str, rdtype: str, deadline: float):
        lifetime = _remaining(self.clock, deadline)
        try:
            answer = self.resolver.resolve(
                name, rdtype, raise_on_no_answer=False, lifetime=lifetime, search=False
            )
        except dns.resolver.NXDOMAIN:
            return []
        except (dns.exception.DNSException, OSError) as error:
            raise VerificationUnavailable() from error
        return list(answer.rrset or [])

    def txt(self, name: str, deadline: float) -> list[str]:
        return [
            b"".join(record.strings).decode("ascii", "replace")
            for record in self._query(name, "TXT", deadline)
        ]

    def cname(self, name: str, deadline: float) -> str | None:
        records = self._query(name, "CNAME", deadline)
        return records[0].target.to_text(omit_final_dot=True) if records else None

    def addresses(self, name: str, deadline: float) -> list[str]:
        found = []
        for rdtype in ("A", "AAAA"):
            found += [record.address for record in self._query(name, rdtype, deadline)]
        return found


# Live TLS adapter: connect to the already validated address (no second resolution), present
# the original hostname as SNI, and require a trusted chain whose names cover that hostname.
# Only the handshake happens; no application data is sent. port and context_factory exist for
# loopback tests with a synthetic certificate authority only. The TCP connection and the
# handshake each get only the budget left before the shared deadline.
class PinnedTlsProbe:
    clock: Callable[[], float] = staticmethod(time.monotonic)

    def __init__(
        self,
        *,
        port: int = 443,
        context_factory: Callable[[], ssl.SSLContext] = ssl.create_default_context,
    ) -> None:
        self.port, self.context_factory = port, context_factory

    def certificate_expiry(self, address: str, hostname: str, deadline: float) -> datetime:
        context = self.context_factory()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            connect_budget = _remaining(self.clock, deadline)
            with socket.create_connection((address, self.port), timeout=connect_budget) as raw:
                raw.settimeout(_remaining(self.clock, deadline))
                with context.wrap_socket(
                    raw, server_hostname=hostname, do_handshake_on_connect=False
                ) as connection:
                    connection.do_handshake()
                    certificate = connection.getpeercert()
        except (ssl.SSLCertVerificationError, ssl.CertificateError) as error:
            raise TlsInvalid() from error
        except ssl.SSLError as error:
            raise TlsInvalid() from error
        except OSError as error:
            raise VerificationUnavailable() from error
        if not certificate or "notAfter" not in certificate:
            raise TlsInvalid()
        return datetime.fromtimestamp(ssl.cert_time_to_seconds(certificate["notAfter"]), UTC)
