# Product brief
Updated: 2026-10-29. Product direction is confirmed; implementation details remain drafts.

## Confirmed owner decisions
- Serve multiple agencies and their clients from the first commercial release.
- Include both social account analytics and attribution connecting sources and content to leads and sales.
- The named platforms are Instagram, YouTube, LinkedIn, and X/Twitter. Launch priority, mandatory connectors, account types, and exact metrics remain unresolved.
- Support a broad customer market. No industry, country, CRM, or payment provider has been selected.
- Implement the backend first using FastAPI and PostgreSQL, followed by React, with Docker.
- Work through specifications, review gates, and later PRs in a repository created by the owner.
- D-013 authorizes starting the backend/database foundation through specification 001, superseding D-008's planning-only restriction for this work. D-014 approves its database tools; later business scope remains subject to review.
- D-016/D-017 authorize the six-table agency/client access model and role matrix in 002-A. Authentication, invitations, and service credentials remain subsequent slices; the commercial launch scope is unchanged.
- Maintain formal English in all project files and filenames. This does not decide the languages of the product interface (D-009).

## Proposed value journey
An agency creates a workspace, adds a client, connects authorized social accounts, registers content and links, collects visits and leads, records a verified sale or an explicitly manual entry, and reviews social performance alongside attribution and financial evidence.

Synthetic acceptance example: content link A, visit B, a form submission, a sale of 1,000 in an approved currency, and a refund of 200. Net revenue is 800. First-touch, last-touch, and linear attribution may allocate credit differently. Platform metrics remain separately identified by source and reporting period. A view does not automatically identify a person or prove a sale.

## Definitions and boundaries
- **Client:** the business served by an agency. **Lead/customer:** a visitor or buyer of that business.
- **Agency tenant:** the approved primary isolation boundary in 002-A. Client workspaces have additional access boundaries.
- **Social analytics:** aggregate measures exposed by an authorized platform account.
- **Attribution:** allocation of credit across observable events under a declared model, not causal proof.
- Missing, stale, and unsupported data must remain distinguishable from zero.
- A broad target market does not imply support for every CRM or payment provider on launch day.

## Proposed success measures
Time to first valid data; accepted, rejected, and duplicate events; attributed versus unknown coverage; financial reconciliation; connector freshness; cost per client and agency; onboarding completion; and verified isolation.

Numeric targets, budgets, delivery dates, hosting, subscription design, currencies, interface languages, and retention policies require owner decisions.
