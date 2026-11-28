"""The Paddle adapter and the billing settings (specification 017-C, D-103; BL22 and BL09).

Unit cases without a database: the settings validation of design-017c.md section 11, the calls
of section 6 against the synthetic Paddle-shaped server of tests/paddle_api.py, the closed error
codes, and the urllib transport against a local socket for its bounds. No Paddle call is made.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from paddle_api import API_KEY, CLIENT_TOKEN, LIVE_API_KEY, WEBHOOK_SECRET, PaddleApi, paddle_id
from pydantic import SecretStr, ValidationError

from app.billing import paddle
from app.billing.paddle import PaddleClient, ProviderError, Reply
from app.config import Settings


def billing_settings(settings, **changes):
    values = {
        "billing_enabled": True,
        "billing_paddle_api_key": SecretStr(API_KEY),
        "billing_paddle_webhook_secret": SecretStr(WEBHOOK_SECRET),
        **changes,
    }
    return Settings(_env_file=None, **(settings.model_dump() | values))


def test_bl22_settings_validation(settings):
    # Off by default, with blank credentials, a 14-day trial and the sandbox.
    assert settings.billing_enabled is False
    assert (settings.billing_trial_days, settings.billing_paddle_environment) == (14, "sandbox")
    assert settings.billing_paddle_api_key.get_secret_value() == ""
    enabled = billing_settings(settings, billing_paddle_client_token=CLIENT_TOKEN)
    assert enabled.billing_enabled and enabled.billing_paddle_client_token == CLIENT_TOKEN
    live = billing_settings(
        settings, billing_paddle_environment="live", billing_paddle_api_key=SecretStr(LIVE_API_KEY)
    )
    assert live.billing_paddle_environment == "live"
    refused = (
        {"billing_paddle_api_key": SecretStr("")},
        {"billing_paddle_webhook_secret": SecretStr("")},
        {"billing_paddle_api_key": SecretStr(API_KEY + "x")},
        {"billing_paddle_webhook_secret": SecretStr("whsec_" + "x" * 32)},
        {"billing_paddle_environment": "live"},  # a sandbox key for the live environment
        {"billing_paddle_client_token": "live_" + "c" * 27},  # a live token for the sandbox
        {"billing_paddle_client_token": "test_short"},
        {"billing_trial_days": 0},
        {"billing_trial_days": 31},
        {"billing_paddle_environment": "staging"},
    )
    for change in refused:
        with pytest.raises(ValidationError) as raised:
            billing_settings(settings, **change)
        text = str(raised.value)
        # A refusal names the setting, never a credential value.
        for secret in (API_KEY, WEBHOOK_SECRET, "whsec_", CLIENT_TOKEN):
            assert secret not in text, change
    # While billing is off, blank or unusual values are not validated (nothing uses them).
    off = Settings(
        _env_file=None,
        **(settings.model_dump() | {"billing_paddle_api_key": SecretStr("ignored")}),
    )
    assert off.billing_enabled is False
    assert paddle.build_billing_provider(settings) is None
    client = paddle.build_billing_provider(enabled)
    assert isinstance(client, PaddleClient) and client.environment == "sandbox"
    assert API_KEY not in repr(client) and API_KEY not in str(vars(client).keys())


def test_get_price_reads_the_registered_price():
    api = PaddleApi()
    monthly = api.add_price(2900, "month")
    client = PaddleClient(API_KEY, "sandbox", api)
    price = client.get_price(monthly)
    assert (price.id, price.status, price.amount_cents, price.currency) == (
        monthly,
        "active",
        2900,
        "USD",
    )
    assert (price.interval, price.frequency) == ("month", 1)
    request = api.requests[-1]
    assert (request.method, request.path) == ("GET", f"/prices/{monthly}")
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert request.headers["Paddle-Version"] == "1"
    # The path is never built from an unchecked value.
    for bad in ("pri_../transactions", f"{monthly}/x", "PRI_" + "a" * 26):
        with pytest.raises(ProviderError) as raised:
            client.get_price(bad)
        assert raised.value.code == "provider_invalid_response"
    assert len(api.requests) == 1
    with pytest.raises(ProviderError) as raised:
        client.get_price(paddle_id("pri"))
    assert raised.value.code == "provider_not_found"


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (500, "internal_error", "provider_unavailable"),
        (503, "service_unavailable", "provider_unavailable"),
        (429, "too_many_requests", "provider_rate_limited"),
        (401, "authentication_malformed", "provider_unauthorized"),
        (403, "forbidden", "provider_unauthorized"),
        (404, "not_found", "provider_not_found"),
        (409, "subscription_locked_renewal", "subscription_locked"),
        (409, "subscription_locked_processing", "subscription_locked"),
        (400, "subscription_locked_pending_changes", "pending_change"),
        (400, "subscription_update_when_past_due", "past_due"),
        (400, "subscription_is_canceled_action_invalid", "subscription_canceled"),
        (400, "subscription_update_when_canceled", "subscription_canceled"),
        (429, "subscription_immediate_charge_hour_limit_exceeded", "provider_rate_limited"),
        (400, "subscription_immediate_charge_24_hour_limit_exceeded", "change_limit"),
        (400, "invalid_field", "provider_rejected"),
    ],
)
def test_errors_map_to_closed_codes(status, code, expected):
    api = PaddleApi()
    price = api.add_price(100)
    api.fail_next(status, code, headers={"retry-after": "60"})
    with pytest.raises(ProviderError) as raised:
        PaddleClient(API_KEY, "sandbox", api).get_price(price)
    assert raised.value.code == expected
    assert raised.value.retry_after == (60 if status == 429 else None)
    # The provider's detail and request ID are never kept.
    assert "Synthetic detail" not in str(raised.value) and "synthetic-request" not in str(
        raised.value
    )


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {"data": None},
        {"data": {"id": "other"}},
        {"data": {"id": "{id}", "status": "deleted", "unit_price": {}}},
        {"data": {"id": "{id}", "status": "active", "unit_price": {"amount": "-1"}}},
        {
            "data": {
                "id": "{id}",
                "status": "active",
                "unit_price": {"amount": "100", "currency_code": "usd"},
            }
        },
        {
            "data": {
                "id": "{id}",
                "status": "active",
                "unit_price": {"amount": "100", "currency_code": "USD"},
                "billing_cycle": {"interval": "month", "frequency": True},
            }
        },
    ],
)
def test_malformed_answers_are_invalid(body):
    api = PaddleApi()
    price = api.add_price(100)
    text = json.dumps(body).replace("{id}", price)
    api.answer_next(Reply(200, json.loads(text)))
    with pytest.raises(ProviderError) as raised:
        PaddleClient(API_KEY, "sandbox", api).get_price(price)
    assert raised.value.code == "provider_invalid_response"


class _Handler(BaseHTTPRequestHandler):
    reply: bytes = b"{}"
    status: int = 200

    def do_GET(self):  # noqa: N802
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.reply)))
        self.end_headers()
        self.wfile.write(self.reply)

    def log_message(self, *args):  # silence the test server
        return


def _serve(reply: bytes, status: int = 200):
    handler = type("Handler", (_Handler,), {"reply": reply, "status": status})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/prices/x"


def test_transport_bounds_its_answer_and_hides_failures():
    server, url = _serve(json.dumps({"data": {"ok": True}}).encode())
    try:
        assert paddle.http_send("GET", url, {}, None).body == {"data": {"ok": True}}
    finally:
        server.shutdown()
    server, url = _serve(b"x" * (paddle.MAX_RESPONSE + 1))
    try:
        with pytest.raises(ProviderError) as raised:
            paddle.http_send("GET", url, {}, None)
        assert raised.value.code == "provider_unavailable"
    finally:
        server.shutdown()
    server, url = _serve(b"not json", status=502)
    try:
        reply = paddle.http_send("GET", url, {}, None)
        assert (reply.status, reply.body) == (502, None)
    finally:
        server.shutdown()
    # A refused connection is provider_unavailable without the address.
    with pytest.raises(ProviderError) as raised:
        paddle.http_send("GET", url, {}, None)
    assert raised.value.code == "provider_unavailable" and "127.0.0.1" not in str(raised.value)
    assert paddle.TIMEOUT == 10
