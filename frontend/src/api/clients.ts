import { queryOptions } from '@tanstack/react-query';

import { tenantKey } from './agencies';
import { api, call } from './client';
import { PAGE_SIZE, readAll } from './pages';
import type { components } from './schema';

export type Client = components['schemas']['ClientResponse'];

/** The clients of an agency that the person may read: all of them for a manager, the granted ones otherwise. */
export const clientsKey = (agencyId: string) => tenantKey(agencyId, 'clients');

/** The archived clients of an agency, which only its owners and admins may list (018-B plan, B2). */
export const archivedClientsKey = (agencyId: string) => tenantKey(agencyId, 'archived-clients');

/**
 * Everything that belongs to one client is keyed under the agency and the client, so it can be
 * removed as a whole when the person leaves that client (acceptance criterion 2).
 */
export const clientKey = (agencyId: string, clientId: string, ...rest: readonly unknown[]) =>
  tenantKey(agencyId, 'client', clientId, ...rest);

const listed = (agencyId: string, status: 'active' | 'archived') =>
  readAll((offset) =>
    call(
      api.GET('/agencies/{agency_id}/clients', {
        params: { path: { agency_id: agencyId }, query: { limit: PAGE_SIZE, offset, ...(status === 'archived' ? { status } : {}) } },
      }),
    ),
  );

export const clientsQuery = (agencyId: string) =>
  queryOptions({
    queryKey: clientsKey(agencyId),
    queryFn: () => listed(agencyId, 'active'),
  });

export const archivedClientsQuery = (agencyId: string) =>
  queryOptions({
    queryKey: archivedClientsKey(agencyId),
    queryFn: () => listed(agencyId, 'archived'),
  });

export const clientQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: clientKey(agencyId, clientId, 'profile'),
    queryFn: () =>
      call(api.GET('/agencies/{agency_id}/clients/{client_id}', { params: { path: { agency_id: agencyId, client_id: clientId } } })),
  });

export function createClient(agencyId: string, name: string) {
  return call(api.POST('/agencies/{agency_id}/clients', { params: { path: { agency_id: agencyId } }, body: { name } }));
}

export function renameClient(agencyId: string, clientId: string, name: string) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}', {
      params: { path: { agency_id: agencyId, client_id: clientId } },
      body: { name },
    }),
  );
}

/** Archives a client, or restores an archived one. Nothing of the client is deleted either way. */
export function setClientStatus(agencyId: string, clientId: string, status: 'active' | 'archived') {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}', {
      params: { path: { agency_id: agencyId, client_id: clientId } },
      body: { status },
    }),
  );
}
