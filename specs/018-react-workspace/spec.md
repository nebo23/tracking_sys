# 018-react-workspace — React workspace and user experience
Status: design decisions approved (D-082, D-083); slice 018-A is implemented under the [018-A plan](plan-018a.md) (D-084) and awaits the owner's review, see the [018-A evidence](evidence-018a.md). D-093 (2026-11-26) authorizes the remaining slices 018-B to 018-D; the parts of 018-B that the present API can back are implemented under the [018-B plan](plan-018b.md) and await the owner's review, see the [018-B evidence](evidence-018b.md). Level: L6. Prepared: 2026-10-28. English revision: 2026-10-29. Design preparation under D-081 (2026-11-25): see the [entry review](entry-review.md) and the [design language](../../docs/design/README.md). Owner design review D-082 (2026-11-25): the logo, the sign-in screen and the search field are approved. D-083 (2026-11-26): the remaining design decisions are approved as recommended.

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

Open decisions: the currency and FX part of Q-006, and the packages of later slices under Q-009 (D-084 decides the list of 018-A). D-083 decides the interface languages and the toolchain families. See the [decision register](../../docs/planning/decisions.md).

## Owner approval
D-081 (2026-11-25) authorized the design preparation. D-082 (2026-11-25) approved the logo, the sign-in screen and the search field. D-083 (2026-11-26) approved the remaining design decisions and the slices 018-A to 018-D. D-084 (2026-11-26) approved the package list and the implementation of 018-A, and D-085 the licences of eight packages that came with it. D-086 (2026-11-26) approved opening the pull request of 018-A against main. The owner's review of the implemented slice is pending. D-093 (2026-11-26) authorized implementing 018-B to 018-D on `codex/spec-018-workspace-screens`; a new package, a change to the API, a pull request for these slices and the merge keep their own decisions.
