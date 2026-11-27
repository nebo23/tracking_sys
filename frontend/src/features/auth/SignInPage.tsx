import { useMutation, useQueryClient } from '@tanstack/react-query';
import { getRouteApi, Link, useRouter } from '@tanstack/react-router';
import { useRef, useState, type FormEvent } from 'react';
import { FormattedMessage } from 'react-intl';

import { currentAgreements, forgetAgreements, googleStartAddress, isAgreementRequired } from '@/api/agreements';
import { describeError, isApiError, type ErrorMessage } from '@/api/errors';
import { signIn } from '@/api/session';
import { apiOrigin, googleSignInEnabled } from '@/app/config';
import { beginSession } from '@/app/sessionLifecycle';
import { AgreementBox } from '@/components/AgreementBox';
import { Field, PasswordField } from '@/components/Field';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';
import { goTo } from '@/lib/browser';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { heldLinkToken } from '@/lib/linkToken';
import { safeNext } from '@/lib/safeNext';
import { emailError, PASSWORD_MAX, requiredError } from '@/lib/validation';

import { GoogleMark } from './GoogleMark';
import { pendingEmail } from './pendingEmail';

const route = getRouteApi('/entry/sign-in');

interface Errors {
  email?: MessageId | null;
  password?: MessageId | null;
  agreement?: MessageId | null;
}

const goodNews = new Set(['passwordChanged', 'reset', 'verified']);

export function SignInPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { next, notice } = route.useSearch();
  usePageTitle('signIn.title');

  const [email, setEmail] = useState(() => pendingEmail.get() ?? '');
  const [password, setPassword] = useState('');
  const [agreed, setAgreed] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const [unverified, setUnverified] = useState(false);
  // Google sign-in comes back with notice=termsChanged after the same refusal.
  const [termsChanged, setTermsChanged] = useState(notice === 'termsChanged');
  const shownNotice = notice === 'termsChanged' ? undefined : notice;
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const agreementRef = useRef<HTMLInputElement>(null);

  // The versions changed while the page was open (A03): forget them so that the next attempt
  // reads the new ones, untick the box and keep what was typed.
  const refuseOutdatedTerms = () => {
    forgetAgreements(queryClient);
    setAgreed(false);
    setTermsChanged(true);
    agreementRef.current?.focus();
  };

  const request = useMutation({
    mutationFn: async () => signIn(email.trim(), password, await currentAgreements(queryClient)),
    onSuccess(session) {
      pendingEmail.set(null);
      beginSession(queryClient, session);
      // An invitation opened before signing in is waiting to be accepted.
      const fallback = heldLinkToken('invitation') ? '/auth/accept-invitation' : '/';
      router.history.push(next ? safeNext(next) : fallback);
    },
    onError(error) {
      if (isAgreementRequired(error)) {
        refuseOutdatedTerms();
        return;
      }
      setUnverified(isApiError(error) && error.code === 'email_verification_required');
      setProblem(describeError(error));
    },
  });

  const agreementMissing = (): boolean => {
    if (agreed) return false;
    setErrors((current) => ({ ...current, agreement: 'agreement.required' }));
    agreementRef.current?.focus();
    return true;
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (request.isPending) return;
    const found: Errors = {
      email: emailError(email),
      password: requiredError(password),
      agreement: agreed ? null : 'agreement.required',
    };
    setErrors(found);
    setProblem(null);
    setUnverified(false);
    const stopped = focusFirstInvalid(
      [found.email, emailRef],
      [found.password, passwordRef],
      [found.agreement, agreementRef],
    );
    if (stopped) return;
    setTermsChanged(false);
    request.mutate();
  };

  const startGoogle = async () => {
    if (agreementMissing()) return;
    setProblem(null);
    try {
      // Google sign-in is a visit to the API, which sends the browser on to Google.
      goTo(googleStartAddress(apiOrigin, await currentAgreements(queryClient)));
    } catch (error) {
      setProblem(describeError(error));
    }
  };

  return (
    <>
      <div className="l-stack l-stack--tight">
        <PageHeading>
          <FormattedMessage id="signIn.title" />
        </PageHeading>
        <p className="u-secondary">
          <FormattedMessage id="signIn.lead" />
        </p>
      </div>

      {shownNotice && !problem ? (
        <Notice tone={goodNews.has(shownNotice) ? 'success' : 'info'}>
          <FormattedMessage id={`signIn.notice.${shownNotice}`} />
        </Notice>
      ) : null}
      <ErrorNotice
        message={problem}
        action={
          unverified ? (
            <Link to="/verify-email" onClick={() => pendingEmail.set(email.trim())}>
              <FormattedMessage id="signIn.verifyLink" />
            </Link>
          ) : undefined
        }
      />

      <form className="l-stack" noValidate onSubmit={onSubmit}>
        {termsChanged ? (
          <Notice tone="warning" title={<FormattedMessage id="agreement.changed.title" />}>
            <FormattedMessage id="agreement.changed.signIn" />
          </Notice>
        ) : null}
        {googleSignInEnabled ? (
          <>
            <button
              className="c-btn c-btn--secondary c-btn--lg c-btn--block"
              type="button"
              onClick={() => void startGoogle()}
            >
              <GoogleMark />
              <FormattedMessage id="signIn.google" />
            </button>
            <div className="c-divider">
              <FormattedMessage id="common.or" />
            </div>
          </>
        ) : null}
        <Field
          id="signin-email"
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
        <PasswordField
          id="signin-password"
          ref={passwordRef}
          label={<FormattedMessage id="common.password" />}
          autoComplete="current-password"
          maxLength={PASSWORD_MAX}
          required
          value={password}
          onChange={setPassword}
          error={errors.password}
          below={
            <Link className="c-field__link" to="/forgot-password">
              <FormattedMessage id="signIn.forgot" />
            </Link>
          }
        />
        <AgreementBox
          id="signin-terms"
          ref={agreementRef}
          checked={agreed}
          onChange={(checked) => {
            setAgreed(checked);
            if (checked) setErrors((current) => ({ ...current, agreement: null }));
          }}
          error={errors.agreement}
        />
        <SubmitButton busy={request.isPending}>
          <FormattedMessage id="signIn.submit" />
        </SubmitButton>
      </form>

      <p className="u-secondary">
        <FormattedMessage id="signIn.new" />{' '}
        <Link to="/register">
          <FormattedMessage id="signIn.create" />
        </Link>
      </p>
    </>
  );
}
