import { queryOptions } from '@tanstack/react-query';

import { tenantKey } from './agencies';
import { api, call } from './client';
import { clientKey } from './clients';
import type { components } from './schema';

export type Connection = components['schemas']['ConnectionResponse'];
export type Coverage = components['schemas']['CoverageResponse'];
export type StreamCoverage = components['schemas']['StreamCoverage'];
export type SyncState = components['schemas']['SyncState'];
export type CostState = components['schemas']['CostState'];
export type ConnectInput = components['schemas']['ConnectInput'];
export type ProviderId = ConnectInput['provider'];
export type AgentApproval = components['schemas']['AgentApproval'];

const scope = (agencyId: string, clientId: string) => ({ params: { path: { agency_id: agencyId, client_id: clientId } } });
const one = (agencyId: string, clientId: string, connectionId: string) => ({
  params: { path: { agency_id: agencyId, client_id: clientId, connection_id: connectionId } },
});

export const connectionsKey = (agencyId: string, clientId: string) => clientKey(agencyId, clientId, 'connections');

/** The accounts a client has connected, as the person may see them. */
export const connectionsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: connectionsKey(agencyId, clientId),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/connections', scope(agencyId, clientId))),
  });

/**
 * The same list as the clients page reads it, once per client, for the state of each row. It has
 * a key of its own under the agency: leaving a client removes that client's workspace data and
 * leaves the agency's list as it is.
 */
export const clientSummaryQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: tenantKey(agencyId, 'clients', 'connections', clientId),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/connections', scope(agencyId, clientId))),
    staleTime: 60_000,
  });

/** Freshness, the latest run, each stream's covered range and the cost of the day. */
export const coverageQuery = (agencyId: string, clientId: string, connectionId: string) =>
  queryOptions({
    queryKey: [...connectionsKey(agencyId, clientId), connectionId, 'coverage'] as const,
    queryFn: () =>
      call(
        api.GET('/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/coverage', one(agencyId, clientId, connectionId)),
      ),
  });

/** Starts an authorization at the provider. The answer is the address the browser goes to. */
export function connect(agencyId: string, clientId: string, input: ConnectInput) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/connections', { ...scope(agencyId, clientId), body: input }));
}

export function reconnect(agencyId: string, clientId: string, connectionId: string, approval: AgentApproval | null) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/reconnect', {
      ...one(agencyId, clientId, connectionId),
      body: approval ? { agent_approval: approval } : null,
    }),
  );
}

/** Queues a read of the newest data. An open run of the same kind is returned as it is. */
export function requestSync(agencyId: string, clientId: string, connectionId: string) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/sync', {
      ...one(agencyId, clientId, connectionId),
      body: null,
    }),
  );
}

export function disconnect(agencyId: string, clientId: string, connectionId: string) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/connections/{connection_id}/disconnect', one(agencyId, clientId, connectionId)),
  );
}
