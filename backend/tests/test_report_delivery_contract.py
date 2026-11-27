"""Contract tests of 016-C report delivery without a database (specification 016-C, D-095).

They cover the binding of an export's seal (RV02) and the stored report parameters. Every
identifier and file is synthetic.
"""

import os
from datetime import date
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag

from app.privacy.token_secrets import (
    LocalKeyring,
    SecretContext,
    open_bytes,
    open_secret,
    seal,
    seal_bytes,
)
from app.reporting.common import ReportError
from app.services.report_exports import query_of, stored_parameters
from app.services.reporting import ReportQuery

KEYRING = LocalKeyring({"k1": os.urandom(32)}, "k1")


def _context(agency, client, export):
    return SecretContext(agency, client, export, export, "report_export", 1)


def test_rv02_seal_is_bound_to_export_agency_and_client():
    agency, client, export = uuid4(), uuid4(), uuid4()
    data = b'"row_type","family"\r\n"metadata","social"\r\n'
    sealed = seal_bytes(KEYRING, data, _context(agency, client, export))
    assert data not in sealed.ciphertext and len(sealed.ciphertext) == len(data) + 16
    assert open_bytes(KEYRING, sealed, _context(agency, client, export)) == data
    for other in (
        _context(uuid4(), client, export),
        _context(agency, uuid4(), export),
        _context(agency, client, uuid4()),
        SecretContext(agency, client, export, export, "conversion_payload", 1),
        SecretContext(agency, client, export, export, "report_export", 2),
    ):
        with pytest.raises(InvalidTag):
            open_bytes(KEYRING, sealed, other)


def test_text_secrets_keep_their_envelope():
    context = SecretContext(uuid4(), uuid4(), uuid4(), uuid4(), "access_token", 1)
    sealed = seal(KEYRING, "synthetic-token-value", context)
    assert open_secret(KEYRING, sealed, context) == "synthetic-token-value"
    assert open_bytes(KEYRING, sealed, context) == b"synthetic-token-value"


@pytest.mark.parametrize(
    "query",
    [
        ReportQuery(
            "social",
            date(2026, 11, 1),
            date(2026, 11, 8),
            True,
            connection_id=uuid4(),
            view="daily",
            metrics=("views", "reach"),
        ),
        ReportQuery("spend", date(2026, 11, 1), date(2026, 11, 8), False, uuid4(), level="ad"),
        ReportQuery("revenue", date(2026, 11, 1), date(2026, 11, 8), True),
        ReportQuery(
            "attribution",
            date(2026, 11, 1),
            date(2026, 11, 8),
            False,
            view="models",
            group_by="link",
        ),
        ReportQuery(
            "roas",
            date(2026, 11, 1),
            date(2026, 11, 8),
            False,
            uuid4(),
            level="campaign",
            model_version=uuid4(),
        ),
        ReportQuery("funnel", date(2026, 11, 1), date(2026, 11, 8), True, group_by="content"),
    ],
)
def test_stored_parameters_rebuild_the_same_query(query):
    stored = stored_parameters(query)
    assert "start" not in stored and "family" not in stored
    assert query_of(query.family, stored, query.start, query.end) == query


def test_stored_parameters_keep_the_route_rules():
    with pytest.raises(ReportError, match="comparison_unsupported"):
        query_of(
            "social",
            {"compare": True, "view": "content_cohort"},
            date(2026, 11, 1),
            date(2026, 11, 8),
        )
    with pytest.raises(ReportError, match="invalid_period"):
        query_of("revenue", {"compare": False}, date(2026, 11, 1), date(2026, 12, 3))
