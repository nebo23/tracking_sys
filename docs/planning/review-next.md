# Next specification review
Updated: 2026-11-10. Specifications 001/002 are merged in PR 1 and specification 003 with its corrections in PR 2 (`bab3a33`). Specification 004 is in design review on `codex/spec-004-event-collection`.

1. Review [design revision 2](../../specs/004-event-collection/design.md) and decide D1-D11 in the [decision packet](../../specs/004-event-collection/decision-packet.md).
2. Decide the separate predecessor items P1-P4 listed there (local 003 card-scan follow-up, status reconciliation, owner edits, legacy mail).
3. After the decisions are recorded, implementation proceeds through slices 004-B to 004-F in the [plan](../../specs/004-event-collection/plan.md); each is verified on disposable storage.
4. Keep native rollout and legacy-mail policy separate from synthetic design and testing. Record transferred consumer obligations without marking them complete.

Do not run native inspection, migrations, deletion, or live provider requests as a checklist shortcut. Native revision was last verified as 0004_identity on 2026-11-04; `main` expects 0006_account_closure. Do not silently choose markets, retention, capacity, hosting, or providers. See the [readiness review](spec-004-readiness.md).
