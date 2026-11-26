import { isIdentifier } from '@/lib/identifier';

// While the browser is at a provider, the application remembers which client the person was
// connecting, so the return leads back to that client. Only the two identifiers are kept, for
// this tab only, and they are removed when the person returns. The outcome itself comes from the
// API; this record grants nothing.
const KEY = 'connect.pendingConnection';

export interface PendingConnection {
  agencyId: string;
  clientId: string;
}

export const pendingConnection = {
  set(pending: PendingConnection): void {
    try {
      window.sessionStorage.setItem(KEY, JSON.stringify(pending));
    } catch {
      // Storage is unavailable: the return page offers the list of clients instead.
    }
  },
  /** The record of a connection that was started in this tab, if there is one. */
  get(): PendingConnection | null {
    try {
      const stored = window.sessionStorage.getItem(KEY);
      if (stored === null) return null;
      const value: unknown = JSON.parse(stored);
      if (typeof value !== 'object' || value === null) return null;
      const { agencyId, clientId } = value as Record<string, unknown>;
      return isIdentifier(agencyId) && isIdentifier(clientId) ? { agencyId, clientId } : null;
    } catch {
      return null;
    }
  },
  /** Removes the record, so it serves one return only. */
  clear(): void {
    try {
      window.sessionStorage.removeItem(KEY);
    } catch {
      // Nothing was stored.
    }
  },
};
