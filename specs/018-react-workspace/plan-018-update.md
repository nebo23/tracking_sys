# Plan of P0: both 018 branches up to date with `main`

Status: phase P0 of the [completion handoff](implementation-prompt-completion.md), approved with D1-D12 of the [completion entry review](entry-review-completion.md) by D-106 on 2026-11-28. Done on 2026-11-28: see the [evidence](evidence-018-update.md). The completion approval was D-099 when this plan was written and became D-106 in P5; the table of branches and the renumbering step below keep the number of that time.

## 1. Starting point (2026-11-28)

| Reference | Head | Note |
|---|---|---|
| `origin/main` | `e3b3005` | Spec 016-C merged (PR 20); highest decision D-095. |
| `origin/claude/keen-fermat-otlr9d` | `4618501` | D-096 (merge of 016-C) and D-097 (preparation of 017-B, which reserves D-098 for its approval). One commit newer than the packet's baseline `2a0deb1`; it changes only records and the 017-B packet. |
| `codex/spec-018-react-workspace` | `1c4ee9e` | Pull request 17, the only open pull request; highest decision D-087. |
| `codex/spec-018-workspace-screens` | `b3be159` | 018-B, 018-D, the A to Z designs, the completion packet and D-099. |

## 2. Pull request 17 (`codex/spec-018-react-workspace`)

1. `git merge origin/main`. The trial merge predicts conflicts only in `AGENTS.md`, `README.md`, `docs/planning/decisions.md` and `specs/README.md`. Each keeps every decision and status line of both sides in numeric order; the register keeps `main`'s numbering note on D-081 to D-087 and this branch's records of them.
2. `npm run api:types`, `npm run api:check`, `npm run typecheck`.
3. Agreement versions (section 4.2 of the entry review, section 6 of the [017-A design](../017-saas-lifecycle/design-017a.md)):
   - a query of `GET /auth/agreements`, read again before each submission;
   - `agreements: {terms, privacy}` with `POST /auth/login` and `POST /auth/register`, and `?terms=&privacy=` with `GET /auth/google/start`;
   - `422 agreement_required`: the versions of the answer replace the cached ones, the box is unticked, the email stays, and the notice A03 appears above the form; the Google completion page with `error=agreement_required` sends the person back to the sign-in page with the same notice;
   - unit tests for each case, and the sign-in journeys against the API of `main`.
4. The checks of section 5 on this branch, then a push: the one update of pull request 17 (D-091).

## 3. The stacked branch (`codex/spec-018-workspace-screens`)

1. `git merge codex/spec-018-react-workspace`.
2. **Renumbering** (D-096): this branch's D-093 becomes D-100 and its D-094 becomes D-101, the next free numbers after D-099. Every reference in `AGENTS.md`, `docs/planning/decisions.md`, `specs/018-react-workspace/` and `frontend/` changes; the numbering note of Spec 018 gains one line. The numbers are checked again on every branch and pull request just before this step. Commit messages are not rewritten.
3. **The rest of section 4.2:**
   - B11: a row with `actor_kind` `platform_operator` names the Connect operator; the actions and resources that 017-A and 016-C added to the closed lists get their sentences (the unit test that reads the backend's lists fails until they do);
   - the switcher and the agency list: a closing agency (listed only to its Owners) is marked as closing; until the closing page B15 exists (P3), choosing it opens a notice that the agency is closing instead of its clients, whose routes the API refuses;
   - `409 plan_limit_reached`: the existing sentence stays; the link to Plan and usage arrives with P3.
4. The checks of section 5, then a push.

## 4. Deviations from the packet

None planned. A needed API change, another package or a conflict outside the four record files goes back to the owner before code depends on it.

## 5. Checks

- Backend, from `backend/` with the disposable PostgreSQL service: `ruff check app tests migrations`, `ruff format --check app tests migrations`, `pytest -m "not integration" -q`, `pytest -m integration -q`.
- Frontend, from `frontend/`: `npm ci`, `npm run api:check`, `npm run typecheck`, `npm run lint`, `npm test`, `npm run build:check`, and the journeys in Chromium and Firefox, one browser per run.
- `git diff --check`; free space on drive C: before every journey or integration run.
