# First-party website tracker
Reserved for a JavaScript package authored by this project and installed on client websites. It collects approved events according to the consent and ingestion contracts.

This is distinct from the React dashboard and from downloaded third-party dependencies. External JavaScript dependencies belong in package manifests and lockfiles and are installed in `node_modules/`, which is not committed.

Implementation depends on specs 003-005. Do not capture sensitive form fields or sessions by default.
