"""Specification 004 event collection contracts (D-027).

contract holds the pure EventEnvelope v1 rules (validation, minimization by purpose, form
mapping, fingerprints, traffic labels, webhook signatures); keys holds the independent
tombstone keyring. Database work lives in app.services.collection and HTTP in
app.api.collection.
"""
