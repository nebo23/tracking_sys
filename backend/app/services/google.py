"""Google OpenID Connect sign-in mapped onto the existing opaque sessions (D-022)."""

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ExternalIdentity, OAuthTransaction, User
from app.security import AuthError, digest, keyed_digest, new_token, normalize_email, now_utc
from app.services.auth import AuthService

DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPE = "openid email profile"
TRANSACTION_SECONDS = 600
AUTHORITATIVE_DOMAINS = frozenset({"gmail.com", "googlemail.com"})
Purpose = Literal["login", "link"]


# Sanitized provider failure (unreachable endpoint, rejected code exchange, unusable keys).
# The code is a fixed value suitable for the completion redirect; provider bodies are dropped.
class GoogleProviderError(Exception):
    # Keep only the fixed failure code.
    def __init__(self, code: str = "google_unavailable") -> None:
        self.code = code
        super().__init__(code)


# Network access to Google's published OpenID endpoints with bounded timeouts. The discovery
# document and signing keys are cached in process. Tests replace this object on app.state
# with a substitute, so automated tests never contact Google.
class GoogleOIDC:
    # Bind validated settings and the per-request timeout in seconds.
    def __init__(self, settings: Settings, *, timeout: float = 10) -> None:
        self.settings, self.timeout = settings, timeout
        self._configuration: dict[str, Any] | None = None
        self._configuration_deadline = 0.0
        self._keys: jwt.PyJWKClient | None = None

    # Perform one JSON request; any HTTP, network, or parsing failure becomes a provider error.
    def _json(self, request: urllib.request.Request | str, code: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise GoogleProviderError(code) from None
        if not isinstance(result, dict):
            raise GoogleProviderError(code)
        return result

    # Return the cached discovery document (refreshed hourly) after checking the fields used.
    def configuration(self) -> dict[str, Any]:
        if self._configuration is None or time.monotonic() >= self._configuration_deadline:
            document = self._json(DISCOVERY_URL, "google_unavailable")
            required = ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer")
            if not all(isinstance(document.get(name), str) for name in required):
                raise GoogleProviderError()
            self._configuration = document
            self._configuration_deadline = time.monotonic() + 3600
            self._keys = None
        return self._configuration

    # Exchange an authorization code with the client secret and PKCE verifier; returns the
    # token response. Tokens are used only for validation and are never stored or logged.
    def exchange(self, code: str, verifier: str) -> dict[str, Any]:
        body = urllib.parse.urlencode(
            {
                "code": code,
                "client_id": self.settings.google_client_id,
                "client_secret": self.settings.google_client_secret.get_secret_value(),
                "redirect_uri": self.settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            }
        ).encode()
        request = urllib.request.Request(
            self.configuration()["token_endpoint"],
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return self._json(request, "google_sign_in_failed")

    # Return the public key that signed an ID token, from Google's published key set.
    def signing_key(self, id_token: str) -> Any:
        if self._keys is None:
            self._keys = jwt.PyJWKClient(
                self.configuration()["jwks_uri"], cache_keys=True, timeout=self.timeout
            )
        try:
            return self._keys.get_signing_key_from_jwt(id_token).key
        except jwt.PyJWTError:
            raise GoogleProviderError("google_sign_in_failed") from None


# PKCE verifier and OIDC nonce are derived from the raw state with purpose-separated HMACs,
# so the transaction row stores neither. The verifier is 64 hexadecimal characters.
def pkce_verifier(settings: Settings, raw_state: str) -> str:
    return keyed_digest(settings, "oauth-pkce", raw_state)


# Nonce sent in the authorization request and required back in the ID token.
def oidc_nonce(settings: Settings, raw_state: str) -> str:
    return keyed_digest(settings, "oidc-nonce", raw_state)


# Start an authorization: store a single-use transaction (state and browser-binding digests,
# purpose, link user, ten-minute expiry) in the caller's transaction and build the Google
# authorization URL with the identity scopes, state, nonce, and S256 PKCE challenge. Returns
# the URL and the raw binding value for the HttpOnly binding cookie.
def begin_authorization(
    session: Session,
    settings: Settings,
    provider: GoogleOIDC,
    purpose: Purpose,
    user_id: UUID | None = None,
) -> tuple[str, str]:
    raw_state, binding = new_token(), new_token()
    session.add(
        OAuthTransaction(
            purpose=purpose,
            user_id=user_id,
            state_digest=digest(raw_state),
            binding_digest=digest(binding),
            expires_at=now_utc() + timedelta(seconds=TRANSACTION_SECONDS),
        )
    )
    challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(pkce_verifier(settings, raw_state).encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    query = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": raw_state,
            "nonce": oidc_nonce(settings, raw_state),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{provider.configuration()['authorization_endpoint']}?{query}", binding


# Validate the ID token from a token response: Google signature, RS256 only, allowed issuer,
# this client's audience, expiry, issued-at, subject, and the transaction nonce.
def validated_claims(
    settings: Settings, provider: GoogleOIDC, tokens: dict[str, Any], raw_state: str
) -> dict[str, Any]:
    id_token = tokens.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise GoogleProviderError("google_sign_in_failed")
    key = provider.signing_key(id_token)
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=ISSUERS,
            leeway=30,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError:
        raise AuthError("google_sign_in_failed", 400) from None
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not hmac.compare_digest(
        nonce, oidc_nonce(settings, raw_state)
    ):
        raise AuthError("google_sign_in_failed", 400)
    subject = claims.get("sub")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
        raise AuthError("google_sign_in_failed", 400)
    return claims


# Apply the approved account policy (D-022) to validated claims and return the local user:
# a known issuer/subject signs in its active verified user; a link attaches one Google
# identity to the user that started it; a new authoritative verified Gmail or Workspace
# address creates a verified, password-less user with no agency membership; an existing
# local email is never linked automatically (google_link_required).
def apply_account_policy(
    session: Session,
    settings: Settings,
    claims: dict[str, Any],
    purpose: Purpose,
    link_user_id: UUID | None,
) -> User:
    auth = AuthService(session, settings)
    issuer, subject = str(claims["iss"]), str(claims["sub"])

    def identity_for_subject() -> ExternalIdentity | None:
        return session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "google", ExternalIdentity.subject == subject
            )
        )

    def active_verified(user_id: UUID) -> User:
        try:
            user = auth._lock_user(user_id)
        except AuthError:
            raise AuthError("google_sign_in_failed", 403) from None
        if user.email_verified_at is None:
            raise AuthError("google_sign_in_failed", 403)
        return user

    identity = identity_for_subject()
    if purpose == "link":
        assert link_user_id is not None
        user = active_verified(link_user_id)
        if identity is not None:
            if identity.user_id != user.id:
                raise AuthError("google_identity_in_use", 409)
            return user
        linked = session.scalar(
            select(ExternalIdentity.id).where(
                ExternalIdentity.user_id == user.id, ExternalIdentity.provider == "google"
            )
        )
        if linked is not None:
            raise AuthError("google_already_linked", 409)
        session.add(
            ExternalIdentity(user_id=user.id, provider="google", issuer=issuer, subject=subject)
        )
        auth.event("google_identity_linked", user.id)
        return user

    if identity is None:
        email = claims.get("email")
        if not isinstance(email, str) or claims.get("email_verified") is not True:
            raise AuthError("google_email_not_verified", 403)
        domain = email.rsplit("@", 1)[-1].lower()
        if domain not in AUTHORITATIVE_DOMAINS and not claims.get("hd"):
            raise AuthError("google_email_not_verified", 403)
        try:
            normalized = normalize_email(email)
        except ValueError:
            raise AuthError("google_email_not_verified", 403) from None
        auth._serialize_email(normalized)
        # A concurrent first sign-in for the same subject may have finished meanwhile.
        identity = identity_for_subject()
        if identity is None:
            if session.scalar(select(User.id).where(User.email_normalized == normalized)):
                raise AuthError("google_link_required", 409)
            name = claims.get("name")
            display = name.strip()[:200] if isinstance(name, str) and name.strip() else ""
            now = now_utc()
            user = User(
                email_normalized=normalized,
                display_name=display or normalized.split("@", 1)[0][:200],
                email_verified_at=now,
            )
            session.add(user)
            session.flush()
            session.add(
                ExternalIdentity(
                    user_id=user.id,
                    provider="google",
                    issuer=issuer,
                    subject=subject,
                    last_login_at=now,
                )
            )
            auth.event("google_registered", user.id)
            return user

    user = active_verified(identity.user_id)
    identity.last_login_at = now_utc()
    auth.event("google_login_succeeded", user.id)
    return user


# Complete a callback: lock the transaction by state digest and require the matching browser
# binding, no prior use, and no expiry, then consume it in the caller's transaction. The code
# exchange, token validation, account policy, and (for login) session issuance run in a
# savepoint, so a rejected sign-in rolls back its partial work while the consumed transaction
# still commits and cannot be replayed. Returns the user, the purpose, and the raw session
# token for login (None for link).
def complete_authorization(
    session: Session,
    settings: Settings,
    provider: GoogleOIDC,
    raw_state: str,
    binding: str | None,
    code: str,
) -> tuple[User, Purpose, str | None]:
    transaction = session.scalar(
        select(OAuthTransaction)
        .where(OAuthTransaction.state_digest == digest(raw_state))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        transaction is None
        or transaction.consumed_at is not None
        or transaction.expires_at <= now_utc()
        or not binding
        or not hmac.compare_digest(transaction.binding_digest, digest(binding))
    ):
        raise AuthError("google_sign_in_failed", 400)
    transaction.consumed_at = now_utc()
    purpose: Purpose = "link" if transaction.purpose == "link" else "login"
    link_user_id = transaction.user_id
    session.flush()
    with session.begin_nested():
        tokens = provider.exchange(code, pkce_verifier(settings, raw_state))
        claims = validated_claims(settings, provider, tokens, raw_state)
        user = apply_account_policy(session, settings, claims, purpose, link_user_id)
        raw = AuthService(session, settings).issue_session(user) if purpose == "login" else None
    return user, purpose, raw
