import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { FormattedDate, FormattedMessage, useIntl } from 'react-intl';

import { diagnosticsQuery } from '@/api/tracking';
import { useClient } from '@/app/tenant';
import { Icon } from '@/components/Icon';
import { ListNone, QueryStates } from '@/components/ListStates';
import { dayFormat } from '@/components/Time';
import { cx } from '@/lib/cx';

import { channelMessage, lastDays, outcomeMessage, reasonMessage, summarize } from './rules';

const periods = [7, 30] as const;
type Period = (typeof periods)[number];

/** A word for a code of the API, or the code itself when the interface has no word for it yet. */
function Word({ message, code }: { message: ReturnType<typeof reasonMessage>; code: string }) {
  return message ? <FormattedMessage id={message} /> : <span className="u-mono u-ltr">{code}</span>;
}

/**
 * What the collector did with what arrived, day by day: kept, refused, held back for lack of
 * consent, or trimmed. The counters name no visitor and hold no content (specification 004).
 */
export function DiagnosticsCard() {
  const intl = useIntl();
  const { agencyId, clientId } = useClient();
  const [period, setPeriod] = useState<Period>(7);
  const range = lastDays(period, Date.now());
  const counters = useQuery(diagnosticsQuery(agencyId, clientId, range.start, range.end));
  const rows = [...(counters.data ?? [])].sort((first, second) => second.day.localeCompare(first.day) || second.count - first.count);
  const total = summarize(rows);

  const figures = [
    { key: 'kept', value: total.kept },
    { key: 'refused', value: total.refused },
    { key: 'withoutConsent', value: total.withoutConsent },
    { key: 'trimmed', value: total.trimmed },
  ] as const;

  return (
    <section className="c-card" aria-labelledby="diagnostics-title">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title" id="diagnostics-title">
            <FormattedMessage id="tracking.diagnostics.title" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id="tracking.diagnostics.lead" />
          </p>
        </div>
        <div className="c-seg" role="group" aria-label={intl.formatMessage({ id: 'tracking.diagnostics.period' })}>
          {periods.map((option) => (
            <button key={option} type="button" className={cx('c-seg__item', period === option && 'is-active')} aria-pressed={period === option} onClick={() => setPeriod(option)}>
              <FormattedMessage id="keys.lifetime.days" values={{ days: option }} />
            </button>
          ))}
        </div>
      </div>
      <div className="c-card__body c-card__body--flush">
        <QueryStates query={counters} />
        {counters.isSuccess ? (
          <dl className="a-figures">
            {figures.map((figure) => (
              <div key={figure.key} className="a-figures__item">
                <dt>
                  <FormattedMessage id={`tracking.diagnostics.${figure.key}`} />
                </dt>
                <dd className="u-num">{intl.formatNumber(figure.value)}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {counters.isSuccess && rows.length === 0 ? (
          <ListNone>
            <FormattedMessage id="tracking.diagnostics.none" />
          </ListNone>
        ) : null}
        {rows.length > 0 ? (
          <div className="c-table-wrap">
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="tracking.diagnostics.day" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="tracking.diagnostics.channel" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="tracking.diagnostics.outcome" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="tracking.diagnostics.reason" />
                  </th>
                  <th scope="col" className="is-num">
                    <FormattedMessage id="tracking.diagnostics.count" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.day}-${row.channel}-${row.outcome}-${row.reason}`}>
                    <td className="a-nowrap">
                      {/* A counter's day is a UTC day, as the API keeps it. */}
                      <FormattedDate value={`${row.day}T00:00:00Z`} {...dayFormat} timeZone="UTC" />
                    </td>
                    <td>
                      <Word message={channelMessage(row.channel)} code={row.channel} />
                    </td>
                    <td>
                      <Word message={outcomeMessage(row.outcome)} code={row.outcome} />
                    </td>
                    <td>
                      <Word message={reasonMessage(row.reason)} code={row.reason} />
                    </td>
                    <td className="is-num u-num">{intl.formatNumber(row.count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
      <div className="c-card__footer">
        <Icon name="lock" size="sm" />
        <FormattedMessage id="tracking.diagnostics.footer" />
      </div>
    </section>
  );
}
