import { useSuspenseQuery, type QueryClient } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';

import { agenciesQuery, tenantRoot, type AgencyAccess } from '@/api/agencies';

// The agency a person works in. Only its identifier is remembered, and it is forgotten at sign-out.
const KEY = 'connect.agency';

function read(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function write(agencyId: string | null): void {
  try {
    if (agencyId === null) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, agencyId);
  } catch {
    // Storage is unavailable: the choice lasts for the visit.
  }
}

let chosen: string | null = read();
const listeners = new Set<() => void>();

export const agencyChoice = {
  get: (): string | null => chosen,
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  set(agencyId: string | null): void {
    chosen = agencyId;
    write(agencyId);
    for (const listener of listeners) listener();
  },
};

/** The chosen agency while the person still belongs to it, otherwise the first one. */
export function currentAccess(agencies: readonly AgencyAccess[], choice: string | null): AgencyAccess | undefined {
  return agencies.find((agency) => agency.agency_id === choice) ?? agencies[0];
}

export function useCurrentAgency(): AgencyAccess | undefined {
  const { data: agencies } = useSuspenseQuery(agenciesQuery);
  const choice = useSyncExternalStore(agencyChoice.subscribe, agencyChoice.get);
  return currentAccess(agencies, choice);
}

/** Moves to another agency and drops everything that was loaded for the previous one. */
export function switchAgency(queryClient: QueryClient, agencyId: string): void {
  agencyChoice.set(agencyId);
  queryClient.removeQueries({ queryKey: tenantRoot });
}
