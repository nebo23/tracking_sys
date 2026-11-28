import { queryOptions } from '@tanstack/react-query';

import { api, call } from './client';
import { clientKey } from './clients';
import type { components } from './schema';

export type SocialReport = components['schemas']['SocialReportResult'];
export type SocialTotal = components['schemas']['SocialTotal'];
export type SocialRow = components['schemas']['SocialRow'];
export type SocialComparison = components['schemas']['SocialComparison'];
export type StreamStatus = components['schemas']['StreamStatus'];
export type SpendReport = components['schemas']['SpendReportResult'];
export type SpendTotal = components['schemas']['SpendReportTotal'];
export type SpendRow = components['schemas']['SpendReportRow'];
export type SpendComparison = components['schemas']['SpendComparison'];
export type RevenueReport = components['schemas']['RevenueReportResult'];
export type RevenueTotal = components['schemas']['RevenueTotal'];
export type RevenueRow = components['schemas']['RevenueRow'];
export type RevenueComparison = components['schemas']['RevenueComparison'];
export type Amount = components['schemas']['Amount'];
export type AttributionReport = components['schemas']['AttributionReportResult'];
export type AttributionRow = components['schemas']['AttributionGroupRow'];
export type FunnelReport = components['schemas']['FunnelReportResult'];
export type FunnelRow = components['schemas']['FunnelRow'];
export type RoasReport = components['schemas']['RoasReportResult'];
export type RoasRow = components['schemas']['RoasValue'];
export type ExactShare = components['schemas']['ExactShare'];
export type ModelVersion = components['schemas']['ModelVersionView'];
export type AttributionGroup = AttributionReport['group_by'];
export type FunnelGroup = FunnelReport['group_by'];
export type SocialView = SocialReport['view'];
export type SpendLevel = SpendReport['level'];

/** The days a report covers, as the API reads them: `start` is included and `end` is not. */
export interface ReportRange {
  start: string;
  end: string;
}

/** What every report of a client is asked with: the client, the days and the comparison. */
export interface ReportScope {
  agencyId: string;
  clientId: string;
  range: ReportRange;
  compare: boolean;
}

// The largest page the API gives (016-A); a report longer than this many pages is not read to its end.
const PAGE_SIZE = 500;
const MOST_PAGES = 20;

/**
 * Every report of a client is keyed under the agency and the client (acceptance criterion 2): leaving
 * the client drops them all, and nothing of one client is ever shown for another.
 */
export const reportKey = (scope: ReportScope, family: string, parameters: Record<string, string | undefined> = {}) =>
  clientKey(scope.agencyId, scope.clientId, 'reports', family, {
    start: scope.range.start,
    end: scope.range.end,
    compare: scope.compare,
    ...parameters,
  });

interface Paged<Row> {
  revision: string;
  rows: Row[];
  page: { total_pages: number };
}

/**
 * Reads every page of one report. Later pages name the revision of the first, so the API refuses
 * them if the stored facts changed in between instead of mixing two states (016-A, D7).
 */
async function allPages<Row, Answer extends Paged<Row>>(read: (page: number, revision?: string) => Promise<Answer>): Promise<Answer> {
  const first = await read(1);
  const rows = [...first.rows];
  const last = Math.min(first.page.total_pages, MOST_PAGES);
  for (let page = 2; page <= last; page += 1) {
    const next = await read(page, first.revision);
    rows.push(...next.rows);
  }
  return { ...first, rows };
}

/**
 * The JSON answer of a report route. The same routes also answer text/csv, so the generated type
 * of their answer is a union; a request without format=csv always gets the JSON shape.
 */
const json = <Answer>(pending: Parameters<typeof call>[0]): Promise<Answer> => call(pending) as Promise<Answer>;

const comparison = (scope: ReportScope) => (scope.compare ? { compare: 'previous' as const } : {});
const path = (scope: ReportScope) => ({ agency_id: scope.agencyId, client_id: scope.clientId });

