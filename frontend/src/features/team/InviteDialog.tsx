import { useMutation } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import type { Role } from '@/api/agencies';
import { describeError, type ErrorMessage } from '@/api/errors';
import { invite, type Invitation } from '@/api/team';
import { SelectField, type Option } from '@/components/Choice';
import { ClientGrantsField, toClientGrants, type Grants } from '@/components/ClientGrantsField';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice } from '@/components/Notice';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { EMAIL_MAX, emailError } from '@/lib/validation';

interface InviteDialogProps {
  agencyId: string;
  /** The role of the person who invites. Only an owner invites an owner. */
  role: Role;
  onInvited: (invitation: Invitation) => void;
  onClose: () => void;
}

const restricted = (role: Role) => role === 'analyst' || role === 'client_viewer';

/** Invites a person by email, with a role and, for the roles that need them, the clients they may open. */
export function InviteDialog({ agencyId, role: actorRole, onInvited, onClose }: InviteDialogProps) {
  const intl = useIntl();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('analyst');
  const [grants, setGrants] = useState<Grants>({});
  const [errors, setErrors] = useState<{ email?: MessageId | null; clients?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const clientsRef = useRef<HTMLInputElement>(null);

  const roles: Role[] = actorRole === 'owner' ? ['owner', 'admin', 'analyst', 'client_viewer'] : ['admin', 'analyst', 'client_viewer'];
  const options: Array<Option<Role>> = roles.map((value) => ({
    value,
    label: intl.formatMessage({ id: `role.${value}` }),
    hint: intl.formatMessage({ id: `team.roles.${value}` }),
  }));

  const request = useMutation({
    mutationFn: () => invite(agencyId, { email: email.trim(), role, clients: restricted(role) ? toClientGrants(grants) : [] }),
    onSuccess: onInvited,
    onError: (failure) => setProblem(describeError(failure, { state_conflict: 'team.invite.error.exists', validation_failed: 'field.error.email' })),
  });

  const submit = () => {
    const found = {
      email: emailError(email),
      clients: restricted(role) && Object.keys(grants).length === 0 ? ('team.invite.error.clients' as const) : null,
    };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.email, emailRef], [found.clients, clientsRef])) request.mutate();
  };

  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="team.invite.title" />}
      submitLabel={<FormattedMessage id="team.invite.submit" />}
      busy={request.isPending}
      onSubmit={submit}
      wide
    >
      <ErrorNotice message={problem} />
      <Field
        id="invite-email"
        ref={emailRef}
        size="md"
        type="email"
        label={<FormattedMessage id="common.email" />}
        hint={<FormattedMessage id="team.invite.emailHint" />}
        autoComplete="off"
        dir="ltr"
        maxLength={EMAIL_MAX}
        required
        // The dialog was opened to type this address.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        value={email}
        onChange={setEmail}
        error={errors.email}
      />
      <SelectField
        label={<FormattedMessage id="team.role" />}
        value={role}
        onChange={(next) => {
          setRole(next);
          setErrors((current) => ({ ...current, clients: null }));
        }}
        options={options}
        hint={<FormattedMessage id={`team.roles.${role}`} />}
      />
      {restricted(role) ? (
        <ClientGrantsField
          id="invite-clients"
          agencyId={agencyId}
          legend={<FormattedMessage id="team.invite.clients" />}
          hint={<FormattedMessage id="team.invite.clientsHint" />}
          value={grants}
          onChange={(next) => {
            setGrants(next);
            setErrors((current) => ({ ...current, clients: null }));
          }}
          error={errors.clients}
          firstRef={clientsRef}
        />
      ) : null}
    </FormDialog>
  );
}
