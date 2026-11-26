import type { Role } from '@/api/agencies';
import type { Member, MemberGrant } from '@/api/team';
import { isManager } from '@/app/agency';

/** A member can use the agency: their membership is active and their account is open. */
export const isActiveMember = (member: Member): boolean => member.status === 'active' && member.account === 'active';

/** The grants of a member to the clients that are active now, in the order of the given clients. */
export function activeGrants(member: Member, activeClientIds: readonly string[]): MemberGrant[] {
  const byClient = new Map(member.clients.map((grant) => [grant.client_id, grant]));
  return activeClientIds.flatMap((clientId) => {
    const grant = byClient.get(clientId);
    return grant ? [grant] : [];
  });
}

/** What a member may open, as the list of members shows it. */
export type ClientAccess =
  | { kind: 'all' }
  | { kind: 'none' }
  | { kind: 'some'; clients: number; financial: number; onlyClient: string | null };

export function clientAccess(member: Member, activeClientIds: readonly string[]): ClientAccess {
  if (isManager(member.role)) return { kind: 'all' };
  const grants = activeGrants(member, activeClientIds);
  if (grants.length === 0) return { kind: 'none' };
  return {
    kind: 'some',
    clients: grants.length,
    financial: grants.filter((grant) => grant.can_view_financials).length,
    onlyClient: grants.length === 1 ? (grants[0]?.client_id ?? null) : null,
  };
}

/**
 * Whether a person may change a member's access here. The API decides in any case: an admin
 * cannot change an owner, and nobody changes a closed account. A person does not change their own
 * access on this page, so that nobody locks themselves out by mistake.
 */
export function mayChange(actorRole: Role, actorUserId: string, member: Member): boolean {
  if (member.user_id === actorUserId || member.account === 'closed') return false;
  if (!isManager(actorRole)) return false;
  return actorRole === 'owner' || member.role !== 'owner';
}

/** The number of people who can open a client now: every active manager, and the active members it was granted to. */
export function peopleWithAccess(members: readonly Member[], clientId: string): number {
  return members.filter(
    (member) => isActiveMember(member) && (isManager(member.role) || member.clients.some((grant) => grant.client_id === clientId)),
  ).length;
}

/** The roles a person may give: only an owner makes another owner. */
export const assignableRoles = (actorRole: Role): Role[] =>
  actorRole === 'owner' ? ['owner', 'admin', 'analyst', 'client_viewer'] : ['admin', 'analyst', 'client_viewer'];

/** Roles that read only the clients they are granted, and need at least one. */
export const isRestricted = (role: Role): boolean => role === 'analyst' || role === 'client_viewer';
