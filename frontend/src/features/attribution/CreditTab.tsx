import { useQuery } from '@tanstack/react-query';
import { FormattedMessage, useIntl } from 'react-intl';

import { attributionReportQuery, type AttributionReport, type ModelVersion, type ReportScope } from '@/api/reports';
import { InlineSelect } from '@/components/Choice';
import { QueryStates } from '@/components/ListStates';
import { TableScroll } from '@/components/TableScroll';

import { Card, Change, NoValue } from '../analyze/parts';
import { money, percent } from '../analyze/shared';
import { attributionGroups, type AttributionGroupChoice } from '../analyze/search';
import { Amounts, FreshnessNotice, GroupName, NeedsFinance, useModelName } from './parts';
import { attributionReason, shareText } from './states';

interface CreditTabProps {
  scope: ReportScope;
  version: ModelVersion | undefined;
  group: AttributionGroupChoice;
  onGroup: (group: AttributionGroupChoice) => void;
}

const recipients = ['all', 'campaign', 'direct', 'unknown'] as const;

/**
 * Credit (C08): which campaigns, content and links earned credit for leads and verified sales
 * under the chosen model, the three models side by side, and the check against the ledger.
 */
export function CreditTab({ scope, version, group, onGroup }: CreditTabProps) {
  const intl = useIntl();
  const report = useQuery({ ...attributionReportQuery(scope, 'groups', group, version?.id), enabled: version !== undefined, retry: false });
  const models = useQuery({ ...attributionReportQuery({ ...scope, compare: false }, 'models', group), enabled: version !== undefined, retry: false });
  const data = report.data;

  return (
    <>
      <QueryStates query={report} />
      {data ? (
        <>
          <FreshnessNotice report={data} />
          <CreditFigures report={data} />
          <Card
            title={<FormattedMessage id={`attribution.credit.by.${group}`} />}
            subtitle={<FormattedMessage id="attribution.credit.lead" />}
            actions={
              <InlineSelect<AttributionGroupChoice>
                label={intl.formatMessage({ id: 'attribution.group.label' })}
                value={group}
                onChange={onGroup}
                options={attributionGroups.map((item) => ({ value: item, label: intl.formatMessage({ id: `attribution.group.${item}` }) }))}
              />
            }
            footer={<FormattedMessage id="attribution.credit.footer" values={{ zone: data.day_zone }} />}
            flush
          >
            <CreditTable report={data} group={group} />
          </Card>
          {models.data ? <ModelsCard report={models.data} /> : null}
          <ReconciliationCard report={data} />
        </>
      ) : null}
    </>
  );
}

/** The credited revenue of the period: in all, and to campaigns, direct and unknown, per currency. */
function CreditFigures({ report }: { report: AttributionReport }) {
  const intl = useIntl();
  const sales = report.totals?.sales;
  const leads = report.totals?.leads;
  const current = (recipient: string) => sales?.items?.filter((item) => item.period === 'current' && item.recipient === recipient) ?? [];
  const leadsOf = (recipient: string) => leads?.items?.find((item) => item.period === 'current' && item.recipient === recipient);
  const revenueChange = report.comparison?.find((item) => item.metric === 'credited_revenue');
  return (
    <section className="l-grid l-grid--4" aria-label={intl.formatMessage({ id: 'attribution.credit.figures' })}>
      {recipients.map((recipient) => (
        <article key={recipient} className="c-card c-stat">
          <p className="c-stat__label">
            <FormattedMessage id={`attribution.figure.${recipient}`} />
          </p>
          <div className="c-stat__value">
            {sales?.state === 'permission_unavailable' ? (
              <NeedsFinance />
            ) : sales?.state === 'not_ready' ? (
              <NoValue>{intl.formatMessage({ id: attributionReason(sales.reason) })}</NoValue>
            ) : (
              <Amounts items={current(recipient).map((item) => ({ currency: item.currency, exponent: item.exponent, amount: item.credited_revenue }))} />
            )}
          </div>
          {recipient === 'all' && revenueChange ? (
            <Change
              comparable={revenueChange.comparable}
              percent={percent(intl, revenueChange.percent_change)}
              difference={revenueChange.difference && typeof revenueChange.difference === 'object' && 'minor' in revenueChange.difference ? revenueChange.difference.minor : null}
              reason={revenueChange.reason}
            />
          ) : null}
          <p className="c-stat__meta">
            {leadsOf(recipient) ? (
              <FormattedMessage id="attribution.figure.leads" values={{ leads: shareText(intl.locale, leadsOf(recipient)?.credited_leads) }} />
            ) : (
              <FormattedMessage id={`attribution.figure.${recipient}.lead`} />
            )}
          </p>
        </article>
      ))}
    </section>
  );
}

