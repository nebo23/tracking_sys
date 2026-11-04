"""Specification 003 contract libraries (D-025): consent, collection minimization, deletion
and tombstones, token envelope encryption, provider policy rules, and the restore journal.

These modules hold no state and create no tables. The specifications that collect, store,
deliver, or restore data (004, 005, 006, 009-016, 019, 020) must call them at their enforcement
points; until those consumers exist, the tests demonstrate the contracts only.
"""
