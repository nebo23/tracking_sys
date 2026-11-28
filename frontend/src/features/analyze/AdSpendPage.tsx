import { useQuery } from '@tanstack/react-query';
import { getRouteApi, Link } from '@tanstack/react-router';
import { FormattedMessage, useIntl } from 'react-intl';

import { spendNamesQuery, spendReportQuery, type SpendLevel, type SpendReport, type SpendRow } from '@/api/reports';
import { useClient } from '@/app/tenant';
import { InlineSelect } from '@/components/Choice';
import { TableScroll } from '@/components/TableScroll';
import { EmptyState } from '@/components/EmptyState';
import { QueryStates } from '@/components/ListStates';
import { usePageTitle } from '@/components/PageHeading';

import { Card, Change, FreshnessBadge, NoValue, ProvisionalBadge, SourceMeta, TotalState } from './parts';
import { AnalyzeHead, FinanceNotice, accountName, chosenConnection, financeRefused, money, percent, reportScope, useSpendConnections, type AnalyzeSearch } from './shared';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/ad-spend');

const levels: SpendLevel[] = ['campaign', 'adset', 'ad'];

/**
 * The name of each row's object, from the 014 read of the same account, days and level. The
 * reports name objects by their IDs only (016-A); a name the read does not know is left out, and
 * the ID is always shown.
 */
export function namedRows(rows: readonly SpendRow[], names: ReadonlyMap<string, string> | undefined): Array<SpendRow & { name: string | null }> {
  return rows.map((row) => ({ ...row, name: row.object_id ? (names?.get(row.object_id) ?? null) : null }));
}

/** Ad spend (C07): what an advertising account spent, per campaign, ad set or ad, in its own days and currency. */
export function AdSpendPage() {
  usePageTitle('analyze.spend.title');
  const intl = useIntl();
  const { agencyId, clientId } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const { range, scope } = reportScope(agencyId, clientId, search);
  const connections = useSpendConnections(agencyId, clientId);
  const connection = chosenConnection(connections.data, search.connection);
  const level: SpendLevel = search.level ?? 'campaign';
  const spend = useQuery({ ...spendReportQuery(scope, connection?.id ?? '', level), enabled: connection !== undefined, retry: false });
  const names = useQuery({ ...spendNamesQuery(scope, connection?.id ?? '', level), enabled: connection !== undefined && spend.isSuccess });
  const change = (next: Partial<AnalyzeSearch>) => void navigate({ search: (current) => ({ ...current, ...next }), replace: true });
  const refused = spend.isError && financeRefused(spend.error);
  const report = spend.data;

  return (
    <>
      <AnalyzeHead
        title={<FormattedMessage id="analyze.spend.title" />}
        lead={<FormattedMessage id="analyze.spend.lead" />}
        range={range}
        compare={scope.compare}
        onRange={(next) => change({ from: next.from, to: next.to })}
        onCompare={(compare) => change({ compare: compare || undefined })}
        csv={connection && !refused ? { scope, family: 'spend', parameters: { connection_id: connection.id, level }, name: `ad-spend-${level}-${range.from}-${range.to}.csv` } : null}
      >
        {connections.data && connections.data.length > 1 && connection ? (
          <InlineSelect
            label={intl.formatMessage({ id: 'analyze.account' })}
            value={connection.id}
            onChange={(id) => change({ connection: id })}
            options={connections.data.map((item) => ({ value: item.id, label: accountName(item, intl) }))}
          />
        ) : null}
        <InlineSelect<SpendLevel>
          label={intl.formatMessage({ id: 'analyze.spend.level' })}
          value={level}
          onChange={(next) => change({ level: next === 'campaign' ? undefined : next })}
          options={levels.map((item) => ({ value: item, label: intl.formatMessage({ id: `analyze.spend.level.${item}` }) }))}
        />
      </AnalyzeHead>

      {connections.isPending ? <QueryStates query={connections} /> : null}
      {connections.data && !connection ? (
        <EmptyState
          icon="megaphone"
          title={<FormattedMessage id="analyze.spend.none.title" />}
          action={
            <Link className="c-btn c-btn--primary" to="/agencies/$agencyId/clients/$clientId/connections" params={{ agencyId, clientId }}>
              <FormattedMessage id="analyze.social.none.action" />
            </Link>
          }
        >
          <FormattedMessage id="analyze.spend.none.text" />
        </EmptyState>
      ) : null}
      {refused ? <FinanceNotice /> : connection ? <QueryStates query={spend} /> : null}

      {report && connection ? (
        <>
          <SpendSource report={report} name={accountName(connection, intl)} accountId={connection.account?.external_account_id ?? null} />
          <SpendTotals report={report} />
          <Card title={<FormattedMessage id={`analyze.spend.rows.${level}`} />} subtitle={<FormattedMessage id="analyze.spend.rowsLead" />} flush>
            <SpendTable rows={namedRows(report.rows, names.data)} label={intl.formatMessage({ id: `analyze.spend.rows.${level}` })} />
          </Card>
        </>
      ) : null}
    </>
  );
}

