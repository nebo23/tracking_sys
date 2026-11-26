import { useMutation } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { issueKey, type IssuedServiceKey } from '@/api/keys';
import { SelectField, type Option } from '@/components/Choice';
import { ClientGrantsField, toClientGrants, type Grants } from '@/components/ClientGrantsField';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice } from '@/components/Notice';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { KEY_NAME_MAX, requiredError } from '@/lib/validation';

type Kind = 'read' | 'ingest';
type Lifetime = '30' | '60' | '90';

interface IssueKeyDialogProps {
  agencyId: string;
  onIssued: (issued: IssuedServiceKey) => void;
  onClose: () => void;
}

/** Names a new key, says what it is for and which clients it reaches, and for how long. */
export function IssueKeyDialog({ agencyId, onIssued, onClose }: IssueKeyDialogProps) {
  const intl = useIntl();
  const [name, setName] = useState('');
  const [kind, setKind] = useState<Kind>('read');
  const [lifetime, setLifetime] = useState<Lifetime>('90');
  const [grants, setGrants] = useState<Grants>({});
  const [errors, setErrors] = useState<{ name?: MessageId | null; clients?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const clientsRef = useRef<HTMLInputElement>(null);

  const kinds: Array<Option<Kind>> = (['read', 'ingest'] as const).map((value) => ({
    value,
    label: intl.formatMessage({ id: `keys.kind.${value}` }),
    hint: intl.formatMessage({ id: `keys.kind.${value}.hint` }),
  }));
  const lifetimes: Array<Option<Lifetime>> = (['30', '60', '90'] as const).map((value) => ({
    value,
    label: intl.formatMessage({ id: 'keys.lifetime.days' }, { days: Number(value) }),
  }));

  const request = useMutation({
    mutationFn: () =>
      issueKey(agencyId, {
        name: name.trim(),
        kind,
        expires_in_days: Number(lifetime),
        // A key that only sends events never carries financial access.
        clients: toClientGrants(grants).map((grant) => (kind === 'ingest' ? { ...grant, can_view_financials: false } : grant)),
      }),
    // The answer holds the key. It is handed on and not kept by the request once the dialog closes.
    gcTime: 0,
    onSuccess: onIssued,
    onError: (failure) => setProblem(describeError(failure)),
  });

  const submit = () => {
    const found = {
      name: requiredError(name.trim()),
      clients: Object.keys(grants).length === 0 ? ('keys.issue.error.clients' as const) : null,
    };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.name, nameRef], [found.clients, clientsRef])) request.mutate();
  };

  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="keys.issue.title" />}
      submitLabel={<FormattedMessage id="keys.issue.submit" />}
      busy={request.isPending}
      onSubmit={submit}
      wide
    >
      <ErrorNotice message={problem} />
      <Field
        id="key-name"
        ref={nameRef}
        size="md"
        label={<FormattedMessage id="keys.name" />}
        hint={<FormattedMessage id="keys.nameHint" />}
        autoComplete="off"
        maxLength={KEY_NAME_MAX}
        required
        // The dialog was opened to type this name.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        value={name}
        onChange={setName}
        error={errors.name}
      />
      <SelectField
        label={<FormattedMessage id="keys.kind" />}
        value={kind}
        onChange={setKind}
        options={kinds}
        hint={<FormattedMessage id={`keys.kind.${kind}.hint`} />}
      />
      <ClientGrantsField
        id="key-clients"
        agencyId={agencyId}
        legend={<FormattedMessage id="keys.clients" />}
        value={grants}
        onChange={(next) => {
          setGrants(next);
          setErrors((current) => ({ ...current, clients: null }));
        }}
        financials={kind === 'read'}
        error={errors.clients}
        firstRef={clientsRef}
      />
      <SelectField
        label={<FormattedMessage id="keys.lifetime" />}
        value={lifetime}
        onChange={setLifetime}
        options={lifetimes}
        hint={<FormattedMessage id="keys.lifetimeHint" />}
      />
    </FormDialog>
  );
}
