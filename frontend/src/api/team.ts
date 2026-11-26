import { queryOptions } from '@tanstack/react-query';

import { tenantKey } from './agencies';
import { api, call } from './client';
import { PAGE_SIZE, readAll } from './pages';
import type { components } from './schema';

export type Invitation = components['schemas']['InvitationResponse'];
export type InvitationInput = components['schemas']['InvitationInput'];
export type ClientGrant = components['schemas']['ClientGrantInput'];
export type Member = components['schemas']['MemberDetail'];
export type MemberGrant = components['schemas']['MemberClientGrant'];
export type Role = components['schemas']['Role'];

export const invitationsKey = (agencyId: string) => tenantKey(agencyId, 'invitations');
export const membersKey = (agencyId: string) => tenantKey(agencyId, 'members');

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

/**
 * Every member of the agency with their name, email, account state and client grants. Readable
 * by its owners and admins (018-B plan, B1; D-094). A closed account comes without a name.
 */
export const membersQuery = (agencyId: string) =>
  queryOptions({
    queryKey: membersKey(agencyId),
    queryFn: () =>
      readAll((offset) =>
        call(api.GET('/agencies/{agency_id}/members', { params: { path: { agency_id: agencyId }, query: { limit: PAGE_SIZE, offset } } })),
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

/** Changes a member's role, or pauses and restores their access. */
export function updateMember(agencyId: string, membershipId: string, change: { role?: Role; status?: 'active' | 'disabled' }) {
  return call(
    api.PATCH('/agencies/{agency_id}/members/{membership_id}', {
      params: { path: { agency_id: agencyId, membership_id: membershipId } },
      body: change,
    }),
  );
}

/**
 * Lets a member open a client, with or without its financial data. The identity flag is left
 * out, so the API keeps whatever was granted before (specification 006, D8).
 */
export function grantClient(agencyId: string, membershipId: string, clientId: string, financials: boolean) {
  return call(
    api.PUT('/agencies/{agency_id}/members/{membership_id}/clients/{client_id}', {
      params: { path: { agency_id: agencyId, membership_id: membershipId, client_id: clientId } },
      body: { can_view_financials: financials },
    }),
  );
}

export function revokeClient(agencyId: string, membershipId: string, clientId: string) {
  return call(
    api.DELETE('/agencies/{agency_id}/members/{membership_id}/clients/{client_id}', {
      params: { path: { agency_id: agencyId, membership_id: membershipId, client_id: clientId } },
    }),
  );
}
