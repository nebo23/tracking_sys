"""Gmail API send-only transport for queued messages (D-022), using the standard library."""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate
from typing import Any
from uuid import UUID

from app.config import Settings

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
RATE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded"})


# Sanitized delivery failure. The code is stored as the outbox failure_code; provider response
# bodies, recipients, and message content are never included.
class GmailError(Exception):
    # Keep only the fixed failure code.
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# Owner-authorized sender for one designated mailbox. It exchanges the stored refresh token for
# short-lived access tokens (cached in process until shortly before expiry) and submits encoded
# MIME messages through users.messages.send with bounded timeouts. The opener argument allows
# tests to substitute the network; automated tests never contact Google.
class GmailSender:
    # Bind validated settings, the HTTP opener, and the per-request timeout in seconds.
    def __init__(
        self,
        settings: Settings,
        *,
        opener: Callable[..., Any] = urllib.request.urlopen,
        timeout: float = 15,
    ) -> None:
        self.settings, self.opener, self.timeout = settings, opener, timeout
        self._token: str | None = None
        self._token_deadline = 0.0

    # Perform one JSON request. HTTP errors map to fixed codes through `classify`; network,
    # timeout, and parsing errors are reported as temporary failures.
    def _json(self, request: urllib.request.Request, classify: Callable[[int, str], str]) -> dict:
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                details = json.loads(error.read() or b"{}")
            except ValueError:
                details = {}
            finally:
                error.close()
            reason = ""
            if isinstance(details.get("error"), dict):
                reasons = details["error"].get("errors") or [{}]
                reason = str(reasons[0].get("reason", ""))
            raise GmailError(classify(error.code, reason)) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise GmailError("gmail_temporary_failure") from None

    # Return a cached access token or refresh it. A refresh response must grant the send-only
    # scope; invalid or revoked authorization is reported without retrying in this call.
    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_deadline:
            return self._token
        body = urllib.parse.urlencode(
            {
                "client_id": self.settings.gmail_client_id,
                "client_secret": self.settings.gmail_client_secret.get_secret_value(),
                "refresh_token": self.settings.gmail_refresh_token.get_secret_value(),
                "grant_type": "refresh_token",
            }
        ).encode()
        request = urllib.request.Request(
            TOKEN_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        result = self._json(
            request,
            lambda status, _: (
                "gmail_authorization_revoked" if status in {400, 401} else "gmail_temporary_failure"
            ),
        )
        token = result.get("access_token")
        if not isinstance(token, str) or not token:
            raise GmailError("gmail_authorization_revoked")
        if SEND_SCOPE not in str(result.get("scope", "")).split():
            raise GmailError("gmail_scope_missing")
        lifetime = int(result.get("expires_in", 0) or 0)
        self._token, self._token_deadline = token, time.monotonic() + max(0, lifetime - 60)
        return token

    # Send one decrypted outbox payload from the configured sender with the stable outbox
    # Message-ID. Google acceptance and the outbox commit are not atomic, so a timeout after
    # acceptance can lead to a duplicate on retry; exactly-once delivery is not claimed.
    def send(self, message_id: UUID, payload: dict[str, str]) -> None:
        email = EmailMessage(policy=SMTP)
        email["From"] = self.settings.gmail_sender
        email["To"] = payload["to"]
        email["Subject"] = payload["subject"]
        email["Date"] = formatdate(usegmt=True)
        email["Message-ID"] = f"<{message_id}@tracking.invalid>"
        email.set_content(payload["body"])
        raw = base64.urlsafe_b64encode(email.as_bytes()).decode()
        request = urllib.request.Request(
            SEND_URL,
            data=json.dumps({"raw": raw}).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._access_token()}",
                "Content-Type": "application/json",
            },
        )
        try:
            self._json(request, _classify_send)
        except GmailError as error:
            if error.code == "gmail_authorization_failed":
                self._token = None
            raise


# Map a users.messages.send HTTP failure to a fixed code.
def _classify_send(status: int, reason: str) -> str:
    if status == 401:
        return "gmail_authorization_failed"
    if status == 429 or reason in RATE_REASONS:
        return "gmail_rate_limited"
    if status == 403:
        return "gmail_access_denied"
    if status == 400:
        return "gmail_message_rejected"
    return "gmail_temporary_failure"
