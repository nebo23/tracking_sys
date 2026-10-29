# Source PDF review
Status: analysis and proposals for discussion, not approval or removal of source requirements.

## Coverage and omissions
The source is a broad tracking and attribution feature map, not an implementation-ready specification. Its 109 features cover collection, links, identity, attribution, calls/sales, revenue, advertising, reporting, visitor behavior, advanced measurement, data quality, AI, partners, teams, and privacy. The 16 additional ideas remain separate in the [feature register](feature-register.md).

The owner added a core capability that the source does not specify adequately: social analytics for Instagram, YouTube, LinkedIn, and X. Dedicated specifications preserve this scope; advertising spend and attribution do not substitute for social analytics.

## Corrections for review
| Source claim or classification | Proposed clarification |
|---|---|
| Server-side tracking prevents tracking loss from blockers | It improves reliability but cannot recover events that never arrived or were not permitted to be collected. It does not override privacy choices. |
| Retain UTM parameters forever | Define retention periods, consent requirements, and provider restrictions. |
| Cross-device identification for every visitor | Use permitted, verified identifiers for deterministic linking. Do not merge people solely because of an IP address or shared device. |
| SHA-256 is encryption | Hashing is not encryption or automatic anonymization. Transport/storage encryption and key management are separate controls. |
| Replay masking is required for MVP | Safe collection is foundational; replay remains optional and requires its own review. |
| Multi-workspace support can wait | Multi-agency isolation is a launch foundation under the owner's confirmed decision. |
| SSO and audit logs are one advanced item | Separate foundational auditing from later enterprise SSO/SAML. |
| Data residency is a later concern | Multiple regions may be deferred; the initial storage-region decision precedes real customer data. |
| All dashboards are live | First-party events may be near real time; social providers can lag. Show measurement timestamps and last synchronization. |
| First/Last/Linear/Time-decay/U/W models all belong in MVP | Seek approval for an initial First/Last/Linear subset; other models need separate rules and tests. |
| Screenshot-to-revenue | OCR may suggest a match; an image alone is not a verified financial entry. |
| WhatsApp AI infers sales from conversations | Purchase intent or a promise to pay differs from confirmed payment or collection. |
| A YouTube moment caused a sale | Aggregate retention does not establish minute-level causality or viewer identity. Correlation analysis also requires provider-policy review. |
| Complete WhatsApp forwarding trees | Hidden forwarding is unavailable. Clicks on explicitly issued referral links can be observed. |
| Confidence as a verified percentage | Begin with evidence sources and classes; probability percentages require calibration. |
| PPP-normalized revenue | Treat it as optional economic comparison, separate from the financial ledger. |
| Ideas do not exist in the market | These are hypotheses, not established uniqueness claims; the market review identifies existing overlap. |

## Proposed gaps to address
1. Distinguish agencies, client businesses, and their customers; test both cross-agency and cross-client isolation.
2. Define token, consent, disconnection, and deletion lifecycles.
3. Version event schemas and define idempotency, replay, and late-arrival behavior.
4. Maintain an auditable financial ledger rather than overwriting a sale total on every webhook.
5. Attach source, definition, currency, time, attribution window, and completeness to metrics.
6. Budget API usage and define SaaS metering, quotas, and subscription entitlements.
7. Plan job recovery, backfill, rate limits, observability, migrations, backups, and restore exercises.
8. Separate permissions for social analytics, advertisements, and messages.
9. Distinguish verified webhooks from lower-trust browser events; prevent poisoning and spam.
10. Define authorized support, offboarding, export, and account closure with audit evidence.

See the [research report](../../reports/market-and-feasibility.md) for evidence and the [decision register](../planning/decisions.md) before approving selections.
