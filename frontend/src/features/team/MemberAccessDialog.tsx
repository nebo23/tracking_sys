import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import type { Role } from '@/api/agencies';
import { describeError, type ErrorMessage } from '@/api/errors';
import { grantClient, membersKey, revokeClient, updateMember, type Member } from '@/api/team';
import { SelectField, type Option } from '@/components/Choice';
import { ClientGrantsField, type Grants } from '@/components/ClientGrantsField';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice, Notice } from '@/components/Notice';
import type { MessageId } from '@/i18n';

import { activeGrants, assignableRoles, isRestricted } from './members';

interface MemberAccessDialogProps {
  agencyId: string;
  /** The role of the person who changes the access. Only an owner makes another owner. */
  actorRole: Role;
  member: Member;
  name: string;
  activeClientIds: readonly string[];
  onSaved: () => void;
  onClose: () => void;
}

const toGrants = (member: Member, activeClientIds: readonly string[]): Grants =>
  Object.fromEntries(activeGrants(member, activeClientIds).map((grant) => [grant.client_id, { financials: grant.can_view_financials }]));

/**
 * Changes what a member may do: their role and, for a role that reads only granted clients, the
 * clients and their financial data. Grants to archived clients are left as they are.
 */
export function MemberAccessDialog({ agencyId, actorRole, member, name, activeClientIds, onSaved, onClose }: MemberAccessDialogProps) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [role, setRole] = useState<Role>(member.role);
  const [grants, setGrants] = useState<Grants>(() => toGrants(member, activeClientIds));
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const clientsRef = useRef<HTMLInputElement>(null);

  const roles = assignableRoles(actorRole);
  const options: Array<Option<Role>> = roles.map((value) => ({
    value,
    label: intl.formatMessage({ id: `role.${value}` }),
    hint: intl.formatMessage({ id: `team.roles.${value}` }),
  }));

  const request = useMutation({
    async mutationFn() {
      // A role that reads only granted clients gets its clients first, so it is never left
      // without any between two requests. A manager reads every client: grants are not touched.
      if (isRestricted(role)) {
        const before = toGrants(member, activeClientIds);
        for (const [clientId, { financials }] of Object.entries(grants)) {
          if (before[clientId]?.financials !== financials) await grantClient(agencyId, member.id, clientId, financials);
        }
        for (const clientId of Object.keys(before)) {
          if (!(clientId in grants)) await revokeClient(agencyId, member.id, clientId);
        }
      }
      if (role !== member.role) await updateMember(agencyId, member.id, { role });
    },
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: membersKey(agencyId) });
      onSaved();
    },
    async onError(failure) {
      setProblem(describeError(failure, { state_conflict: 'team.member.error.lastOwner' }));
      // Some of the changes may have been made before the failure: show what the API now holds.
      await queryClient.invalidateQueries({ queryKey: membersKey(agencyId) });
    },
  });

  const submit = () => {
    const missing = isRestricted(role) && Object.keys(grants).length === 0 ? ('team.invite.error.clients' as const) : null;
    setError(missing);
    setProblem(null);
    if (missing) clientsRef.current?.focus();
    else request.mutate();
  };

  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="team.member.access.title" values={{ name }} />}
      submitLabel={<FormattedMessage id="common.save" />}
      busy={request.isPending}
      onSubmit={submit}
      wide
    >
      <ErrorNotice message={problem} />
      <SelectField
        label={<FormattedMessage id="team.role" />}
        value={role}
        onChange={(next) => {
          setRole(next);
          setError(null);
        }}
        options={options}
        hint={<FormattedMessage id={`team.roles.${role}`} />}
      />
      {isRestricted(role) ? (
        <ClientGrantsField
          id="member-clients"
          agencyId={agencyId}
          legend={<FormattedMessage id="team.member.access.clients" />}
          hint={<FormattedMessage id="team.invite.clientsHint" />}
          value={grants}
          onChange={(next) => {
            setGrants(next);
            setError(null);
          }}
          error={error}
          firstRef={clientsRef}
        />
      ) : (
        <Notice quiet>
          <FormattedMessage id="team.member.access.managers" />
        </Notice>
      )}
    </FormDialog>
  );
}
