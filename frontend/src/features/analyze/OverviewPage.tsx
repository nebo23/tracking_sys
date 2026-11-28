import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { getRouteApi, Link } from '@tanstack/react-router';
import { FormattedMessage, useIntl } from 'react-intl';

import { revenueReportQuery, socialReportQuery, spendReportQuery, type RevenueReport, type SocialReport, type SpendReport } from '@/api/reports';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { TableScroll } from '@/components/TableScroll';
import { SeriesChart } from '@/components/charts/SeriesChart';
import { InlineSelect } from '@/components/Choice';
import { Skeleton } from '@/components/Skeleton';
import { usePageTitle } from '@/components/PageHeading';

import { SocialSourceNotices, useGapWords } from './ContentPage';
import { Card, Change, FreshnessBadge, NoValue, SourceMeta, Stat, TotalState, useCount, useMetricName } from './parts';
import {
  AnalyzeHead,
  accountName,
  chosenConnection,
  financeRefused,
  money,
  percent,
  reportScope,
  useSocialConnections,
  useSpendConnections,
  type AnalyzeSearch,
} from './shared';
import { previousRange } from './range';
import { comparisonOf, dailyMetrics, dailySeries, totalOf } from './social';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/');

/** The second key figure of a social account: interactions on Instagram, watch time on YouTube. */
const secondMetric = (report: SocialReport | undefined) =>
  report && dailyMetrics(report).includes('total_interactions') ? 'total_interactions' : 'estimatedMinutesWatched';

/**
 * The overview of a client (C01, C04 on a phone): what it published, how far it travelled and
 * what was sold, each figure with its source, its day and its state (D5 of the completion entry review).
 */
