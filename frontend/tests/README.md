# Frontend tests
Two kinds of checks, both described in the [frontend guide](../README.md); their results for slice 018-A are in the [018-A evidence](../../specs/018-react-workspace/evidence-018a.md).

- `unit/` runs in jsdom with Vitest and Testing Library. `support/api.ts` is a stand-in for the API that answers by method and path and keeps what was sent; `support/app.tsx` opens the whole application at an address. Tests use the interface as a person does: by role, label and keyboard. Every value is synthetic.
- `browser/` holds the Playwright journeys. They run in Chromium and Firefox against the real API on a disposable stack (`support/stack.ts`): a PostgreSQL container of its own, the migrations, the API and the built application, with mail captured as files. The stack never uses the owner's database (D-015) and removes itself when a run ends. `10-accessibility.spec.ts` runs axe-core on every screen in both languages and both themes.

Later slices add checks for permissions, client switching, and the loading, empty, error, partial and stale states of every data screen.
