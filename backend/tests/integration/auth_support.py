"""Shared authentication test values (017-A, D-092 decision D10).

Registration and every sign-in send the Terms of Service and Privacy Policy versions that the
person accepted; the shared helpers and the direct calls of the existing suites send the
current development versions from the settings' defaults.
"""

from app.config import Settings

AGREEMENTS = {
    "terms": Settings.model_fields["terms_version"].default,
    "privacy": Settings.model_fields["privacy_version"].default,
}
GOOGLE_AGREEMENTS = dict(AGREEMENTS)  # the query parameters of GET /auth/google/start
