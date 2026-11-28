import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { useMemo, useState, type ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import {
  archivedClientsKey,
  archivedClientsQuery,
  clientKey,
  clientQuery,
  clientsKey,
  clientsQuery,
  createClient,
  renameClient,
  setClientStatus,
  type Client,
} from '@/api/clients';
import { clientSummaryQuery } from '@/api/connections';
import { describeError, type ErrorMessage } from '@/api/errors';
import { membersQuery } from '@/api/team';
import { useAgency } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { EmptyState } from '@/components/EmptyState';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { RowMenu } from '@/components/RowMenu';
import { Skeleton } from '@/components/Skeleton';
import { Day, RelativeTime } from '@/components/Time';
import { ProviderMark, useProviderName } from '@/features/connections/ProviderMark';
import { peopleWithAccess } from '@/features/team/members';
import { cx } from '@/lib/cx';
import { initials } from '@/lib/initials';
import { byName } from '@/lib/sort';

import { ClientNameDialog } from './ClientNameDialog';
import { summarize, type ClientSummary } from './summary';

/** What is known about one client's connections while the page is drawn. */
type RowState = { kind: 'loading' } | { kind: 'unread' } | { kind: 'ready'; summary: ClientSummary };

type View = 'active' | 'archived';

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
  /** How many people can open the client, as a figure or a placeholder. Managers only. */
  people: ReactNode;
  onRename: (client: Client) => void;
  onArchive: (client: Client) => void;
}

