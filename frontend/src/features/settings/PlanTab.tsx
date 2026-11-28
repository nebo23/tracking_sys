import { useQuery } from '@tanstack/react-query';
import { FormattedMessage, useIntl } from 'react-intl';

import { planQuery, type PlanLimitUse } from '@/api/agencySettings';
import { Badge } from '@/components/Badge';
import { QueryStates } from '@/components/ListStates';
import { TableScroll } from '@/components/TableScroll';
import { dayFormat } from '@/components/Time';
import { cx } from '@/lib/cx';

/** The words and the look of a limit's state: within the plan, at its limit, or without a limit. */
export function limitState(state: PlanLimitUse['state'] | 'over_allowance'): { tone: 'success' | 'warning' | 'neutral'; icon: 'circle-check' | 'triangle-alert' | 'minus'; label: string } {
  if (state === 'at_limit') return { tone: 'warning', icon: 'triangle-alert', label: 'settings.plan.state.at_limit' };
  if (state === 'over_allowance') return { tone: 'warning', icon: 'triangle-alert', label: 'settings.plan.state.over_allowance' };
  if (state === 'unlimited') return { tone: 'neutral', icon: 'minus', label: 'settings.plan.state.unlimited' };
  return { tone: 'success', icon: 'circle-check', label: 'settings.plan.state.within' };
}

/** How much of a limit is in use, as the meter of the design (B13); nothing for a limit that has no value. */
function Share({ used, value, warning }: { used: number; value: number | null; warning: boolean }) {
  const intl = useIntl();
  if (value === null || value <= 0) return null;
  const share = Math.min(100, Math.round((used / value) * 100));
  return (
    <span className={cx('c-meter', warning && 'c-meter--warning')} role="img" aria-label={intl.formatNumber(share / 100, { style: 'percent' })}>
      <span className="c-meter__fill" style={{ inlineSize: `${share}%` }} />
    </span>
  );
}

/** Plan and usage (B13): the plan, each limit with its use, and the month's tracked events (017-A). */
export function PlanTab({ agencyId }: { agencyId: string }) {
  const intl = useIntl();
  const plan = useQuery(planQuery(agencyId));
  const data = plan.data;
  if (!data) return <QueryStates query={plan} />;
  const events = data.tracked_events;
  const month = intl.formatDate(new Date(events.period_start), { month: 'long', timeZone: 'UTC' });
  const eventsState = limitState(events.state);
  return (
    <>
      <article className="c-card">
        <div className="c-card__header">
          <div>
            <h2 className="c-card__title">
              <FormattedMessage id="settings.plan.title" values={{ plan: data.plan.name }} />
            </h2>
            <p className="c-card__subtitle">
              <FormattedMessage
                id="settings.plan.asOf"
                values={{ when: intl.formatDate(new Date(data.as_of), { ...dayFormat, hour: 'numeric', minute: '2-digit' }) }}
              />
            </p>
          </div>
        </div>
        <div className="c-card__body c-card__body--flush">
          <TableScroll label={intl.formatMessage({ id: 'settings.plan.limits' })}>
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="settings.plan.limit" />
                  </th>
                  <th scope="col" className="is-num">
                    <FormattedMessage id="settings.plan.used" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="settings.plan.share" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="analyze.state" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.limits.map((limit) => {
                  const state = limitState(limit.state);
                  return (
                    <tr key={limit.limit}>
                      <th scope="row">
                        <span className="c-table__primary">
                          <FormattedMessage id={`settings.plan.limit.${limit.limit}`} />
                        </span>
                        <span className="c-table__sub">
                          <FormattedMessage id={`settings.plan.limit.${limit.limit}.lead`} />
                        </span>
                      </th>
                      <td className="is-num u-num">
                        {limit.value === null ? (
                          <FormattedMessage id="settings.plan.usedUnlimited" values={{ used: limit.used }} />
                        ) : (
                          <FormattedMessage id="settings.plan.usedOf" values={{ used: limit.used, value: limit.value }} />
                        )}
                      </td>
                      <td>
                        <Share used={limit.used} value={limit.value} warning={limit.state === 'at_limit'} />
                      </td>
                      <td>
                        <Badge tone={state.tone} icon={state.icon}>
                          <FormattedMessage id={state.label as never} />
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableScroll>
        </div>
      </article>
      <article className="c-card c-stat">
        <p className="c-stat__label">
          <FormattedMessage id="settings.plan.events" values={{ month }} />{' '}
          <Badge tone={eventsState.tone} icon={eventsState.icon}>
            <FormattedMessage id={eventsState.label as never} />
          </Badge>
        </p>
        <div className="c-stat__value u-num">
          {events.count_capped ? (
            <FormattedMessage id="settings.plan.eventsCapped" values={{ count: events.count }} />
          ) : (
            intl.formatNumber(events.count)
          )}
          {events.allowance !== null ? (
            <span className="u-secondary">
              {' '}
              <FormattedMessage id="settings.plan.eventsOf" values={{ allowance: events.allowance }} />
            </span>
          ) : null}
        </div>
        <Share used={events.count} value={events.allowance} warning={events.state === 'over_allowance'} />
        <p className="c-stat__meta">
          <FormattedMessage id="settings.plan.eventsLead" />
        </p>
      </article>
      <p className="u-secondary">
        <FormattedMessage id="settings.plan.change" />
      </p>
    </>
  );
}
