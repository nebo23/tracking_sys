import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getRouteApi, Link } from '@tanstack/react-router';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, isApiError, type ErrorMessage } from '@/api/errors';
import { downloadExport, exportQuery, exportsKey, schedulesQuery, type ReportExport } from '@/api/reportDelivery';
import type { ReportFamily } from '@/api/reports';
import { membersQuery } from '@/api/team';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { Icon } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice } from '@/components/Notice';
import { PageHeading, usePageTitle } from '@/components/PageHeading';
import { Moment } from '@/components/Time';
import { saveFile } from '@/features/analyze/shared';

import { previousPeriod, reportNameId, useModelLabel, usePeriodText } from './describe';
import { downloadErrors } from './ExportsTab';
import { daysLeft, exportGone, goneReasons, lastDay } from './rules';

const route = getRouteApi('/workspace/agencies/$agencyId/clients/$clientId/reports/exports/$exportId');

/** The page of the same report today, on the days of the export. */
function OpenReport({ item }: { item: ReportExport }) {
  const { agencyId, clientId } = useClient();
  const params = { agencyId, clientId };
  const days = { from: item.period.start, to: lastDay(item.period.end), compare: item.parameters.compare === true ? true : undefined };
  const label = <FormattedMessage id={`reports.export.openPage.${item.family}`} />;
  const level = typeof item.parameters.level === 'string' ? (item.parameters.level as 'campaign' | 'adset' | 'ad') : undefined;
  const connection = typeof item.parameters.connection_id === 'string' ? item.parameters.connection_id : undefined;
  const className = 'c-btn c-btn--secondary';
  switch (item.family as ReportFamily) {
    case 'social':
      return (
        <Link className={className} to="/agencies/$agencyId/clients/$clientId/content" params={params} search={{ ...days, connection }}>
          {label}
        </Link>
      );
    case 'spend':
      return (
        <Link className={className} to="/agencies/$agencyId/clients/$clientId/ad-spend" params={params} search={{ ...days, connection, level }}>
          {label}
        </Link>
      );
    case 'revenue':
      return (
        <Link className={className} to="/agencies/$agencyId/clients/$clientId/revenue" params={params} search={days}>
          {label}
        </Link>
      );
    default: {
      const tab = item.family === 'funnel' ? ('funnel' as const) : item.family === 'roas' ? ('roas' as const) : undefined;
      const grouping = item.parameters.group_by;
      const group = grouping === 'content' || grouping === 'link' || grouping === 'recipient' ? grouping : undefined;
      const model = typeof item.parameters.model_version === 'string' ? item.parameters.model_version : undefined;
      return (
        <Link className={className} to="/agencies/$agencyId/clients/$clientId/attribution" params={params} search={{ ...days, tab, connection, level, group, model }}>
          {label}
        </Link>
      );
    }
  }
}

/**
 * The export a report email opens (E07; 016-C section 8), and the states of one that is gone (E08).
 * The address is checked again: a person who may not see the export gets "Page not found".
 */
