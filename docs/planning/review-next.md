# Next specification review
Review the completed local scope of specification 002 before progression or upload.

1. Read the approved [auth design](../../specs/002-tenancy-access/auth-design.md) and [current evidence](../../specs/002-tenancy-access/auth-evidence.md).
2. Inspect 0003_auth and all 16 empty application tables in native tracking_sys.
3. Review the 115 passing cases, especially isolation, revocation, invitation races, key scope, and audit atomicity.
4. Follow the [local auth walkthrough](../engineering/authentication.md) to create synthetic review data if desired.
5. Review [OpenAPI](../../contracts/openapi.json) and the deferrals: Google/Facebook sign-in, external email, React, and future job/export/report consumers.
6. Record findings and owner acceptance. Push/PR requires upload approval under D-012; merge remains the owner's decision.

Specification 003 is the next planned review, particularly retention/consent/deletion before real customer data. Do not silently choose markets, retention periods, hosting, or production providers.
