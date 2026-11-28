import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { changeSchedule, deleteSchedule, leaveSchedule, schedulesKey, schedulesQuery, type ReportSchedule } from '@/api/reportDelivery';
import type { ReportFamily } from '@/api/reports';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EmptyState } from '@/components/EmptyState';
import { Icon } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice } from '@/components/Notice';
import { RowMenu } from '@/components/RowMenu';
import { TableScroll } from '@/components/TableScroll';
import { Moment } from '@/components/Time';
import type { MessageId } from '@/i18n';

import { reportNameId } from './describe';
import { cadencePeriods, cadences, pauseReasons, runError, SCHEDULE_LIMIT } from './rules';

export const scheduleErrors = {
  schedule_limit_reached: 'reports.schedule.error.schedule_limit_reached',
  source_unavailable: 'reports.schedule.error.source_unavailable',
} as const satisfies Record<string, MessageId>;

/** The words of when a schedule runs: every day, every given weekday, or on the 1st, at an hour. */
export function useScheduleTime(): (schedule: Pick<ReportSchedule, 'cadence' | 'weekday' | 'hour'>) => string {
  const intl = useIntl();
  return ({ cadence, weekday, hour }) => {
    const time = `${String(hour).padStart(2, '0')}:00`;
    if (cadence === 'weekly' && weekday) {
      // 1 January 2024 was a Monday, ISO weekday 1.
      const day = intl.formatDate(new Date(Date.UTC(2024, 0, weekday)), { weekday: 'long', timeZone: 'UTC' });
      return intl.formatMessage({ id: 'reports.when.weekly' }, { day, time });
    }
    return intl.formatMessage({ id: cadence === 'monthly' ? 'reports.when.monthly' : 'reports.when.daily' }, { time });
  };
}

