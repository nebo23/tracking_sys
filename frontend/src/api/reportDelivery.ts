import { queryOptions } from '@tanstack/react-query';

import { api, call } from './client';
import { clientKey } from './clients';
import type { components } from './schema';

// Retained exports and scheduled reports of one client (016-C). Every query is keyed under the
// agency and the client, so leaving the client drops them all.

export type ReportExport = components['schemas']['ReportExportView'];
export type ReportSchedule = components['schemas']['ReportScheduleView'];
export type ScheduleInput = components['schemas']['ScheduleInput'];
export type ScheduleChange = components['schemas']['ScheduleChangeInput'];
export type ScheduleReport = ScheduleInput['report'];
export type ExportInput =
  | components['schemas']['SocialExportInput']
  | components['schemas']['SpendExportInput']
  | components['schemas']['RevenueExportInput']
  | components['schemas']['AttributionExportInput']
  | components['schemas']['RoasExportInput']
  | components['schemas']['FunnelExportInput'];

const where = (agencyId: string, clientId: string) => ({ agency_id: agencyId, client_id: clientId });

// The API lists at most 100 at a time (016-C); a client keeps at most 50 unexpired exports and
// 10 active schedules, so a few pages always hold them all.
const PAGE = 100;
const MOST_PAGES = 10;

export const exportsKey = (agencyId: string, clientId: string) => clientKey(agencyId, clientId, 'report-exports');
export const schedulesKey = (agencyId: string, clientId: string) => clientKey(agencyId, clientId, 'report-schedules');

/** The exports the person may see, newest first: ready, revoked and expired ones alike. */
export const exportsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: exportsKey(agencyId, clientId),
    queryFn: async () => {
      const all: ReportExport[] = [];
      for (let page = 0; page < MOST_PAGES; page += 1) {
        const read = await call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/report-exports', {
            params: { path: where(agencyId, clientId), query: { limit: PAGE, offset: page * PAGE } },
          }),
        );
        all.push(...read.exports);
        if (read.exports.length < PAGE) break;
      }
      return all;
    },
  });

/** One export, as the page a report email opens shows it. */
export const exportQuery = (agencyId: string, clientId: string, exportId: string) =>
  queryOptions({
    queryKey: [...exportsKey(agencyId, clientId), exportId],
    queryFn: () =>
      call(
        api.GET('/agencies/{agency_id}/clients/{client_id}/report-exports/{export_id}', {
          params: { path: { ...where(agencyId, clientId), export_id: exportId } },
        }),
      ),
    // A revoked or expired export does not come back; one that is gone is read again only on request.
    retry: false,
  });

/** Saves a report as an export: the same family, choices and days as its page (D2). */
export function createExport(agencyId: string, clientId: string, input: ExportInput) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/report-exports', { params: { path: where(agencyId, clientId) }, body: input }));
}

export function revokeExport(agencyId: string, clientId: string, exportId: string) {
  return call(
    api.DELETE('/agencies/{agency_id}/clients/{client_id}/report-exports/{export_id}', {
      params: { path: { ...where(agencyId, clientId), export_id: exportId } },
    }),
  );
}

/** The stored CSV, checked again by the API at this moment (D6); a gone export answers 410. */
export async function downloadExport(agencyId: string, clientId: string, exportId: string): Promise<Blob> {
  const file = await call(
    api.GET('/agencies/{agency_id}/clients/{client_id}/report-exports/{export_id}/download', {
      params: { path: { ...where(agencyId, clientId), export_id: exportId } },
      parseAs: 'blob',
    }),
  );
  return file as unknown as Blob;
}

/** The schedules of the client for its managers, or those a recipient receives. */
export const schedulesQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: schedulesKey(agencyId, clientId),
    queryFn: async () => {
      const all: ReportSchedule[] = [];
      for (let page = 0; page < MOST_PAGES; page += 1) {
        const read = await call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/report-schedules', {
            params: { path: where(agencyId, clientId), query: { limit: PAGE, offset: page * PAGE } },
          }),
        );
        all.push(...read.schedules);
        if (read.schedules.length < PAGE) break;
      }
      return all;
    },
  });

export function createSchedule(agencyId: string, clientId: string, input: ScheduleInput) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/report-schedules', { params: { path: where(agencyId, clientId) }, body: input }));
}

export function changeSchedule(agencyId: string, clientId: string, scheduleId: string, change: ScheduleChange) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/report-schedules/{schedule_id}', {
      params: { path: { ...where(agencyId, clientId), schedule_id: scheduleId } },
      body: change,
    }),
  );
}

export function deleteSchedule(agencyId: string, clientId: string, scheduleId: string) {
  return call(
    api.DELETE('/agencies/{agency_id}/clients/{client_id}/report-schedules/{schedule_id}', {
      params: { path: { ...where(agencyId, clientId), schedule_id: scheduleId } },
    }),
  );
}

/** A recipient stops receiving a schedule. */
export function leaveSchedule(agencyId: string, clientId: string, scheduleId: string) {
  return call(
    api.DELETE('/agencies/{agency_id}/clients/{client_id}/report-schedules/{schedule_id}/recipients/me', {
      params: { path: { ...where(agencyId, clientId), schedule_id: scheduleId } },
    }),
  );
}