export function OverviewPage() {
  usePageTitle('analyze.overview.title');
  const intl = useIntl();
  const { agencyId, clientId, client } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const { range, scope } = reportScope(agencyId, clientId, search);
  const social = useSocialConnections(agencyId, clientId);
  const spendConnections = useSpendConnections(agencyId, clientId);
  const connection = chosenConnection(social.data, search.connection);
  const spendConnection = spendConnections.data?.[0];
  const daily = useQuery({ ...socialReportQuery(scope, connection?.id ?? '', 'daily'), enabled: connection !== undefined });
  // A report holds its own days only: the previous period's line comes from its own report.
  const previousDaily = useQuery({
    ...socialReportQuery({ ...scope, range: previousRange(scope.range), compare: false }, connection?.id ?? '', 'daily'),
    enabled: connection !== undefined && scope.compare,
  });
  const revenue = useQuery({ ...revenueReportQuery(scope), retry: false });
  const spend = useQuery({ ...spendReportQuery(scope, spendConnection?.id ?? '', 'campaign'), enabled: spendConnection !== undefined, retry: false });
  const metricName = useMetricName();
  const count = useCount();
  const gapWords = useGapWords();
  const formatDate = (date: string) => intl.formatDate(new Date(`${date}T00:00:00Z`), { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const change = (next: Partial<AnalyzeSearch>) => void navigate({ search: (current) => ({ ...current, ...next }), replace: true });

  const metrics = daily.data ? dailyMetrics(daily.data) : [];
  const metric = search.metric && metrics.includes(search.metric) ? search.metric : 'views';

  return (
    <>
      <AnalyzeHead
        title={<FormattedMessage id="analyze.overview.title" />}
        lead={<FormattedMessage id="analyze.overview.lead" values={{ client: client.name }} />}
        range={range}
        compare={scope.compare}
        onRange={(next) => change({ from: next.from, to: next.to })}
        onCompare={(compare) => change({ compare: compare || undefined })}
      >
        {social.data && social.data.length > 1 && connection ? (
          <InlineSelect
            label={intl.formatMessage({ id: 'analyze.account' })}
            value={connection.id}
            onChange={(id) => change({ connection: id })}
            options={social.data.map((item) => ({ value: item.id, label: accountName(item, intl) }))}
          />
        ) : null}
      </AnalyzeHead>

      {daily.data ? <SocialSourceNotices report={daily.data} connectionsPath={{ agencyId, clientId }} /> : null}

      <section className="l-grid l-grid--4" aria-label={intl.formatMessage({ id: 'analyze.overview.figures' })}>
        <SocialStat query={daily} metric="views" connected={connection !== undefined} source={connection ? accountName(connection, intl) : ''} />
        <SocialStat query={daily} metric={secondMetric(daily.data)} connected={connection !== undefined} source={connection ? accountName(connection, intl) : ''} />
        <RevenueStat query={revenue} />
        <SpendStat query={spend} connected={spendConnection !== undefined} source={spendConnection ? accountName(spendConnection, intl) : ''} />
      </section>

      {connection ? (
        <Card
          title={<FormattedMessage id="analyze.overview.chart" values={{ metric: metricName(metric) }} />}
          actions={
            metrics.length > 0 ? (
              <InlineSelect
                label={intl.formatMessage({ id: 'analyze.metric' })}
                value={metric}
                onChange={(next) => change({ metric: next })}
                options={metrics.map((item) => ({ value: item, label: metricName(item) }))}
              />
            ) : null
          }
          footer={
            daily.data ? (
              <SourceMeta source={accountName(connection, intl)} dayZone={daily.data.day_zone} synced={daily.data.source_status.connection_last_successful_sync_at} />
            ) : null
          }
        >
          {daily.isPending ? <Skeleton /> : null}
          {daily.data ? (
            <SeriesChart
              title={intl.formatMessage({ id: 'analyze.overview.chart' }, { metric: metricName(metric) })}
              summary={intl.formatMessage(
                { id: 'analyze.chart.summary' },
                {
                  metric: metricName(metric),
                  from: formatDate(range.from),
                  to: formatDate(range.to),
                  total: totalOf(daily.data, metric)?.value === null || !totalOf(daily.data, metric) ? intl.formatMessage({ id: 'analyze.status.unavailable' }) : count(totalOf(daily.data, metric)?.value ?? 0),
                },
              )}
              points={dailySeries(daily.data, metric, gapWords, scope.compare ? previousDaily.data : undefined)}
              compare={scope.compare && previousDaily.data !== undefined}
              format={count}
              formatDate={formatDate}
              currentLabel={intl.formatMessage({ id: 'analyze.chart.current' })}
              previousLabel={intl.formatMessage({ id: 'analyze.chart.previous' })}
              dayLabel={intl.formatMessage({ id: 'analyze.chart.day' })}
            />
          ) : null}
        </Card>
      ) : null}

      <Sources social={daily.data} spend={spend.data} connected={{ social: connection !== undefined, spend: spendConnection !== undefined }} />
    </>
  );
}

function SocialStat({ query, metric, connected, source }: { query: UseQueryResult<SocialReport>; metric: string; connected: boolean; source: string }) {
  const intl = useIntl();
  const metricName = useMetricName();
  const count = useCount();
  const total = query.data ? totalOf(query.data, metric) : undefined;
  const comparison = query.data ? comparisonOf(query.data, metric) : undefined;
  let value;
  if (!connected) value = <NoValue>{intl.formatMessage({ id: 'analyze.social.none.short' })}</NoValue>;
  else if (query.isPending) value = <span className="c-skel a-skel--name" />;
  else if (!total || total.value === null) value = <NoValue>{intl.formatMessage({ id: 'analyze.status.unavailable' })}</NoValue>;
  else value = <span className="u-num">{count(total.value)}</span>;
  return (
    <Stat
      label={metricName(metric)}
      badge={total?.provisional ? <Badge tone="info" icon="hourglass"><FormattedMessage id="analyze.provisional" /></Badge> : null}
      value={value}
      rows={
        <>
          {total && total.status !== 'complete' ? <p className="c-stat__row"><TotalState status={total.status} reason={total.reason} /></p> : null}
          {comparison ? <Change comparable={comparison.comparable} percent={percent(intl, comparison.percent_change)} difference={comparison.difference} reason={comparison.reason} /> : null}
        </>
      }
      meta={query.data ? <SourceMeta source={source} dayZone={query.data.day_zone} /> : source}
    />
  );
}

function RevenueStat({ query }: { query: UseQueryResult<RevenueReport> }) {
  const intl = useIntl();
  const report = query.data;
  const verified = report?.totals.filter((total) => total.block === 'verified' && total.period === 'current') ?? [];
  const unresolved = report ? report.unresolved.pending + report.unresolved.held + report.unresolved.reconciliation : 0;
  let value;
  if (query.isError && financeRefused(query.error)) value = <NoValue>{intl.formatMessage({ id: 'analyze.finance.short' })}</NoValue>;
  else if (query.isPending) value = <span className="c-skel a-skel--name" />;
  else if (verified.length === 0) value = <NoValue>{intl.formatMessage({ id: 'analyze.revenue.none' })}</NoValue>;
  else
    value = verified.map((total) => (
      <span key={total.currency} className="a-stat__line">
        <span className="c-stat__unit">{total.currency}</span>
        <span className="u-num">{money(intl, total.net, total.currency, total.exponent)}</span>
      </span>
    ));
  const net = report?.comparison?.find((item) => item.block === 'verified' && item.metric === 'net');
  return (
    <Stat
      label={<FormattedMessage id="analyze.revenue.net" />}
      value={value}
      rows={
        <>
          {net ? <Change comparable={net.comparable} percent={percent(intl, net.percent_change)} difference={net.difference ? Number(net.difference.minor) : null} reason={net.reason} /> : null}
          {unresolved > 0 ? (
            <p className="c-stat__row">
              <Badge tone="warning" icon="circle-dot">
                <FormattedMessage id="analyze.revenue.toMatch" values={{ count: unresolved }} />
              </Badge>
            </p>
          ) : null}
        </>
      }
      meta={<FormattedMessage id="analyze.revenue.source" />}
    />
  );
}

function SpendStat({ query, connected, source }: { query: UseQueryResult<SpendReport>; connected: boolean; source: string }) {
  const intl = useIntl();
  const report = query.data;
  const totals = report?.totals.filter((total) => total.period === 'current') ?? [];
  const freshness = report?.source_status.stream.freshness.state;
  let value;
  if (!connected) value = <NoValue>{intl.formatMessage({ id: 'analyze.spend.noAccount' })}</NoValue>;
  else if (query.isError && financeRefused(query.error)) value = <NoValue>{intl.formatMessage({ id: 'analyze.finance.short' })}</NoValue>;
  else if (query.isPending) value = <span className="c-skel a-skel--name" />;
  else if (totals.length === 0) value = <NoValue>{intl.formatMessage({ id: 'analyze.reason.no_spend_facts' })}</NoValue>;
  else
    value = totals.map((total) => (
      <span key={total.currency} className="a-stat__line">
        <span className="c-stat__unit">{total.currency}</span>
        <span className="u-num">{money(intl, total.spend, total.currency, total.exponent)}</span>
      </span>
    ));
  const first = totals[0];
  return (
    <Stat
      label={<FormattedMessage id="analyze.spend.title" />}
      badge={freshness && freshness !== 'fresh' ? <FreshnessBadge state={freshness} /> : null}
      value={value}
      rows={first && first.status !== 'complete' ? <p className="c-stat__row"><TotalState status={first.status} reason={first.reason} /></p> : null}
      meta={report ? <SourceMeta source={source} dayZone={report.day_zone} /> : source}
    />
  );
}

/** Where this page gets its numbers, and how recent each source is. */
function Sources({ social, spend, connected }: { social: SocialReport | undefined; spend: SpendReport | undefined; connected: { social: boolean; spend: boolean } }) {
  const { agencyId, clientId } = useClient();
  const intl = useIntl();
  const rows = [
    ...(social?.source_status.streams.map((stream) => ({ key: `social-${stream.stream}`, name: intl.formatMessage({ id: `provider.${social.source_status.provider}` as never }), detail: stream.stream, state: stream.freshness.state })) ?? []),
    ...(spend ? [{ key: 'spend', name: intl.formatMessage({ id: `provider.${spend.source_status.provider}` as never }), detail: spend.source_status.account?.time_zone ?? '', state: spend.source_status.stream.freshness.state }] : []),
  ];
  return (
    <Card title={<FormattedMessage id="analyze.sources.title" />} subtitle={<FormattedMessage id="analyze.sources.lead" />} flush>
      {rows.length > 0 ? (
        <TableScroll label={intl.formatMessage({ id: 'analyze.sources.title' })}>
          <table className="c-table">
            <tbody>
              {rows.map((row) => (
                <tr key={row.key}>
                  <td>
                    <span className="c-table__primary">{row.name}</span>
                    <span className="c-table__sub u-ltr">{row.detail}</span>
                  </td>
                  <td className="is-num">
                    <FreshnessBadge state={row.state} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      ) : null}
      {!connected.social || !connected.spend ? (
        <p className="a-pad u-secondary">
          <FormattedMessage
            id="analyze.sources.connect"
            values={{
              link: (text) => (
                <Link to="/agencies/$agencyId/clients/$clientId/connections" params={{ agencyId, clientId }}>
                  {text}
                </Link>
              ),
            }}
          />
        </p>
      ) : null}
    </Card>
  );
}
