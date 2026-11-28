import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, isApiError, type ErrorMessage } from '@/api/errors';
import { downloadExport, exportsKey, exportsQuery, revokeExport, schedulesQuery, type ReportExport } from '@/api/reportDelivery';
import type { ReportFamily } from '@/api/reports';
import { membersQuery } from '@/api/team';
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
import { saveFile } from '@/features/analyze/shared';
import type { MessageId } from '@/i18n';

import { reportNameId, usePeriodText } from './describe';
import { daysLeft, EXPORT_LIMIT, exportGone, keptExports } from './rules';

export const downloadErrors = { export_gone: 'reports.error.export_gone' } as const satisfies Record<string, MessageId>;
export const revokeErrors = { access_denied: 'reports.revoke.error.access_denied' } as const satisfies Record<string, MessageId>;

/** The words of an export's report: its kind, then its days and choices. */
export function ExportReport({ item }: { item: ReportExport }) {
  const period = usePeriodText();
  return (
    <>
      <span className="c-table__primary">
        <FormattedMessage id={reportNameId(item.family as ReportFamily, item.parameters)} />
      </span>
      <span className="c-table__sub">
        <FormattedMessage
          id={item.parameters.compare ? 'reports.export.periodCompared' : 'reports.export.period'}
          values={{ period: period(item.period.start, item.period.end) }}
        />
        {item.includes_financials ? (
          <>
            {' '}
            <Icon name="lock" size="xs" /> <FormattedMessage id="reports.export.financial" />
          </>
        ) : null}
      </span>
    </>
  );
}

