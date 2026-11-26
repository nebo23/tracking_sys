import { queryOptions } from '@tanstack/react-query';

import { tenantKey } from './agencies';
import { api, call } from './client';
import { PAGE_SIZE, readAll } from './pages';
import type { components } from './schema';

export type ServiceKey = components['schemas']['ServiceKeyResponse'];
export type ServiceKeyInput = components['schemas']['ServiceKeyInput'];
export type IssuedServiceKey = components['schemas']['IssuedServiceKey'];

export const keysKey = (agencyId: string) => tenantKey(agencyId, 'keys');

/** What the API keeps about each key: its name, kind, state and dates. Never the key itself. */
export const keysQuery = (agencyId: string) =>
  queryOptions({
    queryKey: keysKey(agencyId),
    queryFn: () =>
      readAll((offset) =>
        call(
          api.GET('/agencies/{agency_id}/service-credentials', {
            params: { path: { agency_id: agencyId }, query: { limit: PAGE_SIZE, offset } },
          }),
        ),
      ),
  });

/** The answer holds the key once. It is shown to the person and kept nowhere by the application. */
export function issueKey(agencyId: string, input: ServiceKeyInput) {
  return call(api.POST('/agencies/{agency_id}/service-credentials', { params: { path: { agency_id: agencyId } }, body: input }));
}

export function revokeKey(agencyId: string, credentialId: string) {
  return call(
    api.DELETE('/agencies/{agency_id}/service-credentials/{credential_id}', {
      params: { path: { agency_id: agencyId, credential_id: credentialId } },
    }),
  );
}
