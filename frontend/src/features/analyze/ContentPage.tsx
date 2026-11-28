import { useQuery } from '@tanstack/react-query';
import { getRouteApi, Link } from '@tanstack/react-router';
import { FormattedMessage, useIntl } from 'react-intl';

import { socialReportQuery, type SocialReport, type SocialRow } from '@/api/reports';
import { useClient } from '@/app/tenant';
import { SeriesChart } from '@/components/charts/SeriesChart';
import { InlineSelect } from '@/components/Choice';
import { TableScroll } from '@/components/TableScroll';
import { EmptyState } from '@/components/EmptyState';
import { QueryStates } from '@/components/ListStates';
import { Notice } from '@/components/Notice';
import { usePageTitle } from '@/components/PageHeading';

import { Card, Change, FreshnessBadge, NoValue, ProvisionalBadge, SourceMeta, TotalState, useCount, useMetricName } from './parts';
import { AnalyzeHead, accountName, chosenConnection, percent, reportScope, useSocialConnections, type AnalyzeSearch } from './shared';
import { previousRange } from './range';
import { cohortMetrics, comparisonOf, contentItems, dailyMetrics, dailySeries, totalOf } from './social';
import { valueState } from './states';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/content');

/** The words for a value that is not available, as the table shows them. */
export function useGapWords(): (row: SocialRow | undefined) => string {
  const intl = useIntl();
  return (row) => {
    if (!row) return intl.formatMessage({ id: 'analyze.availability.missing' });
    const { state, reason } = valueState(row.availability, row.reason);
    return reason ? `${intl.formatMessage({ id: state })}: ${intl.formatMessage({ id: reason })}` : intl.formatMessage({ id: state });
  };
}

/** What stands between a social report and complete figures: a switched-off provider, a lost connection. */
export function SocialSourceNotices({ report, connectionsPath }: { report: SocialReport; connectionsPath: { agencyId: string; clientId: string } }) {
  const source = report.source_status;
  return (
    <>
      {source.adapter_state === 'unavailable' ? (
        <Notice tone="warning">
          <FormattedMessage id="analyze.source.adapterUnavailable" />
        </Notice>
      ) : null}
      {source.connection_status !== 'active' ? (
        <Notice
          tone="danger"
          action={
            <Link to="/agencies/$agencyId/clients/$clientId/connections" params={connectionsPath}>
              <FormattedMessage id="analyze.source.review" />
            </Link>
          }
        >
          <FormattedMessage id="analyze.source.connection" />
        </Notice>
      ) : null}
    </>
  );
}

