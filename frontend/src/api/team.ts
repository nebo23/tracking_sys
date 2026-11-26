import { queryOptions } from '@tanstack/react-query';

import { tenantKey } from './agencies';
import { api, call } from './client';
import { PAGE_SIZE, readAll } from './pages';
import type { components } from './schema';

export type Invitation = components['schemas']['InvitationResponse'];
export type InvitationInput = components['schemas']['InvitationInput'];
export type ClientGrant = components['schemas']['ClientGrantInput'];

export const invitationsKey = (agencyId: string) => tenantKey(agencyId, 'invitations');

/** Every invitation of the agency, oldest first. Readable by its owners and admins. */
export const invitationsQuery = (agencyId: string) =>
  queryOptions({
    queryKey: invitationsKey(agencyId),
    queryFn: () =>
      readAll((offset) =>
        call(
          api.GET('/agencies/{agency_id}/invitations', { params: { path: { agency_id: agencyId }, query: { limit: PAGE_SIZE, offset } } }),
        ),
      ),
  });

export function invite(agencyId: string, input: InvitationInput) {
  return call(api.POST('/agencies/{agency_id}/invitations', { params: { path: { agency_id: agencyId } }, body: input }));
}

export function revokeInvitation(agencyId: string, invitationId: string) {
  return call(
    api.DELETE('/agencies/{agency_id}/invitations/{invitation_id}', {
      params: { path: { agency_id: agencyId, invitation_id: invitationId } },
    }),
  );
}
