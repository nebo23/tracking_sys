# Application source
The source of Connect (specification 018, slices 018-A and 018-B). The [frontend guide](../README.md) describes the layout and the rules; the [018-A plan](../../specs/018-react-workspace/plan-018a.md) and the [018-B plan](../../specs/018-react-workspace/plan-018b.md) describe the design.

- `main.tsx` starts the application: it takes a mail-link token out of the address bar, applies the stored language and theme, creates the router and watches for an ended session.
- `app/` holds the providers, the routes with their guards, the session life cycle, the preferences and the workspace shell. `agency.ts` and `tenant.ts` say which agency and client a page belongs to and remove what was loaded for one the person has left.
- `api/` holds the types generated from `contracts/openapi.json`, the client and the error table. `schema.d.ts` is generated; do not edit it.
- `features/` holds the screens, grouped by what a person does.
- `components/`, `lib/`, `i18n/` and `styles/` hold what the screens share.

Agency and client context, permissions that follow the API, and loading, empty, error, partial and stale states remain the design considerations for every later slice. A new screen of a client reads `useClient()` for its scope and keys its data with `clientKey(agency, client, ...)`.