function ClientRow({ agencyId, client, state, manager, people, onRename, onArchive }: RowProps) {
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
      {manager ? (
        <td className="is-num">{people}</td>
      ) : null}
      <td className="is-num">
        <span className="l-cluster a-row-actions">
          {manager ? (
            <RowMenu
              label={intl.formatMessage({ id: 'clients.row.actions' }, { name: client.name })}
              actions={[
                { id: 'rename', label: <FormattedMessage id="clients.row.rename.short" />, text: intl.formatMessage({ id: 'clients.row.rename.short' }), onAction: () => onRename(client) },
                { id: 'archive', label: <FormattedMessage id="clients.archive" />, text: intl.formatMessage({ id: 'clients.archive' }), onAction: () => onArchive(client), danger: true },
              ]}
            />
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

interface ArchiveDialogProps {
  agencyId: string;
  client: Client;
  onArchived: () => void;
  onClose: () => void;
}

/** Archiving is asked: nobody can open the client and its accounts stop syncing until it is restored. */
function ArchiveDialog({ agencyId, client, onArchived, onClose }: ArchiveDialogProps) {
  const queryClient = useQueryClient();
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({
    mutationFn: () => setClientStatus(agencyId, client.id, 'archived'),
    async onSuccess() {
      // Nobody may open an archived client: nothing loaded for it is kept to be drawn again.
      queryClient.removeQueries({ queryKey: clientKey(agencyId, client.id) });
      queryClient.removeQueries({ queryKey: clientSummaryQuery(agencyId, client.id).queryKey });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: clientsKey(agencyId), exact: true }),
        queryClient.invalidateQueries({ queryKey: archivedClientsKey(agencyId) }),
      ]);
      onArchived();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  return (
    <FormDialog
      isOpen
      alert
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="clients.archive.title" values={{ name: client.name }} />}
      submitLabel={<FormattedMessage id="clients.archive" />}
      cancelLabel={<FormattedMessage id="clients.archive.keep" />}
      tone="danger"
      busy={request.isPending}
      onSubmit={() => {
        setProblem(null);
        request.mutate();
      }}
    >
      <p>
        <FormattedMessage id="clients.archive.text" />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}

/** The clients of the agency, each with the state of its connections. Managers add, rename, archive and restore them. */
export function ClientsPage() {
  usePageTitle('clients.title');
  const intl = useIntl();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { agencyId, manager } = useAgency();
  const clients = useQuery(clientsQuery(agencyId));
  const archived = useQuery({ ...archivedClientsQuery(agencyId), enabled: manager });
  const members = useQuery({ ...membersQuery(agencyId), enabled: manager });
  const [view, setView] = useState<View>('active');
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState<Client | null>(null);
  const [archiving, setArchiving] = useState<Client | null>(null);
  const [notice, setNotice] = useState<ReactNode>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);

  const sorted = useMemo(() => [...(clients.data ?? [])].sort(byName(intl.locale)), [clients.data, intl.locale]);
  const sortedArchived = useMemo(() => [...(archived.data ?? [])].sort(byName(intl.locale)), [archived.data, intl.locale]);
  const states: RowState[] = useQueries({
    queries: sorted.map((client) => clientSummaryQuery(agencyId, client.id)),
    combine: (results) =>
      results.map((result): RowState => {
        if (result.isSuccess) return { kind: 'ready', summary: summarize(result.data) };
        return result.isError ? { kind: 'unread' } : { kind: 'loading' };
      }),
  });

  const restore = useMutation({
    mutationFn: (client: Client) => setClientStatus(agencyId, client.id, 'active'),
    async onSuccess(client) {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: clientsKey(agencyId), exact: true }),
        queryClient.invalidateQueries({ queryKey: archivedClientsKey(agencyId) }),
      ]);
      setNotice(<FormattedMessage id="clients.restored" values={{ name: client.name }} />);
    },
    onError: (failure) => setProblem(describeError(failure)),
  });

  const say = (message: ReactNode) => {
    setProblem(null);
    setNotice(message);
  };

  const peopleCell = (clientId: string): ReactNode => {
    if (members.isSuccess) return <span className="u-num">{intl.formatNumber(peopleWithAccess(members.data, clientId))}</span>;
    if (members.isError) return <Dash label={<FormattedMessage id="clients.status.unread" />} />;
    return <span className="c-skel a-skel--figure" />;
  };

  const wanted = search.trim().toLocaleLowerCase(intl.locale);
  const matches = (client: Client) => wanted === '' || client.name.toLocaleLowerCase(intl.locale).includes(wanted);
  const rows = sorted
    .map((client, index) => ({ client, state: states[index] ?? ({ kind: 'loading' } as RowState) }))
    .filter(({ client }) => matches(client));
  const archivedRows = sortedArchived.filter(matches);
  const shown = view === 'active' ? rows.length : archivedRows.length;
  const total = view === 'active' ? sorted.length : sortedArchived.length;
  const archivedCount = archived.data?.length ?? 0;

  const addButton = manager ? (
    <button type="button" className="c-btn c-btn--primary" onClick={() => setAdding(true)}>
      <Icon name="plus" size="sm" />
      <FormattedMessage id="clients.add" />
    </button>
  ) : null;

  // The list stays in view while there are archived clients to show, even with no active one.
  const hasList = sorted.length > 0 || archivedCount > 0;

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
        {clients.isSuccess && hasList ? <div className="l-cluster">{addButton}</div> : null}
      </div>

      {notice ? <Notice tone="success">{notice}</Notice> : null}
      <ErrorNotice message={problem} />

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

      {clients.isSuccess && !hasList && (!manager || archived.isSuccess || archived.isError) ? (
        <div className="c-card">
          <EmptyState icon="briefcase-business" title={<FormattedMessage id="clients.empty.title" />} action={addButton}>
            <FormattedMessage id={manager ? 'clients.empty.manager' : 'clients.empty.member'} />
          </EmptyState>
        </div>
      ) : null}

      {clients.isSuccess && hasList ? (
        <>
          <section className="l-grid l-grid--3" aria-label={intl.formatMessage({ id: 'clients.summary.label' })}>
            <Tile
              label={<FormattedMessage id={manager ? 'clients.summary.active' : 'clients.summary.yours'} />}
              row={archivedCount > 0 ? <FormattedMessage id="clients.summary.archived" values={{ count: archivedCount }} /> : undefined}
            >
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
              {manager ? (
                <div className="c-seg" role="group" aria-label={intl.formatMessage({ id: 'clients.view' })}>
                  {(['active', 'archived'] as const).map((option) => (
                    <button
                      key={option}
                      type="button"
                      className={cx('c-seg__item', view === option && 'is-active')}
                      aria-pressed={view === option}
                      onClick={() => setView(option)}
                    >
                      <FormattedMessage id={`clients.view.${option}`} />
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
            <div className="c-card__body c-card__body--flush">
              {view === 'archived' && archived.isPending ? (
                <div className="a-pad">
                  <Skeleton lines={2} />
                </div>
              ) : null}
              {view === 'archived' && archived.isError ? (
                <div className="a-pad">
                  <ErrorNotice
                    message={describeError(archived.error)}
                    action={
                      <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void archived.refetch()}>
                        <FormattedMessage id="common.retry" />
                      </button>
                    }
                  />
                </div>
              ) : null}
              {view === 'archived' && archived.isSuccess && sortedArchived.length === 0 ? (
                <p className="a-none" role="status">
                  <FormattedMessage id="clients.archived.none" />
                </p>
              ) : null}
              {shown === 0 && total > 0 ? (
                <p className="a-none" role="status">
                  <FormattedMessage id="clients.noMatch" values={{ search: search.trim() }} />
                </p>
              ) : null}
              {view === 'active' && sorted.length === 0 ? (
                <p className="a-none" role="status">
                  <FormattedMessage id="clients.active.none" />
                </p>
              ) : null}

              {view === 'active' && rows.length > 0 ? (
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
                        {manager ? (
                          <th scope="col" className="is-num">
                            <FormattedMessage id="clients.column.people" />
                          </th>
                        ) : null}
                        <th scope="col">
                          <span className="u-sr">
                            <FormattedMessage id="clients.column.actions" />
                          </span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(({ client, state }) => (
                        <ClientRow
                          key={client.id}
                          agencyId={agencyId}
                          client={client}
                          state={state}
                          manager={manager}
                          people={peopleCell(client.id)}
                          onRename={setRenaming}
                          onArchive={(chosen) => {
                            setNotice(null);
                            setArchiving(chosen);
                          }}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}

              {view === 'archived' && archivedRows.length > 0 ? (
                <div className="c-table-wrap">
                  <table className="c-table">
                    <thead>
                      <tr>
                        <th scope="col">
                          <FormattedMessage id="clients.column.client" />
                        </th>
                        <th scope="col">
                          <span className="u-sr">
                            <FormattedMessage id="clients.column.actions" />
                          </span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {archivedRows.map((client) => (
                        <tr key={client.id}>
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
                          <td className="is-num">
                            <button
                              type="button"
                              className={cx('c-btn c-btn--secondary c-btn--sm', restore.isPending && restore.variables?.id === client.id && 'is-loading')}
                              aria-label={intl.formatMessage({ id: 'clients.restore.named' }, { name: client.name })}
                              onClick={() => {
                                if (restore.isPending) return;
                                setNotice(null);
                                setProblem(null);
                                restore.mutate(client);
                              }}
                            >
                              <Icon name="history" size="sm" />
                              <FormattedMessage id="clients.restore" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </div>
            <div className="c-card__footer" role="status">
              <span>
                {view === 'archived' ? (
                  <FormattedMessage id="clients.archived.count" values={{ count: sortedArchived.length }} />
                ) : shown === total ? (
                  <FormattedMessage id="clients.count" values={{ count: total }} />
                ) : (
                  <FormattedMessage id="clients.countFiltered" values={{ shown, total }} />
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
            await navigate({ to: '/agencies/$agencyId/clients/$clientId/connections', params: { agencyId, clientId: client.id } });
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
            say(<FormattedMessage id="clients.renamed" values={{ name: client.name }} />);
          }}
        />
      ) : null}

      {archiving ? (
        <ArchiveDialog
          agencyId={agencyId}
          client={archiving}
          onClose={() => setArchiving(null)}
          onArchived={() => {
            const { name } = archiving;
            setArchiving(null);
            say(<FormattedMessage id="clients.archived" values={{ name }} />);
          }}
        />
      ) : null}
    </>
  );
}
