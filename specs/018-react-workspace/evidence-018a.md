# 018-A evidence

Status: in progress. The installation gate of the [018-A plan](plan-018a.md) (section 4.5) was passed on 2026-11-26: the owner accepted the eight packages of section 1.4 (D-078).

## 1. Installation on 2026-11-26
Environment: Windows 11, Node.js 24.17.0, npm 11.13.0. The install ran inside `frontend/` from `package.json`, in which every version is exact, and created `package-lock.json`.

| Check | Result |
|---|---|
| Packages | 404 installed; the lockfile has 435 entries, which include optional packages for other platforms. |
| Direct versions | All thirty match section 4 of the plan (`npm ls --depth=0`). |
| Size | `node_modules` is 294 MB. Free space on drive C went from 3.7 GB to 3.0 GB, which includes npm's own cache. |
| Browsers | None downloaded. |

### 1.1 Security audit
`npm audit` reports no critical and no high finding, and seven of moderate severity. All seven are one advisory: `minimatch` can be made slow by a crafted pattern. It is reached only through `typescript-eslint` 8.72.2 and its `@typescript-eslint` packages, which are used for static checks during development. The patterns it reads come from this project's own configuration, and the package is not part of the application that a browser loads. Removing the finding means another version of `typescript-eslint`, which needs a decision (D-077).

### 1.2 Notice from the registry
npm marks `eslint` 9.39.5 as no longer supported by its maintainers. ESLint 9 was chosen because `eslint-plugin-jsx-a11y` 6.10.2, which carries the accessibility rules, accepts ESLint up to 9 (plan, section 4.3). The tool runs only during development.

### 1.3 Licences of the full tree
Read from the lockfile, 435 entries:

| Licence | Entries |
|---|---|
| MIT | 348 |
| Apache-2.0 | 34 |
| MPL-2.0 | 14 |
| ISC | 14 |
| BSD-2-Clause | 9 |
| BSD-3-Clause | 5 |
| OFL-1.1 | 3 |
| BlueOak-1.0.0 | 2 |
| Python-2.0, CC-BY-4.0, Unlicense, CC0-1.0, 0BSD, "MIT OR CC0-1.0" | 1 each |

### 1.4 Licences outside the approved list
Section 4.5 of the plan approves MIT, Apache-2.0, BSD, ISC, OFL-1.1 and MPL-2.0. Eight packages carry another licence. None was chosen directly; each comes with an approved package.

| Package | Licence | Part of the application | Comes with |
|---|---|---|---|
| `tslib` 2.9.1 | 0BSD | Yes | `react-aria-components` |
| `isbot` 5.2.4 | Unlicense | Yes | `@tanstack/react-router` |
| `minimatch` 10.2.6 | BlueOak-1.0.0 | No, development only | `typescript-eslint` |
| `lru-cache` 11.5.3 | BlueOak-1.0.0 | No, development only | `jsdom` |
| `argparse` 2.0.1 | Python-2.0 | No, development only | `eslint` |
| `caniuse-lite` 1.0.30001828 | CC-BY-4.0 | No, development only | `eslint-plugin-react-hooks` |
| `language-subtag-registry` 0.3.23 | CC0-1.0 | No, development only | `eslint-plugin-jsx-a11y` |
| `type-fest` 4.41.0 | MIT OR CC0-1.0 | No, development only | `openapi-typescript` |

Assessment: all eight are permissive. None requires publishing source code and none restricts commercial use. 0BSD, the Unlicense and CC0-1.0 ask for nothing at all; BlueOak-1.0.0 and Python-2.0 ask to keep the licence text; CC-BY-4.0 covers a data file used by a development tool and asks for attribution if that data is redistributed, which the application does not do. This is an engineering reading, not legal advice.

Gate: section 4.5 sends such a finding to the owner before any code is written. The owner accepted the eight packages at their locked versions on 2026-11-26 (D-078).
