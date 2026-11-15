# Connector runtime (specification 009-A)
Status: implemented locally under D-048 against a synthetic provider. No real provider adapter exists, and every real provider rule in `app.privacy.providers` stays blocking until its own specification (010-013) re-verifies it. Native `tracking_sys` has not received migration 0009.

## Configuration
Connectors need the D-025 token keyring of the [event collection guide](event-collection.md) (`TRACKING_TOKEN_KEYRING`, `TRACKING_TOKEN_KEYRING_ACTIVE`). Routes answer `503 connector_not_configured` while it is blank.

| Setting | Meaning |
|---|---|
| `TRACKING_CONNECTOR_SYNTHETIC_STATE` | Path of the synthetic provider's SQLite state file, shared by the API and the worker. Development only; production configuration is refused. Unset means no provider is available (`404 provider_unavailable`). |
| `TRACKING_CONNECTOR_REDIRECT_URI` | The provider callback, which must be this API's `/connectors/oauth/callback` (HTTP only on loopback). Default `http://127.0.0.1:8000/connectors/oauth/callback`. |
| `TRACKING_CONNECTOR_COMPLETE_URL` | Where the browser goes after the callback; its origin must be an allowed origin. Default `<frontend origin>/connections/complete`. |
| `TRACKING_CONNECTOR_TEARDOWN_HOURS` | Teardown deadline after a disconnect request, at most 72. The 72-hour target applies to the local synthetic slice only. |

The synthetic provider never makes network calls. Its authorization URL uses the reserved `.invalid` domain. Tests approve it with `SyntheticProvider.approve`, which stands in for the provider's consent page and returns the code that the provider would send to the callback.

## Roles
| Actor | May | May not |
|---|---|---|
| Owner/Admin (browser session) | Connect, reconnect, request a sync, disconnect | — |
| Members with client visibility, read service keys with a client grant | List and read connection status | Any mutation |
| The browser session that started an authorization | Complete its callback | Complete another session's callback |
| Worker (`tracking_app`) | Claim runs and teardowns, write fenced results, revoke, destroy and purge | Delete connections, secrets, runs or transactions |

## Flow
1. `POST /agencies/{a}/clients/{c}/connections` with `{"provider": "synthetic"}` returns `authorization_url` and sets the HttpOnly binding cookie `tracking_connector_oauth` (`__Secure-` when secure) on `/connectors/oauth`.
2. The provider redirects to `GET /connectors/oauth/callback?code=&state=`. The browser is redirected (303) to the completion URL with `result=connected&connection_id=...`, or with one fixed `error`: `connection_failed`, `connection_cancelled`, `connection_denied`, `connection_changed`, `account_mismatch`, `account_already_connected`, `provider_unavailable` or `connector_not_configured`.
3. `GET /agencies/{a}/clients/{c}/connections[/{id}]` returns the status: provider, account reference, status and reason, scopes, connection and last successful sync times, available actions, and the disconnect outcome. Sealed material, key IDs, generations, leases and digests are never returned. The `actions` flags are `true` only for an Owner or Admin session and a connection in the matching state.
4. `POST .../connections/{id}/sync` queues one single-page sync of an active connection (202). The callback also queues one.
5. `POST .../connections/{id}/reconnect` starts a new authorization for a connection in `reconnect_required`. It must return the same external account. Before the new grant replaces the previous one, the previous grant's tokens are revoked at the provider. If that revocation is not confirmed or reported unsupported, the reconnect ends with `provider_unavailable` and can be retried; the previous tokens stay outstanding for the next reconnect or disconnect.
6. `POST .../connections/{id}/disconnect` (202) stops the connection and fixes `purge_due_at`. Repeated requests return the same state.

## Worker
`python -m app.connector_worker` (from `backend/`, with the project `.venv`) runs one bounded pass and prints counts, for example `{"teardown": {"disconnected": 1}, "sync": {"succeeded": 2}}`. It runs teardowns first, then sync runs. It is not a scheduler: run it again for later work. The 72-hour target is met only if it runs within that time. Teardowns past their deadline run first, then those with the fewest attempts, so one failing provider revocation cannot hold back other connections. A sync attempt whose lease expired and was claimed again by another pass is superseded: it writes nothing.

Teardown revokes each outstanding token at the provider, refresh token first. It then destroys all sealed material (the rows stay, with NULL material and `status = destroyed`), deletes the connection's provider records, and clears the account reference. A transient revocation failure is retried on later passes. At the deadline the teardown completes anyway and reports `revocation: failed`. In that case, remove the application's access in the provider account's settings. When a newly issued grant cannot be kept and its revocation is unsupported or fails, the log event `connector_grant_disposal_failed` reports `outcome` `unsupported` or `failed`.

## Verification
The integration suite `backend/tests/integration/test_connectors.py` runs on the disposable PostgreSQL service of the [backend test guide](../../backend/tests/README.md). One case starts the worker as a separate process with the shared provider file. Never point it at `tracking_sys`.