export function ExportPage() {
  usePageTitle('reports.export.pageTitle');
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const { exportId } = route.useParams();
  const item = useQuery(exportQuery(agencyId, clientId, exportId));
  const schedules = useQuery(schedulesQuery(agencyId, clientId));
  const members = useQuery({ ...membersQuery(agencyId), enabled: manager });
  const period = usePeriodText();
  const model = useModelLabel(agencyId, clientId, item.data?.parameters.model_version);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const download = useMutation({
    mutationFn: async (found: ReportExport) => saveFile(await downloadExport(agencyId, clientId, found.id), `report-${found.family}.csv`),
    onMutate: () => setProblem(null),
    onError: async (error) => {
      setProblem(describeError(error, downloadErrors));
      if (isApiError(error) && error.status === 410) {
        await queryClient.invalidateQueries({ queryKey: exportsKey(agencyId, clientId) });
      }
    },
  });

  const data = item.data;
  if (!data) return <QueryStates query={item} />;
  const name = intl.formatMessage({ id: reportNameId(data.family as ReportFamily, data.parameters) });
  const schedule = schedules.data?.find((found) => found.id === data.schedule_id)?.name ?? null;
  const person = members.data?.find((member) => member.id === data.requested_by_membership_id)?.display_name ?? null;
  const gone = exportGone(data);

  if (gone) {
    return (
      <div className="c-empty a-gone">
        <span className="c-empty__icon">
          <Icon name={gone === 'expired' ? 'hourglass' : gone === 'disconnection' || gone === 'connection_purged' ? 'unplug' : 'ban'} />
        </span>
        <PageHeading className="c-empty__title">
          <FormattedMessage id="reports.gone.title" />
        </PageHeading>
        <p className="c-empty__text">
          <FormattedMessage id="reports.gone.what" values={{ report: name, period: period(data.period.start, data.period.end) }} />{' '}
          <FormattedMessage id={goneReasons[gone]} values={{ when: <Moment value={gone === 'expired' ? data.expires_at : (data.revoked_at ?? data.expires_at)} /> }} />
        </p>
        <ErrorNotice message={problem} />
        <div className="l-cluster a-gone__actions">
          <OpenReport item={data} />
          <Link className="c-btn c-btn--secondary" to="/agencies/$agencyId/clients/$clientId/reports" params={{ agencyId, clientId }}>
            <FormattedMessage id="reports.export.all" />
          </Link>
        </div>
      </div>
    );
  }

  const previous = previousPeriod(data.period.start, data.period.end);
  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>
            <FormattedMessage id="reports.export.heading" values={{ report: name, period: period(data.period.start, data.period.end) }} />
          </PageHeading>
          <p className="c-pagehead__lead">
            {data.source === 'schedule' ? (
              schedule ? (
                <FormattedMessage id="reports.export.madeBySchedule" values={{ schedule, when: <Moment value={data.created_at} /> }} />
              ) : (
                <FormattedMessage id="reports.export.madeByAnySchedule" values={{ when: <Moment value={data.created_at} /> }} />
              )
            ) : person ? (
              <FormattedMessage id="reports.export.madeByPerson" values={{ name: person, when: <Moment value={data.created_at} /> }} />
            ) : (
              <FormattedMessage id="reports.export.madeByHand" values={{ when: <Moment value={data.created_at} /> }} />
            )}
          </p>
        </div>
        <div className="l-cluster">
          <Link className="c-btn c-btn--secondary" to="/agencies/$agencyId/clients/$clientId/reports" params={{ agencyId, clientId }}>
            <Icon name="arrow-left" size="sm" mirror />
            <FormattedMessage id="reports.export.all" />
          </Link>
          <button type="button" className="c-btn c-btn--primary" disabled={download.isPending} onClick={() => download.mutate(data)}>
            <Icon name="download" size="sm" />
            <FormattedMessage id="analyze.csv" />
          </button>
        </div>
      </div>
      <ErrorNotice message={problem} />
      <div className="l-split">
        <article className="c-card">
          <div className="c-card__header">
            <div>
              <h2 className="c-card__title">
                <FormattedMessage id="reports.export.card" />
              </h2>
              <p className="c-card__subtitle">
                <FormattedMessage id="reports.exports.daysLeft" values={{ days: daysLeft(data.expires_at) }} />
              </p>
            </div>
            <Badge tone="success" icon="circle-check">
              <FormattedMessage id="reports.state.ready" />
            </Badge>
          </div>
          <div className="c-card__body">
            <dl className="c-dl c-dl--split">
              <dt>
                <FormattedMessage id="reports.detail.report" />
              </dt>
              <dd>{name}</dd>
              {model ? (
                <>
                  <dt>
                    <FormattedMessage id="attribution.model.label" />
                  </dt>
                  <dd>{model}</dd>
                </>
              ) : null}
              <dt>
                <FormattedMessage id="reports.detail.period" />
              </dt>
              <dd>
                <FormattedMessage id="reports.detail.periodDays" values={{ period: period(data.period.start, data.period.end), days: data.period.days }} />
              </dd>
              {data.parameters.compare === true ? (
                <>
                  <dt>
                    <FormattedMessage id="reports.detail.comparedWith" />
                  </dt>
                  <dd>{period(previous.start, previous.end)}</dd>
                </>
              ) : null}
              {data.includes_financials ? (
                <>
                  <dt>
                    <FormattedMessage id="reports.detail.saleValues" />
                  </dt>
                  <dd>
                    <FormattedMessage id="reports.export.financialData" />
                  </dd>
                </>
              ) : null}
              <dt>
                <FormattedMessage id="reports.detail.keptUntil" />
              </dt>
              <dd>
                <Moment value={data.expires_at} />
              </dd>
              <dt>
                <FormattedMessage id="reports.detail.size" />
              </dt>
              <dd>
                <FormattedMessage
                  id="reports.export.size"
                  values={{ rows: data.row_count ?? 0, kib: Math.max(1, Math.ceil((data.byte_size ?? 0) / 1024)) }}
                />
              </dd>
              <dt>
                <FormattedMessage id="reports.detail.downloads" />
              </dt>
              <dd>
                {data.last_downloaded_at ? (
                  <FormattedMessage id="reports.export.downloads" values={{ count: data.download_count, last: <Moment value={data.last_downloaded_at} /> }} />
                ) : (
                  <FormattedMessage id="reports.export.noDownload" />
                )}
              </dd>
            </dl>
          </div>
          <div className="c-card__footer">
            <Icon name="lock" size="sm" />
            <FormattedMessage id={data.includes_financials ? 'reports.export.checkedFinance' : 'reports.export.checked'} />
          </div>
        </article>
        <article className="c-card">
          <div className="c-card__header">
            <div>
              <h2 className="c-card__title">
                <FormattedMessage id="reports.export.today" />
              </h2>
            </div>
          </div>
          <div className="c-card__body l-stack">
            <p>
              <FormattedMessage id="reports.export.todayText" />
            </p>
            <div>
              <OpenReport item={data} />
            </div>
          </div>
        </article>
      </div>
    </>
  );
}
