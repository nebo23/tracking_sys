"""Managed-link destination, hostname, slug, and UTM rules (specification 005-B, D-033).

Synthetic hostnames only. Validation is offline: no case resolves or fetches anything.
"""

from uuid import UUID

import pytest

from app.links.policy import (
    LinkRuleError,
    Origin,
    canonical_hostname,
    canonical_origin,
    compose_target,
    is_managed_target,
    merge_utm,
    parse_destination,
    platform_authorities,
    request_authority,
    validate_query_names,
    validate_slug,
    validate_utm,
)
from app.privacy.collection import contains_card_number

SHOP = Origin("https", "shop.example.test", None)
LINK = UUID("00000000-0000-4000-8000-000000000123")


def code(callable_, *args, **kwargs) -> str:
    with pytest.raises(LinkRuleError) as raised:
        callable_(*args, **kwargs)
    return raised.value.code


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Shop.Example.Test", "shop.example.test"),
        ("xn--bcher-kva.example", "xn--bcher-kva.example"),
        ("b\u00fccher.example", "xn--bcher-kva.example"),
        ("go.brand.test", "go.brand.test"),
    ],
)
def test_hostnames_are_canonical_ascii(value, expected):
    assert canonical_hostname(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "localhost",
        "intranet",
        "printer.local",
        "db.internal",
        "router.home.arpa",
        "x.onion",
        "1.2.3.4",
        "[::1]",
        "*.example.test",
        "trailing.example.test.",
        "-bad.example.test",
        "under_score.example.test",
        "a" * 64 + ".example.test",
        "example.123",
    ],
)
def test_internal_ip_wildcard_and_malformed_hostnames_are_refused(value):
    assert code(canonical_hostname, value) in {"invalid_hostname", "internal_hostname"}


def test_origins_are_exact_https_and_loopback_needs_development_configuration():
    assert canonical_origin("https://Shop.Example.Test").text == "https://shop.example.test"
    assert canonical_origin("https://shop.example.test:443/").text == "https://shop.example.test"
    for unsafe in [
        "http://shop.example.test",
        "javascript:alert(1)",
        "data:text/html,x",
        "ftp://shop.example.test",
        "https://user:pass@shop.example.test",
        "https://shop.example.test:8443",
        "https://shop.example.test/path",
        "https://shop.example.test?x=1",
        "https://shop.example.test#x",
        "https://10.0.0.1",
        "https://[::1]",
        "https://shop.example.test\\@evil.test",
        "https://shop.exa mple.test",
        "http://127.0.0.1:9000",
    ]:
        with pytest.raises(LinkRuleError):
            canonical_origin(unsafe)
    loopback = canonical_origin("http://127.0.0.1:9000", allow_loopback=True)
    assert loopback.text == "http://127.0.0.1:9000"
    with pytest.raises(LinkRuleError):
        canonical_origin("http://10.0.0.1:9000", allow_loopback=True)


def test_static_query_names_exclude_reserved_and_sensitive_names():
    assert validate_query_names(["ref", "variant"]) == ["ref", "variant"]
    for names, reason in [
        (["utm_source"], "reserved_query_name"),
        (["gclid"], "reserved_query_name"),
        (["ts_link"], "reserved_query_name"),
        (["session_id"], "sensitive_query_name"),
        (["api_key"], "sensitive_query_name"),
        (["accesstoken"], "sensitive_query_name"),
        (["customer"], "sensitive_query_name"),
        (["user_email"], "sensitive_query_name"),
        (["sig"], "sensitive_query_name"),
        (["Ref"], "invalid_query_names"),
        (["a", "a"], "invalid_query_names"),
        ([f"n{i}" for i in range(21)], "invalid_query_names"),
    ]:
        assert code(validate_query_names, names) == reason


def test_slugs_are_bounded_lowercase_codes_without_reserved_names():
    assert validate_slug("spring-offer") == "spring-offer"
    for bad in ["ab", "Spring", "-start", "has space", "a" * 65, "admin", "collect", "x/y"]:
        assert code(validate_slug, bad) == "invalid_slug"


