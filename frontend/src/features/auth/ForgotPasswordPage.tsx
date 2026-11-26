import { useMutation } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { useRef, useState, type FormEvent } from 'react';
import { FormattedMessage } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { forgotPassword } from '@/api/session';
import { Field } from '@/components/Field';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { emailError } from '@/lib/validation';

export function ForgotPasswordPage() {
  usePageTitle('forgot.title');

  const [email, setEmail] = useState('');
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  const request = useMutation({
    mutationFn: () => forgotPassword(email.trim()),
    // The API never says whether an address has an account, and neither does this screen.
    onSuccess() {
      setSentTo(email.trim());
    },
    onError(failure) {
      setProblem(describeError(failure));
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (request.isPending) return;
    const found = emailError(email);
    setError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, emailRef])) request.mutate();
  };

  const back = (
    <p className="u-secondary">
      <Link to="/sign-in">
        <FormattedMessage id="common.backToSignIn" />
      </Link>
    </p>
  );

  if (sentTo !== null) {
    return (
      <>
        <PageHeading>
          <FormattedMessage id="forgot.sent.title" />
        </PageHeading>
        <Notice tone="success">
          <FormattedMessage id="forgot.sent.text" values={{ email: <strong className="u-ltr">{sentTo}</strong> }} />
        </Notice>
        {back}
      </>
    );
  }

  return (
    <>
      <div className="l-stack l-stack--tight">
        <PageHeading>
          <FormattedMessage id="forgot.title" />
        </PageHeading>
        <p className="u-secondary">
          <FormattedMessage id="forgot.lead" />
        </p>
      </div>

      <ErrorNotice message={problem} />

      <form className="l-stack" noValidate onSubmit={onSubmit}>
        <Field
          id="forgot-email"
          ref={emailRef}
          label={<FormattedMessage id="common.email" />}
          type="email"
          autoComplete="username"
          dir="ltr"
          required
          value={email}
          onChange={setEmail}
          error={error}
        />
        <SubmitButton busy={request.isPending}>
          <FormattedMessage id="forgot.submit" />
        </SubmitButton>
      </form>

      {back}
    </>
  );
}
