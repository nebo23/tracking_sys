# Connector readiness contract
Status: Draft checklist. Validate each provider separately; one platform's access grant proves nothing about another.

| Field | Required evidence before approval |
|---|---|
| Provider and use case | Distinguish social reads, advertising reads, conversion writes, and business webhooks. |
| Account type | Verify supported professional accounts, channels, pages, members, or advertising accounts. |
| Access | Record program, tier, application review, business verification, and actual account role; never include tokens. |
| Authentication | Document OAuth flow, scopes, token expiry, revocation, refresh, or webhook secrets. |
| Metric catalog | Name, definition, unit, interval, dimensions, source version, and permitted aggregation. |
| Collection | Pagination/cursors, polling/webhooks, quotas, retry behavior, and historical backfill. |
| Freshness | Observed delay, complete-through date, last synchronization, and native timezone. |
| Cost | Billing unit, budget, limits, and the date when pricing must be revalidated. |
| Restrictions | Retention, deletion, export, derived-metric, and combination permissions. |
| Recovery | Behavior for 401, 403, 429, 5xx, deleted content, invalid scopes, and exhausted credit. |
| Isolation | Agency/client credentials, job context, and denied cross-client access. |
| Evidence | Official documentation URL/date, sanitized authorized test fixtures, and exact verification results. |

## Proposed state model
- Connection: pending / active / degraded / revoked / disconnected.
- Metric: available / pending / unavailable / unsupported / stale.
- Job: queued / running / succeeded / retrying / failed / canceled.

These names remain drafts; approve final enumerations with the API contract.

## States requiring clear disclosure
Show incomplete intervals, unsupported metrics, withdrawn consent, expired tokens, insufficient provider entitlement, budget stops, dates outside API history, and prohibited derivations explicitly. None should default to zero.

## Reference comparison
On an authorized test account, compare the same metric, timezone, range, and aggregation with the source platform. Record delays and filtering differences. Prevent a combined total when definitions are incompatible. Real customer accounts require authorization.