/** Scheduled reports of the client (E04): their timing, next and last run, state and recipients. */
export function SchedulesTab({ onEdit }: { onEdit: (schedule: ReportSchedule) => void }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const schedules = useQuery(schedulesQuery(agencyId, clientId));
  const when = useScheduleTime();
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const [deleting, setDeleting] = useState<ReportSchedule | null>(null);
  const [leaving, setLeaving] = useState<ReportSchedule | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: schedulesKey(agencyId, clientId) });

  const status = useMutation({
    mutationFn: ({ schedule, next }: { schedule: ReportSchedule; next: 'active' | 'paused' }) => changeSchedule(agencyId, clientId, schedule.id, { status: next }),
    onMutate: () => setProblem(null),
    onSuccess: () => refresh(),
    onError: (error) => setProblem(describeError(error, scheduleErrors)),
  });

  const items = schedules.data;
  if (!items) return <QueryStates query={schedules} />;
  const active = items.filter((schedule) => schedule.status === 'active').length;

  return (
    <>
    <article className="c-card">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title">
            <FormattedMessage id="reports.schedules.title" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id={manager ? 'reports.schedules.active' : 'reports.schedules.received'} values={{ active, limit: SCHEDULE_LIMIT }} />
          </p>
        </div>
      </div>
      <ErrorNotice message={problem} />
      {items.length === 0 ? (
        <div className="c-card__body">
          <EmptyState icon="calendar-clock" title={<FormattedMessage id={manager ? 'reports.schedules.empty' : 'reports.schedules.emptyReceived'} />} level={3}>
            <FormattedMessage id={manager ? 'reports.schedules.emptyText' : 'reports.schedules.emptyReceivedText'} />
          </EmptyState>
        </div>
      ) : (
        <div className="c-card__body c-card__body--flush">
          <TableScroll label={intl.formatMessage({ id: 'reports.schedules.title' })}>
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="reports.schedules.name" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="reports.schedules.when" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="reports.schedules.next" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="reports.schedules.last" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="analyze.state" />
                  </th>
                  {manager ? (
                    <th scope="col" className="is-num">
                      <FormattedMessage id="reports.schedules.recipients" />
                    </th>
                  ) : null}
                  <th scope="col">
                    <span className="u-sr">
                      <FormattedMessage id="reports.actions" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((schedule) => {
                  const { family, ...parameters } = schedule.report as { family: ReportFamily } & Record<string, unknown>;
                  const run = schedule.last_run;
                  return (
                    <tr key={schedule.id}>
                      <th scope="row">
                        <span className="c-table__primary">{schedule.name}</span>
                        <span className="c-table__sub">
                          <FormattedMessage id={reportNameId(family, parameters)} />
                          {schedule.sale_values ? (
                            <>
                              {' '}
                              <Icon name="lock" size="xs" /> <FormattedMessage id="reports.export.financial" />
                            </>
                          ) : null}
                        </span>
                      </th>
                      <td>
                        {when(schedule)}
                        <span className="c-table__sub">{schedule.time_zone}</span>
                      </td>
                      <td>{schedule.status === 'active' && schedule.next_run_at ? <Moment value={schedule.next_run_at} /> : '—'}</td>
                      <td>
                        {run.at ? (
                          <>
                            <Moment value={run.at} />
                            <span className="c-table__sub">
                              {run.outcome === 'failed' ? (
                                <FormattedMessage id={runError(run.error_code)} />
                              ) : (
                                <FormattedMessage id={run.skipped > 0 ? 'reports.run.builtSkipped' : 'reports.run.built'} values={{ notified: run.notified, skipped: run.skipped }} />
                              )}
                            </span>
                          </>
                        ) : (
                          <span className="u-secondary">
                            <FormattedMessage id="reports.run.none" />
                          </span>
                        )}
                      </td>
                      <td>
                        {schedule.status === 'active' ? (
                          <Badge tone="success" icon="circle-check">
                            <FormattedMessage id="reports.schedule.active" />
                          </Badge>
                        ) : (
                          <>
                            <Badge tone="warning" icon="circle-pause">
                              <FormattedMessage id="reports.schedule.paused" />
                            </Badge>
                            {schedule.pause_reason ? (
                              <span className="c-table__sub">
                                <FormattedMessage id={pauseReasons[schedule.pause_reason]} />
                              </span>
                            ) : null}
                          </>
                        )}
                      </td>
                      {manager ? <td className="is-num u-num">{intl.formatNumber(schedule.recipients?.length ?? 0)}</td> : null}
                      <td className="is-num">
                        {manager ? (
                          <RowMenu
                            label={intl.formatMessage({ id: 'reports.schedules.actions' }, { schedule: schedule.name })}
                            actions={[
                              { id: 'edit', text: intl.formatMessage({ id: 'reports.schedule.edit' }), label: <FormattedMessage id="reports.schedule.edit" />, onAction: () => onEdit(schedule) },
                              schedule.status === 'active'
                                ? {
                                    id: 'pause',
                                    text: intl.formatMessage({ id: 'reports.schedule.pause' }),
                                    label: <FormattedMessage id="reports.schedule.pause" />,
                                    onAction: () => status.mutate({ schedule, next: 'paused' }),
                                  }
                                : {
                                    id: 'resume',
                                    text: intl.formatMessage({ id: 'reports.schedule.resume' }),
                                    label: <FormattedMessage id="reports.schedule.resume" />,
                                    onAction: () => status.mutate({ schedule, next: 'active' }),
                                  },
                              ...(schedule.receiving
                                ? [{ id: 'leave', text: intl.formatMessage({ id: 'reports.leave.action' }), label: <FormattedMessage id="reports.leave.action" />, onAction: () => setLeaving(schedule) }]
                                : []),
                              {
                                id: 'delete',
                                text: intl.formatMessage({ id: 'reports.schedule.delete' }),
                                label: <FormattedMessage id="reports.schedule.delete" />,
                                danger: true,
                                onAction: () => setDeleting(schedule),
                              },
                            ]}
                          />
                        ) : schedule.receiving ? (
                          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setLeaving(schedule)}>
                            <FormattedMessage id="reports.leave.action" />
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableScroll>
        </div>
      )}
      <div className="c-card__footer">
        <Icon name="mail" size="sm" />
        <FormattedMessage id="reports.schedules.footer" />
      </div>
      {deleting ? (
        <ConfirmDialog
          title="reports.schedule.deleteTitle"
          values={{ schedule: deleting.name }}
          text="reports.schedule.deleteText"
          submit="reports.schedule.delete"
          keep="reports.schedule.keep"
          danger
          onConfirm={async () => {
            await deleteSchedule(agencyId, clientId, deleting.id);
            await refresh();
            setDeleting(null);
          }}
          onClose={() => setDeleting(null)}
        />
      ) : null}
      {leaving ? (
        <ConfirmDialog
          title="reports.leave.title"
          values={{ schedule: leaving.name }}
          text="reports.leave.text"
          submit="reports.leave.action"
          keep="reports.schedule.keep"
          onConfirm={async () => {
            await leaveSchedule(agencyId, clientId, leaving.id);
            await refresh();
            setLeaving(null);
          }}
          onClose={() => setLeaving(null)}
        />
      ) : null}
    </article>
    {/* What each cadence reports (E04, D8 of 016-C). */}
    <article className="c-card">
      <div className="c-card__header">
        <h2 className="c-card__title">
          <FormattedMessage id="reports.schedules.runTitle" />
        </h2>
      </div>
      <div className="c-card__body">
        <dl className="c-dl c-dl--split">
          {cadences.map((cadence) => (
            <div key={cadence} className="a-contents">
              <dt>
                <FormattedMessage id={`reports.cadence.${cadence}`} />
              </dt>
              <dd>
                <FormattedMessage id={cadencePeriods[cadence]} />
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="c-card__footer">
        <Icon name="info" size="sm" />
        <FormattedMessage id="reports.schedules.runNote" />
      </div>
    </article>
    </>
  );
}
