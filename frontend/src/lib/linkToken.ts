// Mail links carry their token in the fragment: /auth/reset-password#token=...
// The token is taken out of the address bar before the router reads the address, and it is kept
// in memory only. It never enters storage, the query cache, a query string or a log.

export type LinkKind = 'reset' | 'invitation';

const kindOfPath: Record<string, LinkKind> = {
  '/auth/reset-password': 'reset',
  '/auth/accept-invitation': 'invitation',
};

const held = new Map<LinkKind, string>();

// The API issues 43 URL-safe characters and accepts 32 to 128 (TokenInput in the contract).
const shape = /^[A-Za-z0-9_-]{32,128}$/;

/** Moves the token of a mail link from the address bar into memory. Safe to call again. */
export function captureLinkToken(): void {
  const kind = kindOfPath[window.location.pathname.replace(/\/+$/, '')];
  const match = /(?:^#|&)token=([^&]*)/.exec(window.location.hash);
  if (!kind || !match) return;
  let token = '';
  try {
    token = decodeURIComponent(match[1] ?? '');
  } catch {
    token = '';
  }
  window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
  if (shape.test(token)) held.set(kind, token);
}

/** The token of the link that was opened in this visit, if any. */
export function heldLinkToken(kind: LinkKind): string | null {
  return held.get(kind) ?? null;
}

/** Forgets the token once it was used or refused. */
export function releaseLinkToken(kind: LinkKind): void {
  held.delete(kind);
}
