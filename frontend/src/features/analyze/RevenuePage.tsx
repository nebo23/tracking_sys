import { useQuery } from '@tanstack/react-query';
import { getRouteApi } from '@tanstack/react-router';
import { FormattedMessage, useIntl } from 'react-intl';

import { revenueReportQuery, type RevenueReport, type RevenueTotal } from '@/api/reports';
import { useClient } from '@/app/tenant';
import { SeriesChart, type SeriesPoint } from '@/components/charts/SeriesChart';
import { InlineSelect } from '@/components/Choice';
import { TableScroll } from '@/components/TableScroll';
import { QueryStates } from '@/components/ListStates';
import { usePageTitle } from '@/components/PageHeading';

import { Card, Change, NoValue } from './parts';
import { AnalyzeHead, FinanceNotice, financeRefused, money, percent, reportScope, type AnalyzeSearch } from './shared';
import { addDays } from './range';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/revenue');

const verifiedFields = ['captured', 'refunded', 'charged_back', 'reversed', 'corrected', 'net'] as const;
const declaredFields = ['sales', 'refunds'] as const;

/**
 * The verified net of each day in one currency, as a series. The ledger is complete, so a day
 * without postings is a zero it states. The report's rows hold its own days only; the change
 * against the previous period is in the totals.
 */
export function dailyNet(report: RevenueReport, currency: string): SeriesPoint[] {
  const net = new Map<string, number>();
  for (const row of report.rows) {
    if (row.block !== 'verified' || row.currency !== currency) continue;
    net.set(row.date, (net.get(row.date) ?? 0) + row.amount.minor);
  }
  const exponent = report.totals.find((total) => total.currency === currency)?.exponent ?? 2;
  const points: SeriesPoint[] = [];
  for (let day = 0; day < report.period.days; day += 1) {
    const date = addDays(report.period.start, day);
    points.push({ date, current: (net.get(date) ?? 0) / 10 ** exponent });
  }
  return points;
}

/**
 * Revenue (C06): the verified payments of the ledger and the declarations, never added together,
 * per currency, with the items still waiting to be matched (D5 of the completion entry review).
 * Without financial access the page says so and shows no amount.
 */
