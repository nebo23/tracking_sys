# Tasks: 014-ad-spend-capi
Status: 014-A to 014-D completed under D-063 and D-064 against synthetic Meta-shaped providers and fixture tests, and opened for review in a pull request; the merge is the owner's decision. The [evidence](evidence.md) records the checks. Preparation: the [entry review](entry-review.md) and the [implementation handoff](implementation-prompt.md).

- [x] Approve the scope and sources for advertising spend and conversion delivery (D-063, D-064; sources read in Phase 0, [entry review section 2.4](entry-review.md#24-official-sources-read-in-phase-0)).
- [x] Record the initial advertising provider (Meta, D-063). Q-001, Q-004, Q-010 and Q-012 stay open beyond what D-064 decides for this completion.
- [x] Verify dependencies: 009-connector-runtime, 007-revenue-ledger (007-A calculation and journal), 008-attribution-engine (008-A runs).
- [x] Prepare contracts and synthetic data and permission examples ([design note](design-014.md), synthetic providers, `tests/meta_graph.py`).
- [x] Define independently reviewable local changes: one commit per phase (Phase 0, design, 014-A, 014-B, 014-C, 014-D, records).
- [x] Implement 014-A (spend ingestion), 014-B (conversion delivery), 014-C (ROAS contract) and 014-D (live adapters, off by default).
- [x] Verify: rerunning spend ingestion does not duplicate totals and handles revisions, time zones and currencies (T-01 to T-10).
- [x] Verify: only verified conversions with the required consent enter the delivery outbox; a browser signal alone does not prove payment (T-20 to T-25, T-35).
- [x] Verify: retries do not create a semantically duplicate conversion; provider rejections have recorded resolution paths without endless retry loops (T-26 to T-33).
- [x] Verify: ROAS identifies its model, period and currency; zero spend does not produce a misleading infinite value (T-40 to T-47).
- [x] Update documentation, limitations and untested assumptions ([advertising guide](../../docs/engineering/advertising.md), [evidence](evidence.md)).
- [x] Push and open a pull request against `main` for review (D-063).
- [ ] Owner review and merge decision.

Follow-ups that stay open (separately gated):
- [ ] 014-E: read-only live spend check with the owner's Meta app (Facebook Login for Business, Marketing API) and an owner ad account; it needs a registered HTTPS redirect (020) or an approved feasibility tool, and confirms the unverified details recorded in the evidence (deleted ads in insights, the dataset node, the exchange answer).
- [ ] 014-F: test events to an owner dataset with a test event code; this writes to Meta and needs its own approval.
- [ ] 014-G: App Review for `ads_read`, Business Verification, Tech Provider status if required, the Data Use Checkup, and HTTPS hosting with the callbacks (020).
- [ ] The owner's decision on browser fields for website events (D8, V-9), and email or phone match keys after 006.
- [ ] 007-B journal as the persisted conversion source; ROAS read routes and reports (016); destination and account screens (018, after the owner's brief, design and brand identity); production scheduling of the worker (020).
- [ ] Google Ads, and LinkedIn Ads with Spec 012 when the owner resumes it.
- [ ] Native `tracking_sys` migration (0017 to 0019) and deployment.
