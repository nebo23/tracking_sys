# 018-react-workspace — React workspace and user experience
Status: Draft; implementation is not approved. Level: L6. Prepared: 2026-10-28. English revision: 2026-10-29.

## Sources
USER React; PDF-013,029,030,065,068,069,098,101,103. See the [feature register](../../docs/product/feature-register.md). Inclusion does not imply launch approval.

## Objective and proposed scope
Provide authentication flows, agency/client switching, connections, dashboards, journeys, links, reports, and settings with responsive and accessible interactions.

## Out of scope
Unreviewed UI design, library, TypeScript, or interface-language choices, and displaying demonstration data as live data.

## Acceptance criteria
1. A user connects an account, sees its status, and accesses clearly sourced social analytics and attribution workflows.
2. Switching clients clears state/cache that could expose the previous client's data; deep links cannot bypass API authorization.
3. Approved RTL/LTR layouts, keyboard navigation, and loading, empty, error, stale, and partial states work correctly.
4. Budgets, financial data, and permissions match backend rules; mobile layouts retain essential actions.
5. Production secrets are absent from browser bundles, and potentially dangerous content is rendered safely.

## Required design contracts
A typed API client after toolchain approval; define route, permission, and state matrices before components.

## Dependencies and open decisions
Dependencies: [016-analytics-reporting](../016-analytics-reporting/spec.md), [017-saas-lifecycle](../017-saas-lifecycle/spec.md)

Open decisions: Q-006, Q-009; approve user flows and design before implementation. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
Detailed specification approval is pending. Record the owner decision, date, and scope boundaries before implementation.