function CreditTable({ report, group }: { report: AttributionReport; group: AttributionGroupChoice }) {
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
    <TableScroll label={intl.formatMessage({ id: `attribution.credit.by.${group}` })}>
      <table className="c-table">
        <thead>
          <tr>
            <th scope="col">
              <FormattedMessage id={`attribution.group.${group}`} />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="attribution.column.leads" />
            </th>
            <th scope="col" className="is-num">
              <FormattedMessage id="attribution.column.sales" />
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
              <td className="is-num">{row.leads ? <span className="u-num">{shareText(intl.locale, row.leads.credited_leads)}</span> : <NoValue>{intl.formatMessage({ id: 'attribution.none' })}</NoValue>}</td>
              <td className="is-num">
                {!finance || row.sales?.state === 'permission_unavailable' ? (
                  <NeedsFinance />
                ) : (
                  (row.sales?.items ?? []).map((item) => (
                    <span key={item.currency} className="a-stat__line u-num">
                      {shareText(intl.locale, item.credited_sales)}
                    </span>
                  ))
                )}
              </td>
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

/** Every active model on its own: values never add across models. */
function ModelsCard({ report }: { report: AttributionReport }) {
  const intl = useIntl();
  const name = useModelName();
  const versions = report.model_versions ?? [];
  const totals = report.model_totals ?? [];
  const finance = report.finance === 'available';
  return (
    <Card title={<FormattedMessage id="attribution.models.title" />} subtitle={<FormattedMessage id="attribution.models.lead" />} flush>
      <TableScroll label={intl.formatMessage({ id: 'attribution.models.title' })}>
        <table className="c-table">
          <thead>
            <tr>
              <th scope="col">
                <FormattedMessage id="attribution.model.label" />
              </th>
              {(['campaign', 'direct', 'unknown'] as const).map((recipient) => (
                <th key={recipient} scope="col" className="is-num">
                  <FormattedMessage id={`attribution.recipient.${recipient}`} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {totals.map((entry) => {
              const version = versions.find((item) => item.id === entry.model_version_id);
              return (
                <tr key={entry.model_version_id}>
                  <th scope="row">
                    <span className="c-table__primary">{version ? name(version) : entry.model_version_id}</span>
                    {version?.is_default ? (
                      <span className="c-table__sub">
                        <FormattedMessage id="attribution.model.default" />
                      </span>
                    ) : null}
                  </th>
                  {(['campaign', 'direct', 'unknown'] as const).map((recipient) => (
                    <td key={recipient} className="is-num">
                      {finance && entry.sales.state === 'available' ? (
                        <Amounts
                          items={(entry.sales.items ?? [])
                            .filter((item) => item.period === 'current' && item.recipient === recipient)
                            .map((item) => ({ currency: item.currency, exponent: item.exponent, amount: item.credited_revenue }))}
                        />
                      ) : (
                        <span className="u-num">
                          {shareText(intl.locale, entry.leads.items?.find((item) => item.period === 'current' && item.recipient === recipient)?.credited_leads)}
                        </span>
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>
    </Card>
  );
}

/** Credited revenue against the verified net of the same sales in the ledger. */
function ReconciliationCard({ report }: { report: AttributionReport }) {
  const intl = useIntl();
  const reconciliation = report.reconciliation;
  if (!reconciliation) return null;
  const items = reconciliation.items?.filter((item) => item.period === 'current') ?? [];
  return (
    <Card title={<FormattedMessage id="attribution.reconciliation.title" />} subtitle={<FormattedMessage id="attribution.reconciliation.lead" />}>
      {reconciliation.state === 'permission_unavailable' ? <NeedsFinance /> : null}
      {reconciliation.state === 'not_ready' || reconciliation.state === 'unavailable' ? (
        <p className="u-secondary">
          <FormattedMessage id={attributionReason(reconciliation.reason)} />
        </p>
      ) : null}
      {items.map((item) => (
        <dl key={item.currency} className="a-figures a-figures--flush">
          <div className="a-figures__item">
            <dt>
              <FormattedMessage id="attribution.reconciliation.credited" />
            </dt>
            <dd className="u-num">{money(intl, item.credited_revenue, item.currency, item.exponent)}</dd>
          </div>
          <div className="a-figures__item">
            <dt>
              <FormattedMessage id="attribution.reconciliation.ledger" />
            </dt>
            <dd className="u-num">{money(intl, item.ledger_net, item.currency, item.exponent)}</dd>
          </div>
          <div className="a-figures__item">
            <dt>
              <FormattedMessage id="attribution.reconciliation.difference" />
            </dt>
            <dd className="u-num">{money(intl, item.difference, item.currency, item.exponent)}</dd>
          </div>
          <div className="a-figures__item">
            <dt>
              <FormattedMessage id="analyze.state" />
            </dt>
            <dd>
              {item.state === 'reconciled' ? (
                <FormattedMessage id="attribution.reconciliation.reconciled" />
              ) : (
                <FormattedMessage id={attributionReason(item.reason)} />
              )}
            </dd>
          </div>
        </dl>
      ))}
    </Card>
  );
}
