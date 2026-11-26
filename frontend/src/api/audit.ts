import { queryOptions } from '@tanstack/react-query';

import { tenantKey } from './agencies';
import { api, call } from './client';
import type { components } from './schema';

export type AuditEvent = components['schemas']['AuditResponse'];

/** The most the API returns: the newest changes of the agency, newest first. */
export const AUDIT_LIMIT = 100;

export const auditQuery = (agencyId: string) =>
  queryOptions({
    queryKey: tenantKey(agencyId, 'audit'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/audit', { params: { path: { agency_id: agencyId }, query: { limit: AUDIT_LIMIT } } })),
  });
