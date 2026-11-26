import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import {
  connectionsKey,
  coverageQuery,
  reconnect,
  requestSync,
  type Connection,
  type CostState,
  type Coverage,
  type StreamCoverage,
} from '@/api/connections';
import { describeError, type ErrorMessage } from '@/api/errors';
import { Badge } from '@/components/Badge';
import { Icon } from '@/components/Icon';
import { ErrorNotice, Notice } from '@/components/Notice';
import { Skeleton } from '@/components/Skeleton';
import { Day, dayFormat, Moment, RelativeTime } from '@/components/Time';
import { cx } from '@/lib/cx';

import { coverageBar, runReason, statusReason, streamName } from './coverage';
import { DisconnectDialog } from './DisconnectDialog';
import { connectionErrors } from './errors';
import { leaveForProvider } from './leaveForProvider';
import { ProviderMark, useProviderName } from './ProviderMark';
import { providerOf } from './providers';
import { ReconnectDialog } from './ReconnectDialog';

/** How often a card asks again while something is under way: a run, or a removal. */
const WATCH_MS = 5000;

const underWay = (coverage: Coverage | undefined) => coverage?.sync.state === 'queued' || coverage?.sync.state === 'running';

function StatusBadge({ connection }: { connection: Connection }) {
  if (connection.status === 'reconnect_required') {
    return (
      <Badge tone="danger" icon="circle-alert">
        <FormattedMessage id="connections.status.reconnect_required" />
      </Badge>
    );
  }
  if (connection.status === 'disconnecting') {
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

function Freshness({ coverage }: { coverage: Coverage }) {
  if (coverage.freshness === 'fresh') {
    return (
      <Badge tone="success">
        <FormattedMessage id="state.fresh" />
      </Badge>
    );
  }
  if (coverage.freshness === 'stale') {
    return (
      <Badge tone="warning" icon="clock">
        <FormattedMessage id="state.stale" />
      </Badge>
    );
  }
  return (
    <Badge icon="cloud-off">
      <FormattedMessage id="state.not_synced" />
    </Badge>
  );
}

/** The latest run, when it is anything other than finished and quiet. */
function Run({ coverage }: { coverage: Coverage }) {
  const { state, reason, next_attempt_at: next } = coverage.sync;
  if (state === 'idle') return null;
  const why = runReason(reason);
  return (
    <>
      <dt>
        <FormattedMessage id="connections.run" />
      </dt>
      <dd>
        <span className="l-cluster">
          {state === 'running' ? <span className="c-spinner" aria-hidden="true" /> : null}
          {state === 'failed' ? (
            <Badge tone="danger" icon="circle-alert">
              <FormattedMessage id="connections.run.failed" />
            </Badge>
          ) : (
            <span>
              <FormattedMessage id={`connections.run.${state}`} />
            </span>
          )}
        </span>
        {why || next ? (
          <span className="c-table__sub">
            {why ? <FormattedMessage id={why} /> : null}
            {why && next ? ' ' : null}
            {next ? <FormattedMessage id="connections.run.next" values={{ time: <Moment value={next} /> }} /> : null}
          </span>
        ) : null}
      </dd>
    </>
  );
}

function Stream({ stream }: { stream: StreamCoverage }) {
  const intl = useIntl();
  const known = streamName(stream.stream);
  const bar = coverageBar(stream, Date.now());
  const day = (value: string) => intl.formatDate(value, dayFormat);
  const range =
    stream.covered_from && stream.complete_through
      ? intl.formatMessage(
          { id: 'connections.stream.range' },
          { from: day(stream.covered_from), through: day(stream.complete_through) },
        )
      : null;
  return (
    <>
      <dt>{known ? <FormattedMessage id={known} /> : <span className="u-mono u-ltr">{stream.stream}</span>}</dt>
      <dd>
        {bar ? (
          <div className="c-coverage" role="img" aria-label={range ?? undefined}>
            <span className="c-coverage__range" style={{ insetInlineStart: `${bar.start}%`, inlineSize: `${bar.size}%` }} />
          </div>
        ) : null}
        <span className="l-cluster">
          {stream.state === 'complete' ? (
            <Badge tone="success">
              <FormattedMessage id="state.complete" />
            </Badge>
          ) : null}
          {stream.state === 'partial' ? (
            <Badge tone="warning" icon="circle-dot">
              <FormattedMessage id="state.partial" />
            </Badge>
          ) : null}
          {stream.state === 'not_synced' ? (
            <Badge icon="cloud-off">
              <FormattedMessage id="state.not_synced" />
            </Badge>
          ) : null}
          {range ? <span className="u-tertiary">{range}</span> : null}
        </span>
      </dd>
    </>
  );
}

function Allowance({ cost }: { cost: Pick<CostState, 'consumed' | 'allocation' | 'state'>; }) {
  const intl = useIntl();
  const share = cost.allocation > 0 ? Math.min(100, Math.round((cost.consumed / cost.allocation) * 100)) : 0;
  const label = intl.formatMessage({ id: 'connections.allowance.used' }, { used: cost.consumed, of: cost.allocation });
  const exhausted = cost.state === 'exhausted';
  return (
    <>
      <span className={cx('c-meter', exhausted ? 'c-meter--danger' : share >= 80 && 'c-meter--warning')} role="img" aria-label={label}>
        <span className="c-meter__fill" style={{ inlineSize: `${share}%` }} />
      </span>
      <span className="c-table__sub">{label}</span>
    </>
  );
}

interface ConnectionCardProps {
  agencyId: string;
  clientId: string;
  connection: Connection;
  /** True for an owner or admin. The API's own flags decide each action in any case. */
  manager: boolean;
}

/** One connected account: what it is, whether it works, how much is stored, and what can be done. */
export function ConnectionCard({ agencyId, clientId, connection, manager }: ConnectionCardProps) {
  const queryClient = useQueryClient();
  const providerName = useProviderName()(connection.provider);
  const provider = providerOf(connection.provider);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const [requested, setRequested] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [approving, setApproving] = useState(false);
  const scope = { agencyId, clientId };

  const coverage = useQuery({
    ...coverageQuery(agencyId, clientId, connection.id),
    refetchInterval: (query) => (underWay(query.state.data) ? WATCH_MS : false),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: connectionsKey(agencyId, clientId) });

  const sync = useMutation({
    mutationFn: () => requestSync(agencyId, clientId, connection.id),
    async onSuccess() {
      setRequested(true);
      await refresh();
    },
    async onError(failure) {
      setProblem(describeError(failure, connectionErrors));
      await refresh();
    },
  });

  const again = useMutation({
    mutationFn: () => reconnect(agencyId, clientId, connection.id, null),
    onSuccess: ({ authorization_url: address }) => setProblem(leaveForProvider(address, scope)),
    async onError(failure) {
      setProblem(describeError(failure, connectionErrors));
      await refresh();
    },
  });

  const startReconnect = () => {
    setProblem(null);
    // A provider that needs the account holder's approval asks for it again.
    if (provider?.approval != null) setApproving(true);
    else if (!again.isPending) again.mutate();
  };

  const startSync = () => {
    if (sync.isPending) return;
    setProblem(null);
    setRequested(false);
    sync.mutate();
  };

  const account = connection.account?.label ?? connection.account?.external_account_id;
  const titleId = `connection-${connection.id}`;
  const running = underWay(coverage.data);
  const actions: ReactNode[] = [];
  if (manager && connection.status === 'active') {
    actions.push(
      <button
        key="sync"
        type="button"
        className={cx('c-btn c-btn--secondary c-btn--sm', sync.isPending && 'is-loading')}
        aria-busy={sync.isPending || undefined}
        disabled={running}
        onClick={startSync}
      >
        {sync.isPending ? <span className="c-spinner" aria-hidden="true" /> : <Icon name="refresh-cw" size="sm" />}
        <FormattedMessage id="connections.sync" />
      </button>,
    );
  }
  if (connection.actions.reconnect) {
    actions.push(
      <button
        key="reconnect"
        type="button"
        className={cx('c-btn c-btn--primary c-btn--sm', again.isPending && 'is-loading')}
        aria-busy={again.isPending || undefined}
        onClick={startReconnect}
      >
        {again.isPending ? <span className="c-spinner" aria-hidden="true" /> : null}
        <FormattedMessage id="connections.reconnect" />
      </button>,
    );
  }
  if (connection.actions.disconnect) {
    actions.push(
      <button key="disconnect" type="button" className="c-btn c-btn--ghost c-btn--sm u-end" onClick={() => setDisconnecting(true)}>
        <FormattedMessage id="connections.disconnect" />
      </button>,
    );
  }

  return (
    <article className="c-card" aria-labelledby={titleId}>
      <div className="c-card__header">
        <div className="l-cluster">
          <span className="c-avatar c-avatar--lg c-avatar--provider">
            <ProviderMark provider={connection.provider} large />
          </span>
          <div>
            <h2 className="c-card__title" id={titleId}>
              {providerName}
            </h2>
            <p className="c-card__subtitle">
              {account ? (
                <>
                  <span className="u-ltr">{account}</span>
                  {', '}
                </>
              ) : null}
              <FormattedMessage id="connections.connectedOn" values={{ date: <Day value={connection.connected_at} /> }} />
            </p>
          </div>
        </div>
        <StatusBadge connection={connection} />
      </div>

      <div className="c-card__body l-stack">
        <ErrorNotice message={problem} />
        {requested ? (
          <Notice tone="success">
            <FormattedMessage id="connections.sync.requested" />
          </Notice>
        ) : null}

        {connection.status === 'reconnect_required' ? (
          <Notice
            tone="danger"
            quiet
            title={
              <FormattedMessage
                id={statusReason(connection.status_reason, 'connections.reason.credential_expired')}
                values={{ provider: providerName }}
              />
            }
          >
            <FormattedMessage id={manager ? 'connections.reconnect.manager' : 'connections.reconnect.member'} />
          </Notice>
        ) : null}

        {connection.status === 'disconnecting' && connection.disconnect ? (
          <Notice
            quiet
            title={<FormattedMessage id={statusReason(connection.status_reason, 'connections.reason.user_requested')} values={{ provider: providerName }} />}
          >
            <FormattedMessage id="connections.disconnecting.until" values={{ date: <Moment value={connection.disconnect.purge_due_at} /> }} />
          </Notice>
        ) : null}

        {coverage.isPending ? <Skeleton /> : null}
        {coverage.isError ? (
          <ErrorNotice
            message={describeError(coverage.error, connectionErrors)}
            action={
              <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => void coverage.refetch()}>
                <FormattedMessage id="common.retry" />
              </button>
            }
          />
        ) : null}
        {coverage.isSuccess ? (
          <dl className="c-dl">
            <dt>
              <FormattedMessage id="connections.lastSync" />
            </dt>
            <dd>
              <span className="l-cluster">
                {coverage.data.last_successful_sync_at ? <RelativeTime value={coverage.data.last_successful_sync_at} /> : null}
                <Freshness coverage={coverage.data} />
              </span>
            </dd>
            <Run coverage={coverage.data} />
            {coverage.data.streams.map((stream) => (
              <Stream key={stream.stream} stream={stream} />
            ))}
            {coverage.data.cost.buckets.length > 1 ? (
              coverage.data.cost.buckets.map((bucket) => (
                <div key={bucket.bucket} className="a-contents">
                  <dt>
                    <FormattedMessage id="connections.allowance.bucket" values={{ bucket: <span className="u-mono u-ltr">{bucket.bucket}</span> }} />
                  </dt>
                  <dd>
                    <Allowance cost={bucket} />
                  </dd>
                </div>
              ))
            ) : (
              <>
                <dt>
                  <FormattedMessage id="connections.allowance" />
                </dt>
                <dd>
                  <Allowance cost={coverage.data.cost} />
                  {coverage.data.cost.reason ? (
                    <span className="c-table__sub">
                      <FormattedMessage id={`connections.allowance.${coverage.data.cost.reason}`} />
                    </span>
                  ) : null}
                </dd>
              </>
            )}
          </dl>
        ) : null}
      </div>

      {actions.length > 0 ? <div className="c-card__footer">{actions}</div> : null}

      {disconnecting ? (
        <DisconnectDialog
          agencyId={agencyId}
          clientId={clientId}
          connection={connection}
          name={account ? `${providerName} (${account})` : providerName}
          onClose={() => setDisconnecting(false)}
        />
      ) : null}
      {approving ? (
        <ReconnectDialog agencyId={agencyId} clientId={clientId} connection={connection} providerName={providerName} onClose={() => setApproving(false)} />
      ) : null}
    </article>
  );
}
