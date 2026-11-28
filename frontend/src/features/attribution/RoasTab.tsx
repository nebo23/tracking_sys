import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { FormattedMessage, useIntl } from 'react-intl';

import { isApiError } from '@/api/errors';
import { roasReportQuery, spendNamesQuery, type ModelVersion, type ReportScope, type RoasReport, type RoasRow, type SpendLevel } from '@/api/reports';
import { InlineSelect } from '@/components/Choice';
import { EmptyState } from '@/components/EmptyState';
import { QueryStates } from '@/components/ListStates';
import { Notice } from '@/components/Notice';
import { TableScroll } from '@/components/TableScroll';

import { Card, NoValue, ProvisionalBadge } from '../analyze/parts';
import { FinanceNotice, accountName, chosenConnection, financeRefused, money, numeral, useSpendConnections } from '../analyze/shared';
import { FreshnessNotice } from './parts';
import { roasReason, shareText } from './states';

const levels: SpendLevel[] = ['campaign', 'adset', 'ad'];

interface RoasTabProps {
  scope: ReportScope;
  version: ModelVersion | undefined;
  connection: string | undefined;
  level: SpendLevel;
  onChange: (next: { connection?: string; level?: SpendLevel }) => void;
}

/**
 * Return on ad spend (C10): what one ad account spent, the revenue and leads credited to its
 * campaigns, ad sets or ads under the chosen model, and the credit that matched none of them.
 */
export function RoasTab({ scope, version, connection: chosen, level, onChange }: RoasTabProps) {
  const intl = useIntl();
  const connections = useSpendConnections(scope.agencyId, scope.clientId);
  const connection = chosenConnection(connections.data, chosen);
  const report = useQuery({
    ...roasReportQuery(scope, connection?.id ?? '', level, version?.id),
    enabled: connection !== undefined && version !== undefined,
    retry: false,
  });
  const names = useQuery({ ...spendNamesQuery(scope, connection?.id ?? '', level), enabled: connection !== undefined && report.isSuccess });
  const data = report.data;
  const refused = report.isError && financeRefused(report.error);
  const zoneUnknown = report.isError && isApiError(report.error) && report.error.code === 'day_zone_unknown';

  if (connections.data && !connection) {
    return (
      <EmptyState
        icon="megaphone"
        title={<FormattedMessage id="analyze.spend.none.title" />}
        action={
          <Link className="c-btn c-btn--primary" to="/agencies/$agencyId/clients/$clientId/connections" params={{ agencyId: scope.agencyId, clientId: scope.clientId }}>
            <FormattedMessage id="analyze.social.none.action" />
          </Link>
        }
      >
        <FormattedMessage id="analyze.spend.none.text" />
      </EmptyState>
    );
  }

  return (
    <>
      <div className="l-cluster">
        {connections.data && connections.data.length > 1 && connection ? (
          <InlineSelect
            label={intl.formatMessage({ id: 'analyze.account' })}
            value={connection.id}
            onChange={(id) => onChange({ connection: id })}
            options={connections.data.map((item) => ({ value: item.id, label: accountName(item, intl) }))}
          />
        ) : null}
        <InlineSelect<SpendLevel>
          label={intl.formatMessage({ id: 'analyze.spend.level' })}
          value={level}
          onChange={(next) => onChange({ level: next })}
          options={levels.map((item) => ({ value: item, label: intl.formatMessage({ id: `analyze.spend.level.${item}` }) }))}
        />
      </div>
      {refused ? <FinanceNotice /> : null}
      {zoneUnknown ? (
        <Notice tone="info">
          <FormattedMessage id="attribution.roas.zoneUnknown" />
        </Notice>
      ) : null}
      {!refused && !zoneUnknown ? <QueryStates query={report} /> : null}
      {data && connection ? (
        <>
          <FreshnessNotice report={data} />
          <RoasFigures report={data} />
          <Card
            title={<FormattedMessage id={`analyze.spend.rows.${level}`} />}
            subtitle={<FormattedMessage id="attribution.roas.lead" />}
            footer={<FormattedMessage id="attribution.roas.footer" values={{ zone: data.day_zone }} />}
            flush
          >
            <RoasTable rows={data.rows} names={names.data} label={intl.formatMessage({ id: `analyze.spend.rows.${level}` })} />
          </Card>
          <UnmatchedCard report={data} />
        </>
      ) : null}
    </>
  );
}

/** The return or the cost per lead, or why it is not worked out. */
function Ratio({ value, reason, currency, exponent }: { value: RoasRow['roas']; reason: string | null; currency?: string | null; exponent?: number | null }) {
  const intl = useIntl();
  if (!value) return <NoValue>{intl.formatMessage({ id: roasReason(reason) })}</NoValue>;
  if (currency && exponent !== null && exponent !== undefined) return <span className="u-num">{money(intl, { minor: 0, decimal: value.decimal }, currency, exponent)}</span>;
  return numeral(shareText(intl.locale, value));
}