export const socialReportQuery = (scope: ReportScope, connectionId: string, view: SocialView) =>
  queryOptions({
    queryKey: reportKey(scope, 'social', { connectionId, view }),
    queryFn: () =>
      allPages<SocialRow, SocialReport>((page, revision) =>
        json<SocialReport>(
          api.GET('/agencies/{agency_id}/clients/{client_id}/reports/social', {
            params: {
              path: path(scope),
              query: {
                connection_id: connectionId,
                view,
                start: scope.range.start,
                end: scope.range.end,
                // A content cohort is never compared (016-A): the API refuses the parameter.
                ...(view === 'daily' ? comparison(scope) : {}),
                page,
                page_size: PAGE_SIZE,
                ...(revision ? { expected_revision: revision } : {}),
              },
            },
          }),
        ),
      ),
  });

export const spendReportQuery = (scope: ReportScope, connectionId: string, level: SpendLevel) =>
  queryOptions({
    queryKey: reportKey(scope, 'spend', { connectionId, level }),
    queryFn: () =>
      allPages<SpendRow, SpendReport>((page, revision) =>
        json<SpendReport>(
          api.GET('/agencies/{agency_id}/clients/{client_id}/reports/spend', {
            params: {
              path: path(scope),
              query: {
                connection_id: connectionId,
                level,
                start: scope.range.start,
                end: scope.range.end,
                ...comparison(scope),
                page,
                page_size: PAGE_SIZE,
                ...(revision ? { expected_revision: revision } : {}),
              },
            },
          }),
        ),
      ),
  });

export const revenueReportQuery = (scope: ReportScope) =>
  queryOptions({
    queryKey: reportKey(scope, 'revenue'),
    queryFn: () =>
      allPages<RevenueRow, RevenueReport>((page, revision) =>
        json<RevenueReport>(
          api.GET('/agencies/{agency_id}/clients/{client_id}/reports/revenue', {
            params: {
              path: path(scope),
              query: {
                start: scope.range.start,
                end: scope.range.end,
                ...comparison(scope),
                page,
                page_size: PAGE_SIZE,
                ...(revision ? { expected_revision: revision } : {}),
              },
            },
          }),
        ),
      ),
  });

/** The client's attribution model versions, with its default (008-B). */
export const modelVersionsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: clientKey(agencyId, clientId, 'attribution-models'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/attribution/models', { params: { path: { agency_id: agencyId, client_id: clientId } } })),
  });

const model = (modelVersion: string | undefined) => (modelVersion ? { model_version: modelVersion } : {});

/** Credit by campaign, content, link or recipient (016-B); the models view shows every active version. */
export const attributionReportQuery = (scope: ReportScope, view: 'groups' | 'models', groupBy: AttributionGroup, modelVersion?: string) =>
  queryOptions({
    queryKey: reportKey(scope, 'attribution', { view, groupBy, modelVersion }),
    queryFn: () =>
      allPages<AttributionRow, AttributionReport>((page, revision) =>
        json<AttributionReport>(
          api.GET('/agencies/{agency_id}/clients/{client_id}/reports/attribution', {
            params: {
              path: path(scope),
              query: {
                start: scope.range.start,
                end: scope.range.end,
                group_by: groupBy,
                view,
                // The models view refuses a comparison and a model version (016-B).
                ...(view === 'groups' ? { ...comparison(scope), ...model(modelVersion) } : {}),
                page,
                page_size: PAGE_SIZE,
                ...(revision ? { expected_revision: revision } : {}),
              },
            },
          }),
        ),
      ),
  });

