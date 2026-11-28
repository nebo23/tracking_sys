import { useMutation } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { useRef, useState, type FormEvent } from 'react';
import { FormattedMessage } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { resendVerification, verifyEmailCode } from '@/api/session';
import { Field, FieldError } from '@/components/Field';
import { ErrorNotice, Notice } from '@/components/Notice';
import { OtpInput, type OtpHandle } from '@/components/OtpInput';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';
import { cx } from '@/lib/cx';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { useSecondsUntil } from '@/lib/useSecondsUntil';
import { codeError, emailError } from '@/lib/validation';

import { pendingEmail } from './pendingEmail';

// The API sends nothing new within 60 seconds of the latest code.
const RESEND_WAIT_MS = 60_000;

interface Errors {
  email?: MessageId | null;
  code?: MessageId | null;
}

export function VerifyEmailPage() {
  const navigate = useNavigate();
  usePageTitle('verify.title');

  // Known when the person arrives from registration or sign-in; after a reload they type it again.
  const [known] = useState(() => pendingEmail.get());
  const [email, setEmail] = useState(known ?? '');
  const [code, setCode] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const [resent, setResent] = useState(false);
  const [resendAt, setResendAt] = useState(() => (known ? Date.now() + RESEND_WAIT_MS : 0));
  const wait = useSecondsUntil(resendAt);
  const emailRef = useRef<HTMLInputElement>(null);
  const codeRef = useRef<OtpHandle>(null);

  const confirm = useMutation({
    mutationFn: () => verifyEmailCode(email.trim(), code),
    onSuccess() {
      pendingEmail.set(email.trim());
      void navigate({ to: '/sign-in', search: { notice: 'verified' } });
    },
    onError(error) {
      setCode('');
      setResent(false);
      setProblem(describeError(error));
      codeRef.current?.focus(0);
    },
  });

  const resend = useMutation({
    mutationFn: () => resendVerification(email.trim()),
    // The same answer for every address: the API does not say whether one is waiting.
    onSuccess() {
      setProblem(null);
      setResent(true);
      setResendAt(Date.now() + RESEND_WAIT_MS);
    },
    onError(error) {
      setResent(false);
      setProblem(describeError(error));
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (confirm.isPending) return;
    const found: Errors = { email: emailError(email), code: codeError(code) };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.email, emailRef], [found.code, codeRef])) confirm.mutate();
  };

  const onResend = () => {
    if (wait > 0 || resend.isPending) return;
    const found = emailError(email);
    setErrors({ email: found });
    if (!focusFirstInvalid([found, emailRef])) resend.mutate();
  };

  return (
    <>
      <div className="l-stack l-stack--tight">
        <PageHeading>
          <FormattedMessage id="verify.title" />
        </PageHeading>
        <p className="u-secondary">
          {known ? (
            <FormattedMessage id="verify.lead" values={{ email: <strong className="u-ltr">{known}</strong> }} />
          ) : (
            <FormattedMessage id="verify.leadNoEmail" />
          )}
        </p>
      </div>

      <ErrorNotice message={problem} />
      {resent && !problem ? (
        <Notice tone="success">
          <FormattedMessage id="verify.resent" />
        </Notice>
      ) : null}

      <form className="l-stack" noValidate onSubmit={onSubmit}>
        {known ? null : (
          <Field
            id="verify-email"
            ref={emailRef}
            label={<FormattedMessage id="common.email" />}
            type="email"
            autoComplete="username"
            dir="ltr"
            required
            value={email}
            onChange={setEmail}
            error={errors.email}
          />
        )}
        <div className="c-field">
          <span className="c-field__label" id="verify-code-label">
            <FormattedMessage id="verify.code" />
          </span>
          <OtpInput
            ref={codeRef}
            value={code}
            onChange={setCode}
            labelledBy="verify-code-label"
            describedBy={errors.code ? 'verify-code-error' : undefined}
            invalid={Boolean(errors.code)}
          />
          <FieldError id="verify-code-error" error={errors.code} />
        </div>
        <SubmitButton busy={confirm.isPending}>
          <FormattedMessage id="verify.submit" />
        </SubmitButton>
      </form>

      <div className="l-stack l-stack--tight">
        <button
          type="button"
          className={cx('c-btn c-btn--secondary c-btn--block', wait > 0 && 'is-disabled', resend.isPending && 'is-loading')}
          aria-disabled={wait > 0 || undefined}
          aria-describedby={wait > 0 ? 'verify-wait' : undefined}
          onClick={onResend}
        >
          {resend.isPending ? <span className="c-spinner" aria-hidden="true" /> : null}
          <FormattedMessage id="verify.resend" />
        </button>
        {wait > 0 ? (
          <p className="c-field__hint" id="verify-wait">
            <FormattedMessage id="verify.resendWait" values={{ seconds: wait }} />
          </p>
        ) : null}
      </div>

      <p className="u-secondary">
        <Link to="/sign-in">
          <FormattedMessage id="common.backToSignIn" />
        </Link>
      </p>
    </>
  );
}
