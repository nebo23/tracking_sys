import { getRouteApi, Link, useNavigate } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { FormattedMessage } from 'react-intl';

import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';

import { pendingConnection, type PendingConnection } from './pendingConnection';
import { returnErrorMessage } from './returnErrors';

const route = getRouteApi('/workspace/connections/complete');

/**
 * Where the API sends the browser after a provider. It leads back to the connections of the
 * client the person was connecting, with the outcome. Opened without such a start, it says what
 * happened and offers the list of clients.
 */
export function ConnectionCompletePage() {
  usePageTitle('connections.complete.title');
  const navigate = useNavigate();
  const { result, connection_id: connection, error } = route.useSearch();
  // Read once, when the page opens. The record serves this one return.
  const [pending] = useState<PendingConnection | null>(() => pendingConnection.get());

  useEffect(() => {
    if (!pending) return;
    pendingConnection.clear();
    void navigate({
      to: '/agencies/$agencyId/clients/$clientId/connections',
      params: pending,
      search: error ? { failed: error } : { outcome: result, connection },
      replace: true,
    });
  }, [pending, navigate, result, connection, error]);

  if (pending) return null;

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="connections.complete.title" />
          </PageHeading>
        </div>
      </div>
      <div className="l-stack a-narrow">
        {error ? <ErrorNotice message={{ id: returnErrorMessage[error] }} /> : null}
        {!error && result ? (
          <Notice tone="success">
            <FormattedMessage id={result === 'connected' ? 'connections.complete.connected' : 'connections.complete.reconnected'} />
          </Notice>
        ) : null}
        {!error && !result ? (
          <Notice>
            <FormattedMessage id="connections.complete.nothing" />
          </Notice>
        ) : null}
        <p>
          <Link className="c-btn c-btn--primary" to="/">
            <FormattedMessage id="connections.complete.back" />
          </Link>
        </p>
      </div>
    </>
  );
}
