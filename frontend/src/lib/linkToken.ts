import { useSyncExternalStore } from 'react';

// Mail links carry their token in the fragment: /auth/reset-password#token=...
// The token is taken out of the address bar before the router reads the address, and it is kept
// in memory only. It never enters storage, the query cache, a query string or a log.

export type LinkKind = 'reset' | 'invitation';

const kindOfPath: Record<string, LinkKind> = {
  '/auth/reset-password': 'reset',
  '/auth/accept-invitation': 'invitation',
};

const held = new Map<LinkKind, string>();
const listeners = new Set<() => void>();

const changed = () => {
  for (const listener of listeners) listener();
};

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
  if (shape.test(token)) {
    held.set(kind, token);
    changed();
  }
}

/** The token of the link that was opened in this visit, if any. */
export function heldLinkToken(kind: LinkKind): string | null {
  return held.get(kind) ?? null;
}

/** Forgets the token once it was used or refused. */
export function releaseLinkToken(kind: LinkKind): void {
  if (held.delete(kind)) changed();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** The held token for a screen, which is drawn again when a link arrives or its token is spent. */
export function useLinkToken(kind: LinkKind): string | null {
  return useSyncExternalStore(subscribe, () => heldLinkToken(kind));
}
