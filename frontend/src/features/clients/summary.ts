import type { Connection } from '@/api/connections';

/** What the list of clients says about one client's connections. */
export interface ClientSummary {
  /** Connections that still exist: active, waiting for a reconnect, or being removed. */
  live: Connection[];
  /** The ones that stopped working until someone reconnects them. */
  reconnect: Connection[];
  /** The newest successful synchronization among the live connections, if any has happened. */
  lastSync: string | null;
  state: 'none' | 'reconnect' | 'disconnecting' | 'connected';
}

export function summarize(connections: readonly Connection[]): ClientSummary {
  const live = connections.filter((connection) => connection.status !== 'disconnected');
  const reconnect = live.filter((connection) => connection.status === 'reconnect_required');
  const synced = live
    .map((connection) => connection.last_successful_sync_at)
    .filter((moment): moment is string => typeof moment === 'string')
    .sort();
  let state: ClientSummary['state'] = 'connected';
  if (live.length === 0) state = 'none';
  else if (reconnect.length > 0) state = 'reconnect';
  else if (live.every((connection) => connection.status === 'disconnecting')) state = 'disconnecting';
  return { live, reconnect, lastSync: synced.at(-1) ?? null, state };
}
