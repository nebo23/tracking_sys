import { useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { useEffect, useRef } from 'react';

import { agenciesQuery, type Role } from '@/api/agencies';
import { clientKey, clientQuery, type Client } from '@/api/clients';

import { forgetOtherAgencies, isManager, useTenantAddress } from './agency';

const agencyRoute = getRouteApi('/workspace/agencies/$agencyId');
const clientRoute = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId');

export interface AgencyScope {
  agencyId: string;
  role: Role;
  /** True for an owner or admin. The API decides in any case; this only hides what it would refuse. */
  manager: boolean;
}

/** The agency of a page under /agencies/{agency}, with the person's role in it. */
export function useAgency(): AgencyScope {
  const { agencyId } = agencyRoute.useParams();
  const { data: agencies } = useSuspenseQuery(agenciesQuery);
  // The route does not open for an agency the person does not belong to; the least role is a safe default.
  const role = agencies.find((agency) => agency.agency_id === agencyId)?.role ?? 'client_viewer';
  return { agencyId, role, manager: isManager(role) };
}

export interface ClientScope extends AgencyScope {
  clientId: string;
  client: Client;
}

/** The client of a page under /agencies/{agency}/clients/{client}. The route has already loaded it. */
export function useClient(): ClientScope {
  const scope = useAgency();
  const { clientId } = clientRoute.useParams();
  const { data: client } = useSuspenseQuery(clientQuery(scope.agencyId, clientId));
  return { ...scope, clientId, client };
}

/**
 * Removes what was loaded for a tenant once the person has left it (acceptance criterion 2):
 * the data of a client when they move to another client or to the agency level, and the data of
 * an agency when they move to another agency. It runs after the new page is drawn, when nothing
 * on screen still reads the old data; removing it earlier would only have it loaded again.
 */
export function useForgetWhatWasLeft(currentAgencyId: string | undefined): void {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useTenantAddress();
  const previous = useRef<{ agencyId: string; clientId: string } | null>(null);
  useEffect(() => {
    if (currentAgencyId) forgetOtherAgencies(queryClient, currentAgencyId);
  }, [queryClient, currentAgencyId]);
  useEffect(() => {
    const before = previous.current;
    const now = agencyId && clientId ? { agencyId, clientId } : null;
    if (before && (before.agencyId !== now?.agencyId || before.clientId !== now?.clientId)) {
      queryClient.removeQueries({ queryKey: clientKey(before.agencyId, before.clientId) });
    }
    previous.current = now;
  }, [queryClient, agencyId, clientId]);
}
