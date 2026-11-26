# 018-react-workspace — React workspace and user experience
Status: design decisions approved (D-075, D-076); slice 018-A is implemented under the [018-A plan](plan-018a.md) (D-077) and awaits the owner's review, see the [018-A evidence](evidence-018a.md). Later slices are not approved. Level: L6. Prepared: 2026-10-28. English revision: 2026-10-29. Design preparation under D-074 (2026-11-25): see the [entry review](entry-review.md) and the [design language](../../docs/design/README.md). Owner design review D-075 (2026-11-25): the logo, the sign-in screen and the search field are approved. D-076 (2026-11-26): the remaining design decisions are approved as recommended.

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

Open decisions: the currency and FX part of Q-006, and the packages of later slices under Q-009 (D-077 decides the list of 018-A). D-076 decides the interface languages and the toolchain families. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
D-074 (2026-11-25) authorized the design preparation. D-075 (2026-11-25) approved the logo, the sign-in screen and the search field. D-076 (2026-11-26) approved the remaining design decisions and the slices 018-A to 018-D. D-077 (2026-11-26) approved the package list and the implementation of 018-A, and D-078 the licences of eight packages that came with it. The owner's review of the implemented slice is pending.