def test_destination_accepts_only_registered_origin_static_names_and_codes():
    parsed = parse_destination(
        "https://shop.example.test/offer?ref=spring&utm_source=site", SHOP, ["ref"]
    )
    assert parsed.path == "/offer" and parsed.static == (("ref", "spring"),)
    assert parsed.utm == {"utm_source": "site"}
    assert parse_destination("https://shop.example.test", SHOP, []).path == "/"
    cases = {
        "https://other.example.test/offer": "origin_not_registered",
        "https://shop.example.test/offer?unknown=1": "query_name_not_allowed",
        "https://shop.example.test/offer?ts_link=x": "reserved_query_name",
        "https://shop.example.test/offer?ref=a&ref=b": "invalid_destination_query",
        "https://shop.example.test/offer?ref": "invalid_destination_query",
        "https://shop.example.test/offer?ref=a%20b": "invalid_destination_query",
        "https://shop.example.test/offer?ref=4111111111111111": "invalid_destination_query",
        "https://shop.example.test/offer#fragment": "invalid_destination",
        "https://user@shop.example.test/offer": "invalid_destination",
        "https://shop.example.test/a%2Fb": "invalid_destination",
        "https://shop.example.test/a%252e": "invalid_destination",
        "https://shop.example.test/a%0d": "invalid_destination",
        "https://shop.example.test/a%zz": "invalid_destination",
        "https://shop.example.test/../admin": "invalid_destination",
        "https://shop.example.test//evil.test": "invalid_destination",
        "https://shop.example.test/a b": "invalid_destination",
        "https://shop.example.test/\u00e9": "invalid_destination",
        "https://shop.example.test/a\\b": "invalid_destination",
        "https://shop.example.test/u/someone@example.test": "destination_identifier",
        "https://shop.example.test/u/someone%40example.test": "destination_identifier",
        "https://shop.example.test/c/4111-1111-1111-1111": "destination_identifier",
    }
    for url, reason in cases.items():
        assert code(parse_destination, url, SHOP, ["ref"]) == reason, url


def test_utm_precedence_is_explicit_then_template_then_destination():
    merged = merge_utm(
        {"utm_source": "dest", "utm_medium": "dest"},
        {"utm_source": "template", "utm_campaign": "template"},
        {"utm_source": "explicit"},
        "spring-2026",
    )
    assert merged == {
        "utm_campaign": "template",
        "utm_id": "spring-2026",
        "utm_medium": "dest",
        "utm_source": "explicit",
    }
    assert merge_utm({}, None, {"utm_id": "manual"}, "spring")["utm_id"] == "manual"
    for bad in [{"utm_bogus": "x"}, {"utm_source": "has space"}, {"utm_source": "a" * 65}]:
        assert code(validate_utm, bad) == "invalid_utm"
    assert code(validate_utm, {}, required=True) == "invalid_utm"


def test_issued_target_is_deterministic_and_carries_only_the_link_reference():
    parsed = parse_destination(
        "https://shop.example.test/offer?ref=spring&utm_medium=social", SHOP, ["ref"]
    )
    utm = merge_utm(parsed.utm, None, {"utm_source": "site"}, None)
    target = compose_target(parsed, utm, LINK)
    assert target == (
        "https://shop.example.test/offer?ref=spring&utm_medium=social&utm_source=site"
        f"&ts_link={LINK}"
    )
    assert compose_target(parsed, utm, LINK) == target


def test_link_references_that_look_like_card_numbers_are_still_issued():
    # Found by the final verification run: this random UUID's digit groups "2142041-6274-442"
    # form a Luhn-valid 14-digit number, which the configured-part check must not consider.
    lucky = UUID("c2142041-6274-442a-a369-9d9cdac8d98b")
    assert contains_card_number(str(lucky))
    parsed = parse_destination("https://shop.example.test/x", SHOP, [])
    assert compose_target(parsed, {}, lucky) == f"https://shop.example.test/x?ts_link={lucky}"
    with pytest.raises(LinkRuleError):
        compose_target(parsed, {"utm_term": "4111111111111111"}, lucky)
    long_path = parse_destination("https://shop.example.test/" + "a" * 1980, SHOP, [])
    with pytest.raises(LinkRuleError):
        compose_target(long_path, {"utm_source": "x" * 40}, lucky)


def test_request_authority_and_managed_targets():
    assert request_authority("Localhost:8000") == ("localhost", 8000)
    assert request_authority("go.brand.test") == ("go.brand.test", None)
    for bad in [None, "", "user@host", "host/path", "host:99999", "ho st"]:
        assert request_authority(bad) is None
    platform = platform_authorities(["127.0.0.1:8000", "go.platform.example"])
    assert is_managed_target(Origin("http", "127.0.0.1", 8000), platform, [])
    assert not is_managed_target(Origin("http", "127.0.0.1", 9000), platform, [])
    assert is_managed_target(Origin("https", "go.platform.example", None), platform, [])
    assert is_managed_target(SHOP, platform, ["shop.example.test"])
    assert not is_managed_target(SHOP, platform, ["other.example.test"])
