import { useQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { connectionsQuery, type Connection } from '@/api/connections';
import { describeError } from '@/api/errors';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { EmptyState } from '@/components/EmptyState';
import { Icon } from '@/components/Icon';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { Skeleton } from '@/components/Skeleton';
import { Day } from '@/components/Time';

import { ConnectDialog } from './ConnectDialog';
import { ConnectionCard } from './ConnectionCard';
import { connectionErrors } from './errors';
import { ProviderMark, useProviderName } from './ProviderMark';
import { returnErrorMessage } from './returnErrors';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/connections');

/** How often the list asks again while an account is being removed. */
const WATCH_MS = 5000;

/** What became of an account that was disconnected: whether access was taken back and the data removed. */
function Removal({ connection }: { connection: Connection }) {
  const outcome = connection.disconnect;
  if (!outcome) return null;
  if (outcome.revocation === 'failed') {
    return (
      <Badge tone="warning" icon="triangle-alert">
        <FormattedMessage id="connections.past.revocation.failed" />
      </Badge>
    );
  }
  return (
    <Badge tone="success" icon="circle-check">
      <FormattedMessage id="connections.past.removed" />
    </Badge>
  );
}

/** The accounts a client has connected. Owners and admins connect, synchronize, reconnect and disconnect. */
export function ConnectionsPage() {
  usePageTitle('connections.title');
  const intl = useIntl();
  const providerName = useProviderName();
  const { agencyId, clientId, client, manager } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  // What the return from a provider reported. It is said once: the address is cleared at once,
  // so a reload or a link to this page does not repeat it.
  const [{ outcome, failed }] = useState(() => ({ outcome: search.outcome, failed: search.failed }));
  const [connecting, setConnecting] = useState(false);
  const carriesOutcome = Boolean(search.outcome ?? search.failed ?? search.connection);
  useEffect(() => {
    if (carriesOutcome) void navigate({ search: {}, replace: true });
  }, [carriesOutcome, navigate]);

  const connections = useQuery({
    ...connectionsQuery(agencyId, clientId),
    refetchInterval: (query) => (query.state.data?.some((connection) => connection.status === 'disconnecting') ? WATCH_MS : false),
  });

  const live = (connections.data ?? []).filter((connection) => connection.status !== 'disconnected');
  const past = (connections.data ?? []).filter((connection) => connection.status === 'disconnected');

  const connectButton = manager ? (
    <button type="button" className="c-btn c-btn--primary" onClick={() => setConnecting(true)}>
      <Icon name="plus" size="sm" />
      <FormattedMessage id="connections.connect" />
    </button>
  ) : null;

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="connections.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="connections.lead" values={{ client: client.name }} />
          </p>
        </div>
        {live.length > 0 ? <div className="l-cluster">{connectButton}</div> : null}
      </div>

      {failed ? <ErrorNotice message={{ id: returnErrorMessage[failed] }} /> : null}
      {!failed && outcome ? (
        <Notice tone="success" title={<FormattedMessage id={`connections.complete.${outcome}`} />}>
          <FormattedMessage id="connections.complete.next" />
        </Notice>
      ) : null}

      {connections.isPending ? (
        <div className="c-card">
          <div className="c-card__body">
            <Skeleton lines={4} />
          </div>
        </div>
      ) : null}

      {connections.isError ? (
        <ErrorNotice
          message={describeError(connections.error, connectionErrors)}
          action={
            <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void connections.refetch()}>
              <FormattedMessage id="common.retry" />
            </button>
          }
        />
      ) : null}

      {connections.isSuccess && live.length === 0 ? (
        <div className="c-card">
          <EmptyState icon="plug" title={<FormattedMessage id="connections.empty.title" />} action={connectButton}>
            <FormattedMessage id={manager ? 'connections.empty.manager' : 'connections.empty.member'} values={{ client: client.name }} />
          </EmptyState>
        </div>
      ) : null}

      {live.length > 0 ? (
        <section className="l-grid l-grid--2" aria-label={intl.formatMessage({ id: 'connections.live.label' })}>
          {live.map((connection) => (
            <ConnectionCard key={connection.id} agencyId={agencyId} clientId={clientId} connection={connection} manager={manager} />
          ))}
        </section>
      ) : null}

      {past.length > 0 ? (
        <section className="c-card" aria-labelledby="connections-past">
          <div className="c-card__header">
            <div>
              <h2 className="c-card__title" id="connections-past">
                <FormattedMessage id="connections.past.title" />
              </h2>
              <p className="c-card__subtitle">
                <FormattedMessage id="connections.past.lead" />
              </p>
            </div>
          </div>
          <div className="c-card__body c-card__body--flush">
            <div className="c-table-wrap">
              <table className="c-table">
                <thead>
                  <tr>
                    <th scope="col">
                      <FormattedMessage id="connections.past.account" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="connections.past.connected" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="connections.past.disconnected" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="connections.past.outcome" />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {past.map((connection) => (
                    <tr key={connection.id}>
                      <td>
                        <span className="l-cluster">
                          <ProviderMark provider={connection.provider} />
                          <span className="c-table__primary">{providerName(connection.provider)}</span>
                        </span>
                      </td>
                      <td>
                        <Day value={connection.connected_at} />
                      </td>
                      <td>{connection.disconnect?.completed_at ? <Day value={connection.disconnect.completed_at} /> : null}</td>
                      <td>
                        <Removal connection={connection} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ) : null}

      {connecting ? <ConnectDialog agencyId={agencyId} clientId={clientId} clientName={client.name} onClose={() => setConnecting(false)} /> : null}
    </>
  );
}
