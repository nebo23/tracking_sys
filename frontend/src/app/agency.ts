import { useSuspenseQuery, type QueryClient } from '@tanstack/react-query';
import { useParams } from '@tanstack/react-router';
import { useSyncExternalStore } from 'react';

import { agenciesQuery, tenantRoot, type AgencyAccess, type Role } from '@/api/agencies';
import { isIdentifier } from '@/lib/identifier';

// The agency a person last worked in. Only its identifier is remembered, and it is forgotten at
// sign-out. The address names the agency of a page; this choice only decides where "/" leads.
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

/** The agency and the client that the address names, when it names them by an identifier. */
export function useTenantAddress(): { agencyId: string | undefined; clientId: string | undefined } {
  const agencyId = useParams({ strict: false, select: (params) => params.agencyId });
  const clientId = useParams({ strict: false, select: (params) => params.clientId });
  return { agencyId: isIdentifier(agencyId) ? agencyId : undefined, clientId: isIdentifier(clientId) ? clientId : undefined };
}

/**
 * The agency a person is working in: the one in the address, and on a page whose address names
 * none (the account page) the one they last worked in.
 */
export function useCurrentAgency(): AgencyAccess | undefined {
  const { data: agencies } = useSuspenseQuery(agenciesQuery);
  const choice = useSyncExternalStore(agencyChoice.subscribe, agencyChoice.get);
  const { agencyId } = useTenantAddress();
  return agencies.find((agency) => agency.agency_id === agencyId) ?? currentAccess(agencies, choice);
}

/** Owners and admins manage the agency: its clients, people, keys and connections. */
export const isManager = (role: Role | undefined): boolean => role === 'owner' || role === 'admin';

/**
 * Drops everything that was loaded for any agency other than the one a person works in, so one
 * tenant's data is not kept beside another's (acceptance criterion 2). Every key of tenant data
 * names its agency, so nothing of one agency can be drawn for another in any case.
 */
export function forgetOtherAgencies(queryClient: QueryClient, agencyId: string): void {
  queryClient.removeQueries({
    queryKey: tenantRoot,
    predicate: (query) => query.queryKey[1] !== agencyId,
  });
}
