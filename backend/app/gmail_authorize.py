"""Owner-run Gmail sender authorization: python -m app.gmail_authorize [--env-file PATH].

Opens Google's consent page in the owner's browser for the send-only Gmail scope through a
loopback redirect with state and PKCE, then stores the sender refresh token in the ignored
environment file without printing it. Requires a separate Desktop OAuth client (D-022).
"""

import argparse
import base64
import hashlib
import hmac
import json
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dotenv import dotenv_values, set_key

from app.config import PROJECT_ROOT

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
WAIT_SECONDS = 300


# Raised for any helper failure; messages are fixed and never contain secrets.
class AuthorizationFailed(Exception):
    """A sender authorization step failed; the message is safe to print."""


# Read the sender client from an installed-application JSON download (if given) or from the
# environment file. The sign-in Web client is refused, so the two consents stay separate.
def sender_client(env_file: Path, client_json: Path | None) -> tuple[str, str]:
    values = dotenv_values(env_file)
    if client_json is not None:
        try:
            block = json.loads(client_json.read_text(encoding="utf-8"))["installed"]
            client_id, client_secret = block["client_id"], block["client_secret"]
        except (OSError, ValueError, KeyError, TypeError):
            raise AuthorizationFailed(
                "The client JSON must be a Desktop (installed) OAuth client download."
            ) from None
    else:
        client_id = (values.get("TRACKING_GMAIL_CLIENT_ID") or "").strip()
        client_secret = (values.get("TRACKING_GMAIL_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise AuthorizationFailed("Set the Gmail sender client ID and secret first.")
    if client_id == (values.get("TRACKING_GOOGLE_CLIENT_ID") or "").strip():
        raise AuthorizationFailed(
            "The sender must use a Desktop OAuth client separate from the sign-in client."
        )
    return client_id, client_secret


# Build the consent URL for the send-only scope with offline access, state, and S256 PKCE.
def authorization_url(client_id: str, redirect_uri: str, state: str, verifier: str) -> str:
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return (
        AUTHORIZATION_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": SEND_SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )


# Wait for exactly one loopback redirect, validate its state, and return the authorization
# code. The browser receives a short completion page; nothing secret is printed.
def wait_for_code(server: HTTPServer, state: str) -> str:
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        # Handle the single redirect from Google.
        def do_GET(self) -> None:  # noqa: N802 - name required by BaseHTTPRequestHandler
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            received = query.get("state", [""])[0]
            if query.get("code") and hmac.compare_digest(received, state):
                result["code"] = query["code"][0]
                message = "Sender authorization received. You may close this window."
            else:
                result["error"] = "denied"
                message = "Sender authorization was not completed. You may close this window."
            body = message.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # Suppress request logging; the redirect URL contains the authorization code.
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server.RequestHandlerClass = Handler
    server.timeout = WAIT_SECONDS
    server.handle_request()
    if "code" not in result:
        raise AuthorizationFailed("Authorization was cancelled, denied, or timed out.")
    return result["code"]


# Exchange the code with the PKCE verifier and return the refresh token, requiring the granted
# scope to be exactly the send-only Gmail scope.
def exchange(client_id: str, client_secret: str, code: str, verifier: str, redirect: str) -> str:
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            tokens = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise AuthorizationFailed("Google rejected or did not answer the code exchange.") from None
    if str(tokens.get("scope", "")).split() != [SEND_SCOPE]:
        raise AuthorizationFailed("The granted scope is not exactly the Gmail send-only scope.")
    refresh = tokens.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise AuthorizationFailed("Google returned no refresh token; repeat with consent.")
    return refresh


# Store the sender values in the environment file (quoted) without echoing any of them.
def store(env_file: Path, values: dict[str, str]) -> None:
    for name, value in values.items():
        set_key(env_file, name, value, quote_mode="always")


# Command-line entry point for the owner. Returns a process exit code.
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Authorize the Gmail sender (send-only scope).")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument(
        "--client-json", type=Path, help="Desktop OAuth client JSON (for example in local-data)."
    )
    parser.add_argument("--no-browser", action="store_true", help="Print the URL only.")
    options = parser.parse_args(argv)
    try:
        if not options.env_file.is_file():
            raise AuthorizationFailed("The environment file does not exist.")
        client_id, client_secret = sender_client(options.env_file, options.client_json)
        server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        redirect = f"http://127.0.0.1:{server.server_address[1]}/"
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        url = authorization_url(client_id, redirect, state, verifier)
        print("Sign in with the designated sender account and approve sending email only.")
        print(f"If the browser does not open, visit:\n{url}")
        if not options.no_browser:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        try:
            code = wait_for_code(server, state)
        finally:
            server.server_close()
        refresh = exchange(client_id, client_secret, code, verifier, redirect)
        values = {"TRACKING_GMAIL_REFRESH_TOKEN": refresh}
        if options.client_json is not None:
            values |= {
                "TRACKING_GMAIL_CLIENT_ID": client_id,
                "TRACKING_GMAIL_CLIENT_SECRET": client_secret,
            }
        store(options.env_file, values)
    except AuthorizationFailed as failure:
        print(f"Sender authorization failed: {failure}", file=sys.stderr)
        return 1
    print(f"Stored the sender authorization in {options.env_file.name} (values not shown).")
    print("Set TRACKING_GMAIL_SENDER to the same account, then TRACKING_MAIL_MODE=gmail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