/** Content (C05): what a social account did day by day, and what it published in the range. */
export function ContentPage() {
  usePageTitle('analyze.content.title');
  const intl = useIntl();
  const { agencyId, clientId } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const { range, scope } = reportScope(agencyId, clientId, search);
  const connections = useSocialConnections(agencyId, clientId);
  const connection = chosenConnection(connections.data, search.connection);
  const daily = useQuery({ ...socialReportQuery(scope, connection?.id ?? '', 'daily'), enabled: connection !== undefined });
  // A report holds its own days only: the previous period's line comes from its own report.
  const previousDaily = useQuery({
    ...socialReportQuery({ ...scope, range: previousRange(scope.range), compare: false }, connection?.id ?? '', 'daily'),
    enabled: connection !== undefined && scope.compare,
  });
  const cohort = useQuery({ ...socialReportQuery(scope, connection?.id ?? '', 'content_cohort'), enabled: connection !== undefined });
  const metricName = useMetricName();
  const count = useCount();
  const gapWords = useGapWords();
  const formatDate = (date: string) => intl.formatDate(new Date(`${date}T00:00:00Z`), { day: 'numeric', month: 'short', timeZone: 'UTC' });

  const change = (next: Partial<AnalyzeSearch>) => void navigate({ search: (current) => ({ ...current, ...next }), replace: true });
  const metrics = daily.data ? dailyMetrics(daily.data) : [];
  // Views first, as people read an account; otherwise the first metric the report totals.
  const metric = search.metric && metrics.includes(search.metric) ? search.metric : metrics.includes('views') ? 'views' : (metrics[0] ?? 'views');

  return (
    <>
      <AnalyzeHead
        title={<FormattedMessage id="analyze.content.title" />}
        lead={<FormattedMessage id="analyze.content.lead" />}
        range={range}
        compare={scope.compare}
        onRange={(next) => change({ from: next.from, to: next.to })}
        onCompare={(compare) => change({ compare: compare || undefined })}
        csv={connection ? { scope, family: 'social', parameters: { connection_id: connection.id, view: 'daily' }, name: `content-${range.from}-${range.to}.csv` } : null}
      >
        {connections.data && connections.data.length > 1 && connection ? (
          <InlineSelect
            label={intl.formatMessage({ id: 'analyze.account' })}
            value={connection.id}
            onChange={(id) => change({ connection: id, metric: undefined })}
            options={connections.data.map((item) => ({ value: item.id, label: accountName(item, intl) }))}
          />
        ) : null}
      </AnalyzeHead>

      {connections.isPending ? <QueryStates query={connections} /> : null}
      {connections.data && !connection ? (
        <EmptyState
          icon="plug"
          title={<FormattedMessage id="analyze.social.none.title" />}
          action={
            <Link className="c-btn c-btn--primary" to="/agencies/$agencyId/clients/$clientId/connections" params={{ agencyId, clientId }}>
              <FormattedMessage id="analyze.social.none.action" />
            </Link>
          }
        >
          <FormattedMessage id="analyze.social.none.text" />
        </EmptyState>
      ) : null}

      {connection ? (
        <>
          {daily.data ? <SocialSourceNotices report={daily.data} connectionsPath={{ agencyId, clientId }} /> : null}
          <Card
            title={<FormattedMessage id="analyze.content.daily" />}
            subtitle={<FormattedMessage id="analyze.content.dailyLead" />}
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
                <>
                  <SourceMeta
                    source={accountName(connection, intl)}
                    dayZone={daily.data.day_zone}
                    synced={daily.data.source_status.connection_last_successful_sync_at}
                  />
                  {daily.data.source_status.streams
                    .filter((stream) => stream.stream === 'account' || stream.stream === 'channel_daily')
                    .map((stream) => (
                      <FreshnessBadge key={stream.stream} state={stream.freshness.state} />
                    ))}
                </>
              ) : null
            }
          >
            <QueryStates query={daily} />
            {daily.data ? (
              <SeriesChart
                title={intl.formatMessage({ id: 'analyze.content.chartTitle' }, { metric: metricName(metric) })}
                summary={intl.formatMessage(
                  { id: 'analyze.chart.summary' },
                  { metric: metricName(metric), from: formatDate(range.from), to: formatDate(range.to), total: totalText(daily.data, metric, count, intl) },
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

          {daily.data ? <TotalsTable report={daily.data} metrics={metrics} /> : null}
          <CohortCard query={cohort} />
        </>
      ) : null}
    </>
  );
}

function totalText(report: SocialReport, metric: string, count: (value: number) => string, intl: ReturnType<typeof useIntl>): string {
  const total = totalOf(report, metric);
  if (!total || total.value === null) return intl.formatMessage({ id: 'analyze.status.unavailable' });
  return count(total.value);
}

/** Each daily metric's total for the range, its state and its change. */
function TotalsTable({ report, metrics }: { report: SocialReport; metrics: string[] }) {
  const intl = useIntl();
  const metricName = useMetricName();
  const count = useCount();
  return (
    <Card title={<FormattedMessage id="analyze.content.totals" />} flush>
      <TableScroll label={intl.formatMessage({ id: 'analyze.content.totals' })}>
        <table className="c-table">
          <thead>
            <tr>
              <th scope="col">
                <FormattedMessage id="analyze.metric" />
              </th>
              <th scope="col" className="is-num">
                <FormattedMessage id="analyze.total" />
              </th>
              {report.comparison ? (
                <th scope="col">
                  <FormattedMessage id="analyze.change" />
                </th>
              ) : null}
              <th scope="col">
                <FormattedMessage id="analyze.state" />
              </th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => {
              const total = totalOf(report, metric);
              const comparison = comparisonOf(report, metric);
              return (
                <tr key={metric}>
                  <th scope="row">{metricName(metric)}</th>
                  <td className="is-num u-num">
                    {total && total.value !== null ? count(total.value) : <NoValue>{intl.formatMessage({ id: 'analyze.status.unavailable' })}</NoValue>}
                  </td>
                  {report.comparison ? (
                    <td>
                      {comparison ? (
                        <Change
                          comparable={comparison.comparable}
                          percent={percent(intl, comparison.percent_change)}
                          difference={comparison.difference}
                          reason={comparison.reason}
                        />
                      ) : null}
                    </td>
                  ) : null}
                  <td>
                    {total ? <TotalState status={total.status} reason={total.reason} /> : null}
                    {total?.provisional ? <ProvisionalBadge /> : null}
                    {total && total.status === 'complete' && !total.provisional ? <FormattedMessage id="analyze.status.complete" /> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>
    </Card>
  );
}

/** The content published on the range's days, with what it earned up to its fetch time. */
function CohortCard({ query }: { query: ReturnType<typeof useQuery<SocialReport>> }) {
  const intl = useIntl();
  const metricName = useMetricName();
  const count = useCount();
  const gapWords = useGapWords();
  const report = query.data;
  const metrics = report ? cohortMetrics(report) : [];
  const items = report ? contentItems(report) : [];
  const unknown = report?.source_status.publication_unknown ?? 0;
  const status = report?.totals.find((total) => total.period === 'current' && metrics.includes(total.metric));

  return (
    <Card
      title={<FormattedMessage id="analyze.content.cohort" />}
      subtitle={<FormattedMessage id="analyze.content.cohortLead" />}
      footer={status ? <TotalState status={status.status} reason={status.reason} /> : null}
      flush
    >
      <QueryStates query={query} />
      {report && items.length === 0 ? (
        <p className="a-pad u-secondary">
          <FormattedMessage id="analyze.content.cohortNone" />
        </p>
      ) : null}
      {items.length > 0 ? (
        <TableScroll label={intl.formatMessage({ id: 'analyze.content.cohort' })}>
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="analyze.content.item" />
                </th>
                <th scope="col">
                  <FormattedMessage id="analyze.content.published" />
                </th>
                {metrics.map((metric) => (
                  <th key={metric} scope="col" className="is-num">
                    {metricName(metric)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={`${item.stream}:${item.id}`}>
                  <th scope="row">
                    <span className="c-table__primary u-ltr">{item.id}</span>
                    <span className="c-table__sub">{item.productType ?? item.stream}</span>
                  </th>
                  <td>{item.publishedDate ? intl.formatDate(new Date(`${item.publishedDate}T00:00:00Z`), { day: 'numeric', month: 'short', timeZone: 'UTC' }) : null}</td>
                  {metrics.map((metric) => {
                    const row = item.values.get(metric);
                    return (
                      <td key={metric} className="is-num u-num">
                        {row && row.availability === 'available' && typeof row.value === 'number' ? count(row.value) : <NoValue>{gapWords(row)}</NoValue>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      ) : null}
      {unknown > 0 ? (
        <p className="a-pad u-secondary">
          <FormattedMessage id="analyze.content.publicationUnknown" values={{ count: unknown }} />
        </p>
      ) : null}
    </Card>
  );
}
