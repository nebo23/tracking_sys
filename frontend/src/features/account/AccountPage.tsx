import { useMutation, useSuspenseQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { useRef, useState, type FormEvent, type ReactNode } from 'react';
import { FormattedDate, FormattedMessage } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { changePassword, linkGoogle, sessionQuery } from '@/api/session';
import { googleSignInEnabled } from '@/app/config';
import { useEndSession } from '@/app/sessionLifecycle';
import { useSignOut } from '@/app/useSignOut';
import { PasswordField } from '@/components/Field';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { LanguageSwitch, ThemeSwitch } from '@/components/PreferenceSwitches';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';
import { goTo, isSecureAddress } from '@/lib/browser';
import { cx } from '@/lib/cx';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';
import { newPasswordError, PASSWORD_MAX, requiredError } from '@/lib/validation';

import { CloseAccount } from './CloseAccount';

const route = getRouteApi('/workspace/account');

function Card({ id, title, lead, children }: { id: string; title: MessageId; lead?: MessageId; children: ReactNode }) {
  return (
    <section className="c-card" aria-labelledby={id}>
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title" id={id}>
            <FormattedMessage id={title} />
          </h2>
          {lead ? (
            <p className="c-card__subtitle">
              <FormattedMessage id={lead} />
            </p>
          ) : null}
        </div>
      </div>
      <div className="c-card__body">{children}</div>
    </section>
  );
}

function PasswordCard() {
  const end = useEndSession();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [errors, setErrors] = useState<{ current?: MessageId | null; next?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const currentRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);

  const request = useMutation({
    mutationFn: () => changePassword(current, next),
    // The API ends every session of the account, this one included.
    onSuccess: () => end('passwordChanged'),
    onError(error) {
      setProblem(describeError(error, { invalid_credentials: 'account.password.error.current' }));
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (request.isPending) return;
    const found = { current: requiredError(current), next: newPasswordError(next) };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.current, currentRef], [found.next, nextRef])) request.mutate();
  };

  return (
    <Card id="account-password" title="account.password.title" lead="account.password.lead">
      <form className="a-form" noValidate onSubmit={onSubmit}>
        <ErrorNotice message={problem} />
        <PasswordField
          id="account-current-password"
          ref={currentRef}
          size="md"
          label={<FormattedMessage id="account.password.current" />}
          autoComplete="current-password"
          maxLength={PASSWORD_MAX}
          required
          value={current}
          onChange={setCurrent}
          error={errors.current}
        />
        <PasswordField
          id="account-new-password"
          ref={nextRef}
          size="md"
          label={<FormattedMessage id="account.password.new" />}
          autoComplete="new-password"
          maxLength={PASSWORD_MAX}
          required
          value={next}
          onChange={setNext}
          error={errors.next}
          hint={<FormattedMessage id="register.passwordHint" />}
        />
        <div>
          <SubmitButton size="md" block={false} busy={request.isPending}>
            <FormattedMessage id="account.password.submit" />
          </SubmitButton>
        </div>
      </form>
    </Card>
  );
}

function SessionsCard() {
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const leave = useSignOut(setProblem);
  const start = (everywhere: boolean) => {
    if (leave.isPending) return;
    setProblem(null);
    leave.mutate(everywhere);
  };
  return (
    <Card id="account-sessions" title="account.sessions.title" lead="account.sessions.lead">
      <div className="l-stack">
        <ErrorNotice message={problem} />
        <div className="l-cluster">
          <button type="button" className="c-btn c-btn--secondary" onClick={() => start(false)}>
            <FormattedMessage id="shell.signOut" />
          </button>
          <button type="button" className="c-btn c-btn--secondary" onClick={() => start(true)}>
            <FormattedMessage id="account.sessions.all" />
          </button>
        </div>
      </div>
    </Card>
  );
}

function GoogleCard() {
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({
    mutationFn: linkGoogle,
    onSuccess({ authorization_url: address }) {
      // The API answers with Google's own address. Anything that is not an https address is refused.
      if (isSecureAddress(address)) goTo(address);
      else setProblem({ id: 'google.error.other' });
    },
    onError(error) {
      setProblem(describeError(error, { not_found: 'google.error.other' }));
    },
  });
  return (
    <Card id="account-google" title="account.google.title" lead="account.google.lead">
      <div className="l-stack">
        <ErrorNotice message={problem} />
        <div>
          <button
            type="button"
            className={cx('c-btn c-btn--secondary', request.isPending && 'is-loading')}
            aria-busy={request.isPending || undefined}
            onClick={() => {
              if (request.isPending) return;
              setProblem(null);
              request.mutate();
            }}
          >
            {request.isPending ? <span className="c-spinner" aria-hidden="true" /> : null}
            <FormattedMessage id="account.google.link" />
          </button>
        </div>
      </div>
    </Card>
  );
}

export function AccountPage() {
  usePageTitle('account.title');
  const { notice } = route.useSearch();
  const { data: session } = useSuspenseQuery(sessionQuery);
  if (!session) return null;
  const { user } = session;

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="account.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="account.lead" />
          </p>
        </div>
      </div>

      {notice === 'googleLinked' ? (
        <Notice tone="success">
          <FormattedMessage id="account.google.linked" />
        </Notice>
      ) : null}

      <div className="l-stack a-narrow">
        <Card id="account-profile" title="account.profile.title">
          <dl className="c-dl">
            <dt>
              <FormattedMessage id="account.profile.name" />
            </dt>
            <dd className="u-strong">{user.display_name}</dd>
            <dt>
              <FormattedMessage id="account.profile.email" />
            </dt>
            <dd>
              <span className="u-ltr">{user.email_normalized}</span>
            </dd>
            <dt>
              <FormattedMessage id="account.profile.verified" />
            </dt>
            <dd>
              <FormattedDate value={user.email_verified_at} dateStyle="long" />
            </dd>
          </dl>
        </Card>

        <Card id="account-preferences" title="account.preferences.title">
          <dl className="c-dl a-dl--controls">
            <dt>
              <FormattedMessage id="language.label" />
            </dt>
            <dd>
              <LanguageSwitch />
            </dd>
            <dt>
              <FormattedMessage id="theme.label" />
            </dt>
            <dd>
              <ThemeSwitch />
            </dd>
          </dl>
        </Card>

        <PasswordCard />
        <SessionsCard />
        {googleSignInEnabled ? <GoogleCard /> : null}

        <Card id="account-close" title="account.close.title" lead="account.close.lead">
          <div>
            <CloseAccount />
          </div>
        </Card>
      </div>
    </>
  );
}