export const funnelReportQuery = (scope: ReportScope, groupBy: FunnelGroup, modelVersion?: string) =>
  queryOptions({
    queryKey: reportKey(scope, 'funnel', { groupBy, modelVersion }),
    queryFn: () =>
      allPages<FunnelRow, FunnelReport>((page, revision) =>
        json<FunnelReport>(
          api.GET('/agencies/{agency_id}/clients/{client_id}/reports/funnel', {
            params: {
              path: path(scope),
              query: {
                start: scope.range.start,
                end: scope.range.end,
                group_by: groupBy,
                ...comparison(scope),
                ...model(modelVersion),
                page,
                page_size: PAGE_SIZE,
                ...(revision ? { expected_revision: revision } : {}),
              },
            },
          }),
        ),
      ),
  });

export const roasReportQuery = (scope: ReportScope, connectionId: string, level: SpendLevel, modelVersion?: string) =>
  queryOptions({
    queryKey: reportKey(scope, 'roas', { connectionId, level, modelVersion }),
    queryFn: () =>
      allPages<RoasRow, RoasReport>((page, revision) =>
        json<RoasReport>(
          api.GET('/agencies/{agency_id}/clients/{client_id}/reports/roas', {
            params: {
              path: path(scope),
              query: {
                connection_id: connectionId,
                level,
                start: scope.range.start,
                end: scope.range.end,
                ...comparison(scope),
                ...model(modelVersion),
                page,
                page_size: PAGE_SIZE,
                ...(revision ? { expected_revision: revision } : {}),
              },
            },
          }),
        ),
      ),
  });

/** The day before an ISO date, for the 014 read, whose `until` is included. */
export function dayBefore(date: string): string {
  const moment = new Date(`${date}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() - 1);
  return moment.toISOString().slice(0, 10);
}

/**
 * The names of a spend connection's campaigns, ad sets or ads, from the 014 read of the same days
 * and level: the reports name objects by their IDs only (016-A), so the names are joined here.
 */
export const spendNamesQuery = (scope: ReportScope, connectionId: string, level: SpendLevel) =>
  queryOptions({
    queryKey: reportKey(scope, 'spend-names', { connectionId, level }),
    queryFn: async () => {
      const names = new Map<string, string>();
      let after: string | undefined;
      for (let index = 0; index < MOST_PAGES; index += 1) {
        const read = await call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/ad-spend', {
            params: {
              path: path(scope),
              query: {
                connection_id: connectionId,
                since: scope.range.start,
                until: dayBefore(scope.range.end),
                level,
                limit: PAGE_SIZE,
                ...(after ? { after } : {}),
              },
            },
          }),
        );
        for (const row of read.rows) if (row.object_id && row.name) names.set(row.object_id, row.name);
        if (!read.next_after) break;
        after = read.next_after;
      }
      return names;
    },
  });

export type ReportFamily = 'social' | 'spend' | 'revenue' | 'attribution' | 'funnel' | 'roas';

const csvPaths = {
  social: '/agencies/{agency_id}/clients/{client_id}/reports/social',
  spend: '/agencies/{agency_id}/clients/{client_id}/reports/spend',
  revenue: '/agencies/{agency_id}/clients/{client_id}/reports/revenue',
  attribution: '/agencies/{agency_id}/clients/{client_id}/reports/attribution',
  funnel: '/agencies/{agency_id}/clients/{client_id}/reports/funnel',
  roas: '/agencies/{agency_id}/clients/{client_id}/reports/roas',
} as const;

/**
 * The same report as a CSV file, straight from the API (016-A, "CSV"): the request carries the
 * session cookie and the file never passes through a stored link.
 */
export async function reportCsv(scope: ReportScope, family: ReportFamily, parameters: Record<string, string>): Promise<Blob> {
  const query = {
    start: scope.range.start,
    end: scope.range.end,
    // A content cohort and the models view are never compared (016-A, 016-B).
    ...((family === 'social' && parameters.view !== 'daily') || parameters.view === 'models' ? {} : comparison(scope)),
    ...parameters,
    format: 'csv',
  };
  const file = await call(api.GET(csvPaths[family], { params: { path: path(scope), query: query as never }, parseAs: 'blob' }));
  return file as unknown as Blob;
}
