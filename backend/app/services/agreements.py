"""Record of agreement to the Terms of Service and the Privacy Policy (017-A, D-092 D10).

Registration and every sign-in (password and Google) send the versions the person accepted.
They must equal the current versions of the settings; otherwise the request is refused with
agreement_required before any credential, account or provider work, so the answer reveals
nothing. A row is written per document only when the account has none for that version, in the
transaction that creates the account or the session. Rows hold the user, the document, the
version label, the time and the channel only.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import UserAgreement


@dataclass(frozen=True)
class Versions:
    terms: str
    privacy: str
    published: bool


class AgreementRequired(Exception):
    """The request did not accept the current versions; 422 with those versions."""

    code = "agreement_required"

    def __init__(self, current: Versions) -> None:
        self.current = current
        super().__init__(self.code)


def current(settings: Settings) -> Versions:
    return Versions(
        settings.terms_version, settings.privacy_version, settings.agreement_texts_published
    )


# Whether the accepted versions are exactly the current ones.
def accepted(settings: Settings, terms: str | None, privacy: str | None) -> bool:
    now = current(settings)
    return terms == now.terms and privacy == now.privacy


# Refuse a request that did not accept the current versions.
def require(settings: Settings, terms: str | None, privacy: str | None) -> None:
    if not accepted(settings, terms, privacy):
        raise AgreementRequired(current(settings))


# Record the current versions for the account through one channel, once per version.
# Returns the number of new rows (0 when the account already agreed to both versions).
def record(session: Session, settings: Settings, user_id: UUID, channel: str) -> int:
    now = current(settings)
    statement = (
        insert(UserAgreement)
        .values(
            [
                {
                    "id": uuid4(),
                    "user_id": user_id,
                    "document": document,
                    "version": version,
                    "channel": channel,
                }
                for document, version in (("terms", now.terms), ("privacy", now.privacy))
            ]
        )
        .on_conflict_do_nothing(constraint="uq_user_agreements_user_document_version")
    )
    return session.execute(statement).rowcount