export function RevenuePage() {
  usePageTitle('analyze.revenue.title');
  const intl = useIntl();
  const { agencyId, clientId } = useClient();
  const search = route.useSearch();
  const navigate = route.useNavigate();
  const { range, scope } = reportScope(agencyId, clientId, search);
  const revenue = useQuery({ ...revenueReportQuery(scope), retry: false });
  const change = (next: Partial<AnalyzeSearch>) => void navigate({ search: (current) => ({ ...current, ...next }), replace: true });
  const report = revenue.data;
  const currencies = report ? [...new Set(report.totals.filter((total) => total.block === 'verified').map((total) => total.currency))] : [];
  const currency = search.metric && currencies.includes(search.metric) ? search.metric : currencies[0];
  const formatDate = (date: string) => intl.formatDate(new Date(`${date}T00:00:00Z`), { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const refused = revenue.isError && financeRefused(revenue.error);

  return (
    <>
      <AnalyzeHead
        title={<FormattedMessage id="analyze.revenue.title" />}
        lead={<FormattedMessage id="analyze.revenue.lead" />}
        range={range}
        compare={scope.compare}
        onRange={(next) => change({ from: next.from, to: next.to })}
        onCompare={(compare) => change({ compare: compare || undefined })}
        csv={refused ? null : { scope, family: 'revenue', parameters: {}, name: `revenue-${range.from}-${range.to}.csv` }}
      />
      {refused ? <FinanceNotice /> : <QueryStates query={revenue} />}
      {report ? (
        <>
          <section className="l-grid l-grid--3" aria-label={intl.formatMessage({ id: 'analyze.revenue.blocks' })}>
            <BlockCard report={report} block="verified" />
            <BlockCard report={report} block="declared" />
            <Card title={<FormattedMessage id="analyze.revenue.unresolved" />} subtitle={<FormattedMessage id="analyze.revenue.unresolvedLead" />}>
              <dl className="a-figures a-figures--flush">
                {(['pending', 'held', 'reconciliation'] as const).map((key) => (
                  <div key={key} className="a-figures__item">
                    <dt>
                      <FormattedMessage id={`analyze.revenue.${key}`} />
                    </dt>
                    <dd className="u-num">{intl.formatNumber(report.unresolved[key])}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          </section>
          {currency ? (
            <Card
              title={<FormattedMessage id="analyze.revenue.daily" />}
              actions={
                currencies.length > 1 ? (
                  <InlineSelect
                    label={intl.formatMessage({ id: 'analyze.currency' })}
                    value={currency}
                    onChange={(next) => change({ metric: next })}
                    options={currencies.map((item) => ({ value: item, label: item }))}
                  />
                ) : null
              }
              footer={<FormattedMessage id="analyze.dayZone" values={{ zone: report.day_zone }} />}
            >
              <SeriesChart
                kind="bar"
                title={intl.formatMessage({ id: 'analyze.revenue.daily' })}
                summary={intl.formatMessage(
                  { id: 'analyze.revenue.chartSummary' },
                  {
                    from: formatDate(range.from),
                    to: formatDate(range.to),
                    total: netText(report, currency, intl),
                  },
                )}
                points={dailyNet(report, currency)}
                compare={false}
                format={(value) => intl.formatNumber(value, { style: 'currency', currency, numberingSystem: 'latn' })}
                formatDate={formatDate}
                currentLabel={intl.formatMessage({ id: 'analyze.chart.current' })}
                previousLabel={intl.formatMessage({ id: 'analyze.chart.previous' })}
                dayLabel={intl.formatMessage({ id: 'analyze.chart.day' })}
              />
            </Card>
          ) : null}
        </>
      ) : null}
    </>
  );
}

function netText(report: RevenueReport, currency: string, intl: ReturnType<typeof useIntl>): string {
  const total = report.totals.find((item) => item.block === 'verified' && item.period === 'current' && item.currency === currency);
  return total ? money(intl, total.net, currency, total.exponent) : intl.formatMessage({ id: 'analyze.revenue.none' });
}

/** One block of the ledger, per currency: verified payments, or declarations that nothing verified. */
function BlockCard({ report, block }: { report: RevenueReport; block: RevenueTotal['block'] }) {
  const intl = useIntl();
  const totals = report.totals.filter((total) => total.block === block && total.period === 'current');
  const fields = block === 'verified' ? verifiedFields : declaredFields;
  return (
    <Card
      title={<FormattedMessage id={`analyze.revenue.${block}`} />}
      subtitle={<FormattedMessage id={`analyze.revenue.${block}Lead`} />}
      flush
    >
      {totals.length === 0 ? (
        <p className="a-pad">
          <NoValue>{intl.formatMessage({ id: block === 'verified' ? 'analyze.revenue.none' : 'analyze.revenue.noDeclared' })}</NoValue>
        </p>
      ) : (
        <TableScroll label={intl.formatMessage({ id: `analyze.revenue.${block}` })}>
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="analyze.revenue.field" />
                </th>
                {totals.map((total) => (
                  <th key={total.currency} scope="col" className="is-num">
                    {total.currency}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr key={field}>
                  <th scope="row">
                    <FormattedMessage id={`analyze.revenue.field.${field}`} />
                  </th>
                  {totals.map((total) => (
                    <td key={total.currency} className="is-num u-num">
                      {money(intl, total[field], total.currency, total.exponent)}
                    </td>
                  ))}
                </tr>
              ))}
              {block === 'verified' && report.comparison
                ? totals.map((total) => {
                    const net = report.comparison?.find((item) => item.block === 'verified' && item.metric === 'net' && item.currency === total.currency);
                    return net ? (
                      <tr key={`change-${total.currency}`}>
                        <th scope="row">
                          <FormattedMessage id="analyze.change" /> ({total.currency})
                        </th>
                        <td colSpan={totals.length}>
                          <Change comparable={net.comparable} percent={percent(intl, net.percent_change)} difference={net.difference ? net.difference.minor : null} reason={net.reason} />
                        </td>
                      </tr>
                    ) : null;
                  })
                : null}
            </tbody>
          </table>
        </TableScroll>
      )}
    </Card>
  );
}