/** Retained exports of the client (E03): newest first, with their state, expiry, size and downloads. */
export function ExportsTab() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { agencyId, clientId, manager } = useClient();
  const exports = useQuery(exportsQuery(agencyId, clientId));
  // Names of members are listed to owners and admins only (002); others see the source without a name.
  const members = useQuery({ ...membersQuery(agencyId), enabled: manager });
  const schedules = useQuery(schedulesQuery(agencyId, clientId));
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const [revoking, setRevoking] = useState<ReportExport | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: exportsKey(agencyId, clientId) });

  const download = useMutation({
    mutationFn: async (item: ReportExport) => saveFile(await downloadExport(agencyId, clientId, item.id), `report-${item.family}.csv`),
    onMutate: () => setProblem(null),
    onError: async (error) => {
      setProblem(describeError(error, downloadErrors));
      // A gone export is read again, so the list says why.
      if (isApiError(error) && error.status === 410) await refresh();
    },
  });

  const items = exports.data;
  if (!items) return <QueryStates query={exports} />;
  const nameOf = (membershipId: string) => members.data?.find((member) => member.id === membershipId)?.display_name ?? null;
  const scheduleName = (scheduleId: string | null) => schedules.data?.find((schedule) => schedule.id === scheduleId)?.name ?? null;

  return (
    <>
    <article className="c-card">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title">
            <FormattedMessage id="reports.exports.title" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id="reports.exports.kept" values={{ kept: keptExports(items), limit: EXPORT_LIMIT }} />
          </p>
        </div>
      </div>
      <ErrorNotice message={problem} />
      {items.length === 0 ? (
        <div className="c-card__body">
          <EmptyState icon="file-chart-column" title={<FormattedMessage id="reports.exports.empty" />} level={3}>
            <FormattedMessage id="reports.exports.emptyText" />
          </EmptyState>
        </div>
      ) : (
        <div className="c-card__body c-card__body--flush">
          <TableScroll label={intl.formatMessage({ id: 'reports.exports.title' })}>
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="reports.detail.report" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="reports.exports.made" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="analyze.state" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="reports.detail.keptUntil" />
                  </th>
                  <th scope="col" className="is-num">
                    <FormattedMessage id="reports.detail.size" />
                  </th>
                  <th scope="col" className="is-num">
                    <FormattedMessage id="reports.detail.downloads" />
                  </th>
                  <th scope="col">
                    <span className="u-sr">
                      <FormattedMessage id="reports.actions" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const gone = exportGone(item);
                  const label = intl.formatMessage({ id: reportNameId(item.family as ReportFamily, item.parameters) });
                  const by = item.source === 'schedule' ? scheduleName(item.schedule_id) : nameOf(item.requested_by_membership_id);
                  return (
                    <tr key={item.id}>
                      <th scope="row">
                        <ExportReport item={item} />
                      </th>
                      <td>
                        <Moment value={item.created_at} />
                        <span className="c-table__sub">
                          {item.source === 'schedule' ? (
                            by ? (
                              <FormattedMessage id="reports.exports.bySchedule" values={{ schedule: by }} />
                            ) : (
                              <FormattedMessage id="reports.exports.byAnySchedule" />
                            )
                          ) : by ? (
                            <FormattedMessage id="reports.exports.byPerson" values={{ name: by }} />
                          ) : (
                            <FormattedMessage id="reports.exports.byHand" />
                          )}
                        </span>
                      </td>
                      <td>
                        {gone === null ? (
                          <Badge tone="success" icon="circle-check">
                            <FormattedMessage id="reports.state.ready" />
                          </Badge>
                        ) : gone === 'expired' ? (
                          <Badge tone="plain" icon="hourglass">
                            <FormattedMessage id="reports.state.expired" />
                          </Badge>
                        ) : (
                          <>
                            <Badge tone="warning" icon="ban">
                              <FormattedMessage id="reports.state.revoked" />
                            </Badge>
                            <span className="c-table__sub">
                              <FormattedMessage id={`reports.reason.${gone}`} />
                            </span>
                          </>
                        )}
                      </td>
                      <td>
                        {gone === null || gone === 'expired' ? <Moment value={item.expires_at} /> : '—'}
                        <span className="c-table__sub">
                          {gone === null ? (
                            <FormattedMessage id="reports.exports.daysLeft" values={{ days: daysLeft(item.expires_at) }} />
                          ) : gone === 'expired' ? (
                            <FormattedMessage id="reports.exports.deleted" />
                          ) : item.revoked_at ? (
                            <FormattedMessage id="reports.exports.removedOn" values={{ day: intl.formatDate(new Date(item.revoked_at), { day: 'numeric', month: 'short' }) }} />
                          ) : null}
                        </span>
                      </td>
                      <td className="is-num">
                        {gone === null && item.byte_size !== null ? (
                          <>
                            <FormattedMessage id="reports.detail.kib" values={{ kib: Math.max(1, Math.ceil(item.byte_size / 1024)) }} />
                            <span className="c-table__sub">
                              <FormattedMessage id="reports.detail.rows" values={{ rows: item.row_count ?? 0 }} />
                            </span>
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="is-num">
                        <span className="u-num">{intl.formatNumber(item.download_count)}</span>
                        {item.last_downloaded_at ? (
                          <span className="c-table__sub">
                            <FormattedMessage
                              id="reports.exports.lastDownload"
                              values={{ day: intl.formatDate(new Date(item.last_downloaded_at), { day: 'numeric', month: 'short' }) }}
                            />
                          </span>
                        ) : null}
                      </td>
                      <td className="is-num">
                        <span className="l-cluster a-row-actions">
                          {gone === null ? (
                            <button
                              type="button"
                              className="c-btn c-btn--ghost c-btn--sm c-btn--icon"
                              aria-label={intl.formatMessage({ id: 'reports.exports.download' }, { report: label })}
                              disabled={download.isPending}
                              onClick={() => download.mutate(item)}
                            >
                              <Icon name="download" size="sm" />
                            </button>
                          ) : null}
                          <RowMenu
                            label={intl.formatMessage({ id: 'reports.exports.actions' }, { report: label })}
                            actions={[
                              {
                                id: 'open',
                                text: intl.formatMessage({ id: 'reports.exports.open' }),
                                label: <FormattedMessage id="reports.exports.open" />,
                                onAction: () =>
                                  void navigate({
                                    to: '/agencies/$agencyId/clients/$clientId/reports/exports/$exportId',
                                    params: { agencyId, clientId, exportId: item.id },
                                  }),
                              },
                              ...(gone === null
                                ? [
                                    {
                                      id: 'revoke',
                                      text: intl.formatMessage({ id: 'reports.revoke.action' }),
                                      label: <FormattedMessage id="reports.revoke.action" />,
                                      danger: true,
                                      onAction: () => setRevoking(item),
                                    },
                                  ]
                                : []),
                            ]}
                          />
                        </span>
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
        <Icon name="lock" size="sm" />
        <FormattedMessage id="reports.exports.footer" />
      </div>
      {revoking ? (
        <ConfirmDialog
          title="reports.revoke.title"
          text="reports.revoke.text"
          submit="reports.revoke.submit"
          keep="reports.revoke.keep"
          danger
          errors={revokeErrors}
          onConfirm={async () => {
            await revokeExport(agencyId, clientId, revoking.id);
            await refresh();
            setRevoking(null);
          }}
          onClose={() => setRevoking(null)}
        />
      ) : null}
    </article>
    {/* Who sees an export, and where one comes from (E03). */}
    <div className="l-grid l-grid--2">
      <article className="c-card">
        <div className="c-card__header">
          <h2 className="c-card__title">
            <FormattedMessage id="reports.exports.whoTitle" />
          </h2>
        </div>
        <div className="c-card__body l-stack">
          <p>
            <FormattedMessage id="reports.exports.who1" />
          </p>
          <p>
            <FormattedMessage id="reports.exports.who2" />
          </p>
          <p className="u-secondary">
            <FormattedMessage id="reports.exports.who3" />
          </p>
        </div>
      </article>
      <article className="c-card">
        <div className="c-card__header">
          <h2 className="c-card__title">
            <FormattedMessage id="reports.exports.savingTitle" />
          </h2>
        </div>
        <div className="c-card__body l-stack">
          <p>
            <FormattedMessage id="reports.exports.saving1" />
          </p>
          <p className="u-secondary">
            <FormattedMessage id="reports.exports.saving2" />
          </p>
        </div>
      </article>
    </div>
    </>
  );
}
