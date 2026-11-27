import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { useRef, useState, type FormEvent } from 'react';
import { FormattedMessage } from 'react-intl';

import { agenciesQuery, agencyQuery, createAgency } from '@/api/agencies';
import { describeError, type ErrorMessage } from '@/api/errors';
import { agencyChoice } from '@/app/agency';
import { useSignOut } from '@/app/useSignOut';
import { Field } from '@/components/Field';
import { ErrorNotice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { NAME_MAX, nameError } from '@/lib/validation';

/** A signed-in person who belongs to no agency creates their first one, and becomes its owner. */
export function WelcomePage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  usePageTitle('welcome.title');

  const [name, setName] = useState('');
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const leave = useSignOut(setProblem);

  const request = useMutation({
    mutationFn: () => createAgency(name.trim()),
    async onSuccess(agency) {
      agencyChoice.set(agency.id);
      queryClient.setQueryData(agencyQuery(agency.id).queryKey, agency);
      // The workspace opens only once the list of agencies holds the new one.
      await queryClient.fetchQuery({ ...agenciesQuery, staleTime: 0 });
      await navigate({ to: '/' });
    },
    onError(failure) {
      setProblem(describeError(failure));
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (request.isPending) return;
    const found = nameError(name);
    setError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, nameRef])) request.mutate();
  };

  return (
    <>
      <div className="l-stack l-stack--tight">
        <PageHeading>
          <FormattedMessage id="welcome.title" />
        </PageHeading>
        <p className="u-secondary">
          <FormattedMessage id="welcome.lead" />
        </p>
      </div>

      <ErrorNotice message={problem} />

      <form className="l-stack" noValidate onSubmit={onSubmit}>
        <Field
          id="welcome-name"
          ref={nameRef}
          label={<FormattedMessage id="welcome.name" />}
          autoComplete="organization"
          maxLength={NAME_MAX}
          required
          value={name}
          onChange={setName}
          error={error}
          hint={<FormattedMessage id="welcome.nameHint" />}
        />
        <SubmitButton busy={request.isPending}>
          <FormattedMessage id="welcome.submit" />
        </SubmitButton>
      </form>

      <p className="u-secondary">
        <FormattedMessage id="welcome.invited" />
      </p>
      <p className="l-cluster">
        <Link className="c-btn c-btn--ghost" to="/account">
          <FormattedMessage id="shell.nav.account" />
        </Link>
        <button
          type="button"
          className="c-btn c-btn--ghost"
          onClick={() => {
            if (!leave.isPending) leave.mutate(false);
          }}
        >
          <FormattedMessage id="shell.signOut" />
        </button>
      </p>
    </>
  );
}
