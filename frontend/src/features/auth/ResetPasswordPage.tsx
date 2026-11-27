import { useMutation } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { useRef, useState, type FormEvent } from 'react';
import { FormattedMessage } from 'react-intl';

import { describeError, isApiError, type ErrorMessage } from '@/api/errors';
import { resetPassword } from '@/api/session';
import { useEndSession } from '@/app/sessionLifecycle';
import { PasswordField } from '@/components/Field';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { releaseLinkToken, useLinkToken } from '@/lib/linkToken';
import { newPasswordError, PASSWORD_MAX } from '@/lib/validation';

export function ResetPasswordPage() {
  const end = useEndSession();
  usePageTitle('reset.title');

  // The token left the address bar before this screen was drawn; it is held in memory.
  const token = useLinkToken('reset');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const request = useMutation({
    mutationFn: (value: string) => resetPassword(value, password),
    onSuccess() {
      releaseLinkToken('reset');
      // A new password ends every session of the account, this browser's included.
      return end('reset');
    },
    onError(failure) {
      if (isApiError(failure) && failure.code === 'invalid_or_expired_token') {
        releaseLinkToken('reset');
      }
      setProblem(describeError(failure));
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (request.isPending || token === null) return;
    const found = newPasswordError(password);
    setError(found);
    setProblem(null);
    if (!focusFirstInvalid([found, passwordRef])) request.mutate(token);
  };

  if (token === null) {
    return (
      <>
        <PageHeading>
          <FormattedMessage id="reset.missing.title" />
        </PageHeading>
        {problem ? (
          <ErrorNotice message={problem} />
        ) : (
          <Notice tone="warning">
            <FormattedMessage id="reset.missing.text" />
          </Notice>
        )}
        <p>
          <Link className="c-btn c-btn--primary c-btn--lg c-btn--block" to="/forgot-password">
            <FormattedMessage id="reset.request" />
          </Link>
        </p>
        <p className="u-secondary">
          <Link to="/sign-in">
            <FormattedMessage id="common.backToSignIn" />
          </Link>
        </p>
      </>
    );
  }

  return (
    <>
      <div className="l-stack l-stack--tight">
        <PageHeading>
          <FormattedMessage id="reset.title" />
        </PageHeading>
        <p className="u-secondary">
          <FormattedMessage id="reset.lead" />
        </p>
      </div>

      <ErrorNotice message={problem} />

      <form className="l-stack" noValidate onSubmit={onSubmit}>
        <PasswordField
          id="reset-password"
          ref={passwordRef}
          label={<FormattedMessage id="reset.newPassword" />}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX}
          required
          value={password}
          onChange={setPassword}
          error={error}
          hint={<FormattedMessage id="register.passwordHint" />}
        />
        <SubmitButton busy={request.isPending}>
          <FormattedMessage id="reset.submit" />
        </SubmitButton>
      </form>
    </>
  );
}
