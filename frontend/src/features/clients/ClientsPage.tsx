import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { useMemo, useState, type ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { clientQuery, clientsQuery, createClient, renameClient, type Client } from '@/api/clients';
import { clientSummaryQuery } from '@/api/connections';
import { describeError } from '@/api/errors';
import { useAgency } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { EmptyState } from '@/components/EmptyState';
import { Icon } from '@/components/Icon';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { Skeleton } from '@/components/Skeleton';
import { Day, RelativeTime } from '@/components/Time';
import { ProviderMark, useProviderName } from '@/features/connections/ProviderMark';
import { initials } from '@/lib/initials';
import { byName } from '@/lib/sort';

import { ClientNameDialog } from './ClientNameDialog';
import { summarize, type ClientSummary } from './summary';

/** What is known about one client's connections while the page is drawn. */
type RowState = { kind: 'loading' } | { kind: 'unread' } | { kind: 'ready'; summary: ClientSummary };

const Dash = ({ label }: { label: ReactNode }) => (
  <>
    <span aria-hidden="true">—</span>
    <span className="u-sr">{label}</span>
  </>
);

function Tile({ label, children, row }: { label: ReactNode; children: ReactNode; row?: ReactNode }) {
  return (
    <article className="c-card c-stat">
      <p className="c-stat__label">{label}</p>
      {children}
      {row ? <p className="c-stat__row">{row}</p> : null}
    </article>
  );
}

/** A figure counted over every client. While one client is unread, or could not be read, there is no figure. */
function Count({ states, count }: { states: RowState[]; count: (summary: ClientSummary) => number }) {
  const intl = useIntl();
  if (states.some((state) => state.kind === 'loading')) {
    return (
      <p className="c-stat__value" role="status" aria-label={intl.formatMessage({ id: 'common.loading' })}>
        <span className="c-skel a-skel--figure" />
      </p>
    );
  }
  if (states.some((state) => state.kind === 'unread')) {
    return (
      <p className="c-stat__value is-absent">
        <Dash label={<FormattedMessage id="clients.summary.unread" />} />
      </p>
    );
  }
  const total = states.reduce((sum, state) => sum + (state.kind === 'ready' ? count(state.summary) : 0), 0);
  return (
    <p className="c-stat__value">
      <span className="u-num">{intl.formatNumber(total)}</span>
    </p>
  );
}

function StatusBadge({ state }: { state: RowState }) {
  const providerName = useProviderName();
  if (state.kind === 'loading') return <span className="c-skel a-skel--chip" />;
  if (state.kind === 'unread') {
    return (
      <Badge icon="circle-dashed">
        <FormattedMessage id="clients.status.unread" />
      </Badge>
    );
  }
  const { summary } = state;
  if (summary.state === 'none') {
    return (
      <Badge icon="plug">
        <FormattedMessage id="clients.status.first" />
      </Badge>
    );
  }
  if (summary.state === 'reconnect') {
    const [first] = summary.reconnect;
    return (
      <Badge tone="danger" icon="circle-alert">
        {summary.reconnect.length === 1 && first ? (
          <FormattedMessage id="clients.status.reconnect" values={{ provider: providerName(first.provider) }} />
        ) : (
          <FormattedMessage id="clients.status.reconnectMany" values={{ count: summary.reconnect.length }} />
        )}
      </Badge>
    );
  }
  if (summary.state === 'disconnecting') {
    return (
      <Badge icon="unplug">
        <FormattedMessage id="connections.status.disconnecting" />
      </Badge>
    );
  }
  return (
    <Badge tone="success" icon="circle-check">
      <FormattedMessage id="connections.status.active" />
    </Badge>
  );
}

interface RowProps {
  agencyId: string;
  client: Client;
  state: RowState;
  manager: boolean;
  onRename: (client: Client) => void;
}

function ClientRow({ agencyId, client, state, manager, onRename }: RowProps) {
  const intl = useIntl();
  const summary = state.kind === 'ready' ? state.summary : null;
  const providers = summary ? [...new Set(summary.live.map((connection) => connection.provider))] : [];
  const unconnected = summary?.state === 'none';
  const open = intl.formatMessage({ id: unconnected && manager ? 'clients.row.setUp' : 'clients.row.open' });
  return (
    <tr>
      <td>
        <span className="l-cluster">
          <span className="c-avatar c-avatar--org" aria-hidden="true">
            {initials(client.name)}
          </span>
          <span>
            <span className="c-table__primary">{client.name}</span>
            <span className="c-table__sub">
              <FormattedMessage id="clients.row.added" values={{ date: <Day value={client.created_at} /> }} />
            </span>
          </span>
        </span>
      </td>
      {state.kind === 'loading' ? (
        <td>
          <span className="c-skel a-skel--chip" />
        </td>
      ) : providers.length > 0 ? (
        <td>
          <span className="l-cluster">
            {providers.map((provider) => (
              <ProviderMark key={provider} provider={provider} labelled />
            ))}
          </span>
        </td>
      ) : (
        <td className="is-absent">
          {summary ? <FormattedMessage id="clients.row.none" /> : <Dash label={<FormattedMessage id="clients.status.unread" />} />}
        </td>
      )}
      {summary?.lastSync ? (
        <td>
          <RelativeTime value={summary.lastSync} />
        </td>
      ) : (
        <td className="is-absent">
          {state.kind === 'loading' ? <span className="c-skel a-skel--chip" /> : null}
          {state.kind === 'unread' ? <Dash label={<FormattedMessage id="clients.status.unread" />} /> : null}
          {summary ? <FormattedMessage id="clients.row.never" /> : null}
        </td>
      )}
      <td>
        <StatusBadge state={state} />
      </td>
      <td className="is-num">
        <span className="l-cluster a-row-actions">
          {manager ? (
            <button
              type="button"
              className="c-btn c-btn--ghost c-btn--sm c-btn--icon"
              aria-label={intl.formatMessage({ id: 'clients.row.rename' }, { name: client.name })}
              onClick={() => onRename(client)}
            >
              <Icon name="pencil" size="sm" />
            </button>
          ) : null}
          <Link
            className="c-btn c-btn--secondary c-btn--sm"
            to="/agencies/$agencyId/clients/$clientId"
            params={{ agencyId, clientId: client.id }}
            aria-label={`${open}: ${client.name}`}
          >
            {open}
          </Link>
        </span>
      </td>
    </tr>
  );
}

/** The clients of the agency, each with the state of its connections. Managers add and rename them. */
export function ClientsPage() {
  usePageTitle('clients.title');
  const intl = useIntl();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { agencyId, manager } = useAgency();
  const clients = useQuery(clientsQuery(agencyId));
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState<Client | null>(null);
  const [renamed, setRenamed] = useState<string | null>(null);

  const sorted = useMemo(() => [...(clients.data ?? [])].sort(byName(intl.locale)), [clients.data, intl.locale]);
  const states: RowState[] = useQueries({
    queries: sorted.map((client) => clientSummaryQuery(agencyId, client.id)),
    combine: (results) =>
      results.map((result): RowState => {
        if (result.isSuccess) return { kind: 'ready', summary: summarize(result.data) };
        return result.isError ? { kind: 'unread' } : { kind: 'loading' };
      }),
  });

  const wanted = search.trim().toLocaleLowerCase(intl.locale);
  const rows = sorted
    .map((client, index) => ({ client, state: states[index] ?? ({ kind: 'loading' } as RowState) }))
    .filter(({ client }) => wanted === '' || client.name.toLocaleLowerCase(intl.locale).includes(wanted));

  const addButton = manager ? (
    <button type="button" className="c-btn c-btn--primary" onClick={() => setAdding(true)}>
      <Icon name="plus" size="sm" />
      <FormattedMessage id="clients.add" />
    </button>
  ) : null;

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="clients.title" />
          </PageHeading>
          <p className="c-pagehead__lead">
            <FormattedMessage id="clients.lead" />
          </p>
        </div>
        {clients.isSuccess && sorted.length > 0 ? <div className="l-cluster">{addButton}</div> : null}
      </div>

      {renamed ? (
        <Notice tone="success">
          <FormattedMessage id="clients.renamed" values={{ name: renamed }} />
        </Notice>
      ) : null}

      {clients.isPending ? (
        <div className="c-card">
          <div className="c-card__body">
            <Skeleton lines={4} />
          </div>
        </div>
      ) : null}

      {clients.isError ? (
        <ErrorNotice
          message={describeError(clients.error)}
          action={
            <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void clients.refetch()}>
              <FormattedMessage id="common.retry" />
            </button>
          }
        />
      ) : null}

      {clients.isSuccess && sorted.length === 0 ? (
        <div className="c-card">
          <EmptyState icon="briefcase-business" title={<FormattedMessage id="clients.empty.title" />} action={addButton}>
            <FormattedMessage id={manager ? 'clients.empty.manager' : 'clients.empty.member'} />
          </EmptyState>
        </div>
      ) : null}

      {clients.isSuccess && sorted.length > 0 ? (
        <>
          <section className="l-grid l-grid--3" aria-label={intl.formatMessage({ id: 'clients.summary.label' })}>
            <Tile label={<FormattedMessage id={manager ? 'clients.summary.active' : 'clients.summary.yours'} />}>
              <p className="c-stat__value">
                <span className="u-num">{intl.formatNumber(sorted.length)}</span>
              </p>
            </Tile>
            <Tile label={<FormattedMessage id="clients.summary.attention" />} row={<FormattedMessage id="clients.summary.attention.row" />}>
              <Count states={states} count={(summary) => summary.reconnect.length} />
            </Tile>
            <Tile label={<FormattedMessage id="clients.summary.unconnected" />} row={<FormattedMessage id="clients.summary.unconnected.row" />}>
              <Count states={states} count={(summary) => (summary.state === 'none' ? 1 : 0)} />
            </Tile>
          </section>

          <section className="c-card" aria-label={intl.formatMessage({ id: 'clients.title' })}>
            <div className="c-card__header">
              <label className="c-search">
                <span className="u-sr">
                  <FormattedMessage id="clients.search" />
                </span>
                <Icon name="search" size="sm" />
                <input
                  className="c-search__input"
                  type="search"
                  placeholder={intl.formatMessage({ id: 'clients.search' })}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
            </div>
            <div className="c-card__body c-card__body--flush">
              {rows.length === 0 ? (
                <p className="a-none" role="status">
                  <FormattedMessage id="clients.noMatch" values={{ search: search.trim() }} />
                </p>
              ) : (
                <div className="c-table-wrap">
                  <table className="c-table">
                    <thead>
                      <tr>
                        <th scope="col">
                          <FormattedMessage id="clients.column.client" />
                        </th>
                        <th scope="col">
                          <FormattedMessage id="clients.column.connections" />
                        </th>
                        <th scope="col">
                          <FormattedMessage id="connections.lastSync" />
                        </th>
                        <th scope="col">
                          <FormattedMessage id="clients.column.status" />
                        </th>
                        <th scope="col">
                          <span className="u-sr">
                            <FormattedMessage id="clients.column.actions" />
                          </span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(({ client, state }) => (
                        <ClientRow key={client.id} agencyId={agencyId} client={client} state={state} manager={manager} onRename={setRenaming} />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div className="c-card__footer" role="status">
              <span>
                {rows.length === sorted.length ? (
                  <FormattedMessage id="clients.count" values={{ count: sorted.length }} />
                ) : (
                  <FormattedMessage id="clients.countFiltered" values={{ shown: rows.length, total: sorted.length }} />
                )}
              </span>
            </div>
          </section>
        </>
      ) : null}

      {adding ? (
        <ClientNameDialog
          title={<FormattedMessage id="clients.add.title" />}
          submitLabel={<FormattedMessage id="clients.add" />}
          initial=""
          save={(name) => createClient(agencyId, name)}
          onClose={() => setAdding(false)}
          onSaved={async (client) => {
            queryClient.setQueryData(clientQuery(agencyId, client.id).queryKey, client);
            await queryClient.invalidateQueries({ queryKey: clientsQuery(agencyId).queryKey, exact: true });
            // The next step for a new client is its first connection.
            await navigate({ to: '/agencies/$agencyId/clients/$clientId', params: { agencyId, clientId: client.id } });
          }}
        />
      ) : null}

      {renaming ? (
        <ClientNameDialog
          title={<FormattedMessage id="clients.rename.title" values={{ name: renaming.name }} />}
          submitLabel={<FormattedMessage id="common.save" />}
          initial={renaming.name}
          save={(name) => renameClient(agencyId, renaming.id, name)}
          onClose={() => setRenaming(null)}
          onSaved={async (client) => {
            queryClient.setQueryData(clientQuery(agencyId, client.id).queryKey, client);
            await queryClient.invalidateQueries({ queryKey: clientsQuery(agencyId).queryKey, exact: true });
            setRenaming(null);
            setRenamed(client.name);
          }}
        />
      ) : null}
    </>
  );
}
