import { useSuspenseQuery } from '@tanstack/react-query';
import { getRouteApi, Link } from '@tanstack/react-router';
import { FormattedMessage } from 'react-intl';

import { sessionQuery } from '@/api/session';
import { Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';

const route = getRouteApi('/entry/auth/google/complete');

// The codes that have a sentence of their own. Any other code gets the general one.
const explained = [
  'google_link_required',
  'google_email_not_verified',
  'google_sign_in_cancelled',
  'google_identity_in_use',
  'google_already_linked',
] as const;

/**
 * Where the API sends the browser after Google. A successful sign-in or link never shows this
 * screen: the route moves on before it is drawn. What remains is the explanation of a failure.
 */
export function GoogleCompletePage() {
  const { error } = route.useSearch();
  const { data: session } = useSuspenseQuery(sessionQuery);
  usePageTitle('google.failed.title');
  const code = explained.find((known) => known === error);

  return (
    <>
      <PageHeading>
        <FormattedMessage id="google.failed.title" />
      </PageHeading>
      <Notice tone="danger">
        <FormattedMessage id={code ? `google.error.${code}` : 'google.error.other'} />
      </Notice>
      <p className="u-secondary">
        {session ? (
          <Link to="/account">
            <FormattedMessage id="google.backToAccount" />
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
