import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { useState } from 'react';
import { FormattedMessage } from 'react-intl';

import { agenciesQuery } from '@/api/agencies';
import { describeError, isApiError, type ErrorMessage } from '@/api/errors';
import { acceptInvitation, sessionQuery } from '@/api/session';
import { agencyChoice } from '@/app/agency';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { cx } from '@/lib/cx';
import { releaseLinkToken, useLinkToken } from '@/lib/linkToken';

export function AcceptInvitationPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  usePageTitle('invitation.title');

  const { data: session } = useSuspenseQuery(sessionQuery);
  // The token left the address bar before this screen was drawn; it stays in memory while the person signs in.
  const token = useLinkToken('invitation');
  const [problem, setProblem] = useState<ErrorMessage | null>(null);

  const request = useMutation({
    mutationFn: (value: string) => acceptInvitation(value),
    async onSuccess(membership) {
      releaseLinkToken('invitation');
      agencyChoice.set(membership.agency_id);
      await queryClient.fetchQuery({ ...agenciesQuery, staleTime: 0 });
      await navigate({ to: '/' });
    },
    onError(error) {
      if (isApiError(error) && error.code === 'invalid_or_expired_token') {
        releaseLinkToken('invitation');
      }
      setProblem(
        describeError(error, {
          invalid_or_expired_token: 'invitation.error.token',
          email_verification_required: 'invitation.error.unverified',
        }),
      );
    },
  });

  if (token === null) {
    return (
      <>
        <PageHeading>
          <FormattedMessage id="invitation.missing.title" />
        </PageHeading>
        <ErrorNotice message={problem} />
        <Notice tone="warning">
          <FormattedMessage id="invitation.missing.text" />
        </Notice>
        <p className="u-secondary">
          {session ? (
            <Link to="/">
              <FormattedMessage id="notFound.home" />
            </Link>
          ) : (
            <Link to="/sign-in">
              <FormattedMessage id="common.backToSignIn" />
            </Link>
          )}
        </p>
      </>
    );
  }

  return (
    <>
      <div className="l-stack l-stack--tight">
        <PageHeading>
          <FormattedMessage id="invitation.title" />
        </PageHeading>
        <p className="u-secondary">
          <FormattedMessage id="invitation.lead" />
        </p>
      </div>

      <ErrorNotice message={problem} />

      {session ? (
        <button
          type="button"
          className={cx('c-btn c-btn--primary c-btn--lg c-btn--block', request.isPending && 'is-loading')}
          aria-busy={request.isPending || undefined}
          onClick={() => {
            if (request.isPending) return;
            setProblem(null);
            request.mutate(token);
          }}
        >
          {request.isPending ? <span className="c-spinner" aria-hidden="true" /> : null}
          <FormattedMessage id="invitation.accept" />
        </button>
      ) : (
        <>
          <p>
            <FormattedMessage id="invitation.signInFirst" />
          </p>
          <Link
            className="c-btn c-btn--primary c-btn--lg c-btn--block"
            to="/sign-in"
            search={{ next: '/auth/accept-invitation' }}
          >
            <FormattedMessage id="invitation.signIn" />
          </Link>
          <p className="u-secondary">
            <FormattedMessage id="signIn.new" />{' '}
            <Link to="/register">
              <FormattedMessage id="invitation.create" />
            </Link>
          </p>
        </>
      )}
    </>
  );
}
