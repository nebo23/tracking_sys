import { queryOptions } from '@tanstack/react-query';

import { api, call } from './client';
import type { components } from './schema';

export type AgencyAccess = components['schemas']['AgencyAccess'];
export type Agency = components['schemas']['AgencyResponse'];
export type Role = components['schemas']['Role'];

// What a person may see about their own agencies: the list and each agency's name.
export const agenciesKey = ['agencies'] as const;

// Data that belongs to one agency is keyed under ['tenant', agencyId, ...], so it can be removed
// as a whole when the person moves to another agency or signs out (acceptance criterion 2).
export const tenantRoot = ['tenant'] as const;
export const tenantKey = (agencyId: string, ...rest: readonly unknown[]) => [...tenantRoot, agencyId, ...rest] as const;

/** The agencies the signed-in person belongs to, with the role in each. */
export const agenciesQuery = queryOptions({
  queryKey: agenciesKey,
  queryFn: () => call(api.GET('/agencies')),
});

export const agencyQuery = (agencyId: string) =>
  queryOptions({
    queryKey: [...agenciesKey, agencyId] as const,
    queryFn: () => call(api.GET('/agencies/{agency_id}', { params: { path: { agency_id: agencyId } } })),
  });

export function createAgency(name: string) {
  return call(api.POST('/agencies', { body: { name } }));
}
