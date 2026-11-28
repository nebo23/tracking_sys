import { useQuery } from '@tanstack/react-query';
import { FormattedMessage, useIntl } from 'react-intl';

import { funnelReportQuery, type FunnelReport, type FunnelGroup, type ModelVersion, type ReportScope } from '@/api/reports';
import { InlineSelect } from '@/components/Choice';
import { QueryStates } from '@/components/ListStates';
import { TableScroll } from '@/components/TableScroll';

import { Card, NoValue } from '../analyze/parts';
import { Amounts, FreshnessNotice, GroupName, NeedsFinance } from './parts';
import { attributionReason, shareText } from './states';

const groups: FunnelGroup[] = ['campaign', 'content', 'link'];

interface FunnelTabProps {
  scope: ReportScope;
  version: ModelVersion | undefined;
  group: FunnelGroup;
  onGroup: (group: FunnelGroup) => void;
}

/**
 * Funnel (C09): page views through each campaign's links, and the leads and sales credited to it.
 * Each step is counted on its own basis, so the steps are never divided into one another, and a
 * group whose visits cannot be measured says so instead of showing 0.
 */
export function FunnelTab({ scope, version, group, onGroup }: FunnelTabProps) {
  const intl = useIntl();
  const report = useQuery({ ...funnelReportQuery(scope, group, version?.id), enabled: version !== undefined, retry: false });
  const data = report.data;
  return (
    <>
      <QueryStates query={report} />
      {data ? (
        <>
          <FreshnessNotice report={data} />
          <FunnelFigures report={data} />
          <Card
            title={<FormattedMessage id={`attribution.funnel.by.${group}`} />}
            subtitle={<FormattedMessage id="attribution.funnel.lead" />}
            actions={
              <InlineSelect<FunnelGroup>
                label={intl.formatMessage({ id: 'attribution.group.label' })}
                value={group}
                onChange={onGroup}
                options={groups.map((item) => ({ value: item, label: intl.formatMessage({ id: `attribution.group.${item}` }) }))}
              />
            }
            flush
          >
            <FunnelTable report={data} group={group} />
          </Card>
          <Card title={<FormattedMessage id="attribution.funnel.bases.title" />}>
            <dl className="a-figures a-figures--flush">
              {(['visits', 'leads', 'sales'] as const).map((step) => (
                <div key={step} className="a-figures__item">
                  <dt>
                    <FormattedMessage id={`attribution.funnel.step.${step}`} />
                  </dt>
                  <dd className="a-figures__text">
                    <FormattedMessage id={data.bases[step] === 'received_date' ? 'attribution.funnel.basis.received' : 'attribution.funnel.basis.conversion'} />
                  </dd>
                </div>
              ))}
            </dl>
            <p className="u-secondary">
              <FormattedMessage id="attribution.funnel.bases.lead" />
            </p>
          </Card>
        </>
      ) : null}
    </>
  );
}

function FunnelFigures({ report }: { report: FunnelReport }) {
  const intl = useIntl();
  const current = report.totals.find((total) => total.period === 'current');
  if (!current) return null;
  const sales = current.sales;
  return (
    <section className="l-grid l-grid--4" aria-label={intl.formatMessage({ id: 'attribution.funnel.figures' })}>
      <article className="c-card c-stat">
        <p className="c-stat__label">
          <FormattedMessage id="attribution.funnel.pageViews" />
        </p>
        <div className="c-stat__value u-num">{intl.formatNumber(current.page_views)}</div>
        <p className="c-stat__meta">
          <FormattedMessage id="attribution.funnel.pageViewsLead" />
        </p>
      </article>
      <article className="c-card c-stat">
        <p className="c-stat__label">
          <FormattedMessage id="attribution.funnel.linkViews" />
        </p>
        <div className="c-stat__value u-num">{intl.formatNumber(current.link_page_views)}</div>
        <p className="c-stat__meta">
          <FormattedMessage id="attribution.funnel.linkViewsLead" />
        </p>
      </article>
      <article className="c-card c-stat">
        <p className="c-stat__label">
          <FormattedMessage id="attribution.column.leads" />
        </p>
        <div className="c-stat__value u-num">
          {current.leads.state === 'available' ? shareText(intl.locale, current.leads.credited_leads) : <NoValue>{intl.formatMessage({ id: attributionReason('attribution_not_ready') })}</NoValue>}
        </div>
        <p className="c-stat__meta">
          <FormattedMessage id="attribution.funnel.leadsLead" />
        </p>
      </article>
      <article className="c-card c-stat">
        <p className="c-stat__label">
          <FormattedMessage id="attribution.column.sales" />
        </p>
        <div className="c-stat__value">
          {sales.state === 'permission_unavailable' ? (
            <NeedsFinance />
          ) : sales.state === 'not_ready' ? (
            <NoValue>{intl.formatMessage({ id: attributionReason('attribution_not_ready') })}</NoValue>
          ) : (
            <Amounts items={(sales.items ?? []).map((item) => ({ currency: item.currency, exponent: item.exponent, amount: item.credited_revenue }))} />
          )}
        </div>
        <p className="c-stat__meta">
          <FormattedMessage id="attribution.funnel.salesLead" />
        </p>
      </article>
    </section>
  );
}

function FunnelTable({ report, group }: { report: FunnelReport; group: FunnelGroup }) {
  const intl = useIntl();
  if (report.rows.length === 0) {
    return (
      <p className="a-pad u-secondary">
        <FormattedMessage id="attribution.credit.none" />
      </p>
    );
  }
  const finance = report.finance === 'available';
  return (
    <TableScroll label={intl.formatMessage({ id: `attribution.funnel.by.${group}` })}>
      <table className="c-table">
        <thead>
          <tr>
            <th scope="col">
              <FormattedMessage id={`attribution.group.${group}`} />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="attribution.funnel.pageViews" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="attribution.column.leads" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="attribution.column.revenue" />
            </th>
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row) => (
            <tr key={`${row.recipient}:${row.group_ref ?? ''}`}>
              <th scope="row">
                <GroupName recipient={row.recipient} groupRef={row.group_ref} registered={row.registered} group={group} />
              </th>
              <td className="is-num">
                {row.visits.state === 'available' && row.visits.count !== null ? (
                  <span className="u-num">{intl.formatNumber(row.visits.count)}</span>
                ) : (
                  <NoValue>{intl.formatMessage({ id: 'attribution.funnel.notMeasured' })}</NoValue>
                )}
              </td>
              <td className="is-num">{row.leads ? <span className="u-num">{shareText(intl.locale, row.leads.credited_leads)}</span> : <NoValue>{intl.formatMessage({ id: 'attribution.none' })}</NoValue>}</td>
              <td className="is-num">
                {!finance || row.sales?.state === 'permission_unavailable' ? (
                  <NeedsFinance />
                ) : (
                  <Amounts items={(row.sales?.items ?? []).map((item) => ({ currency: item.currency, exponent: item.exponent, amount: item.credited_revenue }))} />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