function RoasFigures({ report }: { report: RoasReport }) {
  const intl = useIntl();
  const account = report.totals.filter((total) => total.period === 'current' && total.level === 'account');
  if (account.length === 0) {
    return (
      <p className="u-secondary">
        <FormattedMessage id="analyze.reason.no_spend_facts" />
      </p>
    );
  }
  return (
    <section className="l-grid l-grid--4" aria-label={intl.formatMessage({ id: 'attribution.roas.figures' })}>
      {account.map((total) => (
        <article key={`${total.currency ?? 'none'}`} className="c-card c-stat">
          <p className="c-stat__label">
            <FormattedMessage id="analyze.spend.spent" /> {total.spend_state === 'provisional' ? <ProvisionalBadge /> : null}
          </p>
          <div className="c-stat__value u-num">{total.spend && total.currency ? money(intl, total.spend, total.currency, total.exponent ?? 2) : '-'}</div>
          <p className="c-stat__row">
            <FormattedMessage id="attribution.roas.credited" />{' '}
            <span className="u-num">{total.credited_revenue && total.currency ? money(intl, total.credited_revenue, total.currency, total.exponent ?? 2) : <NoValue>{intl.formatMessage({ id: 'analyze.finance.short' })}</NoValue>}</span>
          </p>
          <p className="c-stat__row">
            <FormattedMessage id="attribution.roas.return" />{' '}
            <span className="u-num">
              <Ratio value={total.roas} reason={total.roas_reason} />
            </span>
          </p>
          <p className="c-stat__meta">
            <FormattedMessage id="attribution.roas.costPerLead" />{' '}
            <Ratio value={total.cost_per_lead} reason={total.cost_per_lead_reason} currency={total.currency} exponent={total.exponent} />
          </p>
        </article>
      ))}
    </section>
  );
}

function RoasTable({ rows, names, label }: { rows: RoasRow[]; names: ReadonlyMap<string, string> | undefined; label: string }) {
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
              <FormattedMessage id="attribution.roas.credited" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="attribution.roas.return" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="attribution.column.leads" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="attribution.roas.costPerLead" />
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const name = names?.get(row.object_id);
            return (
              <tr key={`${row.object_id}:${row.currency ?? ''}`}>
                <th scope="row">
                  <span className="c-table__primary">{name ?? <FormattedMessage id="analyze.spend.unnamed" />}</span>
                  <span className="c-table__sub u-ltr">{row.object_id}</span>
                </th>
                <td className="is-num">
                  <span className="u-num">{row.spend && row.currency ? money(intl, row.spend, row.currency, row.exponent ?? 2) : '-'}</span>{' '}
                  {row.spend_state === 'provisional' ? <ProvisionalBadge /> : null}
                  {row.spend_state === 'incomplete' ? <NoValue>{intl.formatMessage({ id: 'attribution.roas.incomplete' })}</NoValue> : null}
                </td>
                <td className="is-num">
                  {row.credited_revenue && row.currency ? <span className="u-num">{money(intl, row.credited_revenue, row.currency, row.exponent ?? 2)}</span> : <NoValue>{intl.formatMessage({ id: 'attribution.none' })}</NoValue>}
                </td>
                <td className="is-num">
                  <Ratio value={row.roas} reason={row.roas_reason} />
                </td>
                <td className="is-num">{numeral(shareText(intl.locale, row.credited_leads)) ?? <NoValue>{intl.formatMessage({ id: 'attribution.none' })}</NoValue>}</td>
                <td className="is-num">
                  <Ratio value={row.cost_per_lead} reason={row.cost_per_lead_reason} currency={row.currency} exponent={row.exponent} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableScroll>
  );
}

/** Credit that went to campaigns this ad account does not have: left out of the return, not hidden. */
function UnmatchedCard({ report }: { report: RoasReport }) {
  const intl = useIntl();
  const revenue = report.unmatched?.filter((item) => item.period === 'current') ?? [];
  const leads = report.unmatched_leads?.find((item) => item.period === 'current');
  return (
    <Card title={<FormattedMessage id="attribution.roas.unmatched" />} subtitle={<FormattedMessage id="attribution.roas.unmatchedLead" />}>
      <dl className="a-figures a-figures--flush">
        <div className="a-figures__item">
          <dt>
            <FormattedMessage id="attribution.roas.credited" />
          </dt>
          <dd className="u-num">
            {report.unmatched === null ? (
              <NoValue>{intl.formatMessage({ id: 'analyze.finance.short' })}</NoValue>
            ) : revenue.length === 0 ? (
              <NoValue>{intl.formatMessage({ id: 'attribution.none' })}</NoValue>
            ) : (
              revenue.map((item) => (
                <span key={item.currency} className="a-stat__line">
                  {money(intl, item.credited_revenue, item.currency, item.exponent)}
                </span>
              ))
            )}
          </dd>
        </div>
        <div className="a-figures__item">
          <dt>
            <FormattedMessage id="attribution.column.leads" />
          </dt>
          <dd className="u-num">{leads ? shareText(intl.locale, leads.credited_leads) : <NoValue>{intl.formatMessage({ id: 'attribution.none' })}</NoValue>}</dd>
        </div>
      </dl>
    </Card>
  );
}