/** The account behind the figures: its currency and time zone, how recent its data is, what was refused. */
function SpendSource({ report, name, accountId }: { report: SpendReport; name: string; accountId: string | null }) {
  const intl = useIntl();
  const source = report.source_status;
  const current = source.periods.find((period) => period.period === 'current');
  const refused = current ? current.refused.unparseable_amount + current.refused.unsupported_currency : 0;
  return (
    <Card title={<FormattedMessage id="analyze.spend.account" />} footer={<SourceMeta source={name} dayZone={report.day_zone} synced={source.connection_last_successful_sync_at} />}>
      <dl className="a-figures a-figures--flush">
        <div className="a-figures__item">
          <dt>
            <FormattedMessage id="analyze.spend.accountId" />
          </dt>
          <dd className="u-ltr">{accountId ?? <NoValue>{intl.formatMessage({ id: 'analyze.spend.accountUnknown' })}</NoValue>}</dd>
        </div>
        <div className="a-figures__item">
          <dt>
            <FormattedMessage id="analyze.currency" />
          </dt>
          <dd>{source.account?.currency ?? '-'}</dd>
        </div>
        <div className="a-figures__item">
          <dt>
            <FormattedMessage id="analyze.spend.timeZone" />
          </dt>
          <dd className="u-ltr">{source.account?.time_zone ?? '-'}</dd>
        </div>
        <div className="a-figures__item">
          <dt>
            <FormattedMessage id="analyze.freshness" />
          </dt>
          <dd>
            <FreshnessBadge state={source.stream.freshness.state} />
          </dd>
        </div>
        <div className="a-figures__item">
          <dt>
            <FormattedMessage id="analyze.spend.refused" />
          </dt>
          <dd className="u-num">{intl.formatNumber(refused)}</dd>
        </div>
      </dl>
      {source.adapter_state === 'unavailable' ? (
        <p className="u-secondary">
          <FormattedMessage id="analyze.source.adapterUnavailable" />
        </p>
      ) : null}
    </Card>
  );
}

/** The totals per original currency, with their state and their change. */
function SpendTotals({ report }: { report: SpendReport }) {
  const intl = useIntl();
  const totals = report.totals.filter((total) => total.period === 'current');
  if (totals.length === 0) {
    const current = report.source_status.periods.find((period) => period.period === 'current');
    return (
      <Card title={<FormattedMessage id="analyze.spend.totals" />}>
        <TotalState status="unavailable" reason={current?.reason ?? 'no_spend_facts'} />
      </Card>
    );
  }
  return (
    <section className="l-grid l-grid--3" aria-label={intl.formatMessage({ id: 'analyze.spend.totals' })}>
      {totals.map((total) => {
        const changeOf = (metric: 'spend' | 'impressions' | 'clicks') =>
          report.comparison?.find((item) => item.currency === total.currency && item.metric === metric);
        const spent = changeOf('spend');
        return (
          <article key={total.currency} className="c-card c-stat">
            <p className="c-stat__label">
              <FormattedMessage id="analyze.spend.spent" /> {total.provisional ? <ProvisionalBadge /> : null}
            </p>
            <div className="c-stat__value">
              <span className="c-stat__unit">{total.currency}</span>
              <span className="u-num">{money(intl, total.spend, total.currency, total.exponent)}</span>
            </div>
            {total.status !== 'complete' ? (
              <p className="c-stat__row">
                <TotalState status={total.status} reason={total.reason} />
              </p>
            ) : null}
            {spent ? (
              <Change
                comparable={spent.comparable}
                percent={percent(intl, spent.percent_change)}
                difference={typeof spent.difference === 'object' && spent.difference ? spent.difference.minor : (spent.difference as number | null)}
                reason={spent.reason}
                rising="neutral"
              />
            ) : null}
            <p className="c-stat__meta">
              <FormattedMessage
                id="analyze.spend.reach"
                values={{ impressions: intl.formatNumber(total.impressions), clicks: intl.formatNumber(total.clicks), days: total.days_with_spend }}
              />
            </p>
          </article>
        );
      })}
    </section>
  );
}

function SpendTable({ rows, label }: { rows: Array<SpendRow & { name: string | null }>; label: string }) {
  const intl = useIntl();
  if (rows.length === 0) {
    return (
      <p className="a-pad u-secondary">
        <FormattedMessage id="analyze.reason.no_spend_facts" />
      </p>
    );
  }
  return (
    <TableScroll label={label}>
      <table className="c-table">
        <thead>
          <tr>
            <th scope="col">
              <FormattedMessage id="analyze.spend.object" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="analyze.spend.spent" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="analyze.spend.impressions" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="analyze.spend.clicks" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="analyze.spend.days" />
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.object_id ?? 'none'}:${row.currency}`}>
              <th scope="row">
                <span className="c-table__primary">{row.name ?? (row.object_id ? <FormattedMessage id="analyze.spend.unnamed" /> : <FormattedMessage id="analyze.spend.noObject" />)}</span>
                {row.object_id ? <span className="c-table__sub u-ltr">{row.object_id}</span> : null}
              </th>
              <td className="is-num u-num">
                {money(intl, row.spend, row.currency, row.exponent)} {row.provisional ? <ProvisionalBadge /> : null}
              </td>
              <td className="is-num u-num">{intl.formatNumber(row.impressions)}</td>
              <td className="is-num u-num">{intl.formatNumber(row.clicks)}</td>
              <td className="is-num u-num">{intl.formatNumber(row.days_with_spend)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
