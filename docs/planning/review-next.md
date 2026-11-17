# Next specification review
Updated: 2026-11-10. Review [Spec 004 readiness](spec-004-readiness.md) and its [entry packet](../../specs/004-event-collection/entry-review.md). Specifications 001/002 are merged in PR 1. Specification 003 is completed at contract level with corrections in open PR 2.

1. Review corrected specification 003 in [PR 2](https://github.com/nebo23/tracking_sys/pull/2), including the bounded card-scan follow-up and verification evidence.
2. Record the owner's PR 2 merge decision. The earlier explicit no-merge instruction remains in force; preparation does not execute a merge.
3. After merge, create `codex/spec-004-event-collection` from updated merged main, preserving unrelated local edits. Fetch and compare the remote; the local main ref is stale.
4. Review the 004 event, schema, trust, deduplication, consent, deletion and retention design before dependent implementation.
5. Keep native rollout and legacy-mail policy separate from synthetic design/testing. Record transferred consumer obligations without marking them complete.

Do not run native inspection, migrations, deletion, or live provider requests as a checklist shortcut. Native revision was last verified as 0004_identity on 2026-11-04; this branch expects 0006_account_closure. Do not silently choose markets, retention, capacity, hosting, or providers.
