import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SaveExportButton } from '@/features/reports/SaveExport';

import { agency, asRole, client, empty, fakeApi, json, member, refused, withClients } from '../support/api';
import { forgetEverything, openApp, renderWithMessages } from '../support/app';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-28T12:00:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
  forgetEverything();
});

const base = `/agencies/${agency.id}/clients/${client.id}`;
const reportsPath = `${base}/reports`;
const exportsRoute = `GET ${base}/report-exports`;
const schedulesRoute = `GET ${base}/report-schedules`;

const exported = (given: Record<string, unknown> = {}) => ({
  id: 'e1111111-1111-4111-8111-111111111111',
  client_id: client.id,
  family: 'revenue',
  parameters: { compare: true },
  period: { start: '2026-11-23', end: '2026-11-30', days: 7 },
  includes_financials: true,
  source: 'schedule',
  schedule_id: 's1111111-1111-4111-8111-111111111111',
  requested_by_membership_id: 'b1111111-1111-4111-8111-111111111111',
  status: 'ready',
  revoked_reason: null,
  revoked_at: null,
  created_at: '2026-11-23T07:00:00Z',
  expires_at: '2026-11-30T07:00:00Z',
  row_count: 7,
  byte_size: 900,
  report_revision: 'r1',
  download_count: 2,
  last_downloaded_at: '2026-11-27T09:00:00Z',
  ...given,
});
const revoked = exported({
  id: 'e2222222-2222-4222-8222-222222222222',
  family: 'social',
  parameters: { compare: false, connection_id: 'k1', view: 'daily', metrics: null },
  includes_financials: false,
  source: 'manual',
  schedule_id: null,
  status: 'revoked',
  revoked_reason: 'disconnection',
  revoked_at: '2026-11-27T11:02:00Z',
  row_count: null,
  byte_size: null,
});
const expired = exported({ id: 'e3333333-3333-4333-8333-333333333333', family: 'spend', parameters: { compare: false, connection_id: 'k2', level: 'campaign' }, status: 'expired', source: 'manual', schedule_id: null });

const schedule = (given: Record<string, unknown> = {}) => ({
  id: 's1111111-1111-4111-8111-111111111111',
  client_id: client.id,
  name: 'Weekly revenue',
  report: { family: 'revenue', compare: true },
  sale_values: false,
  cadence: 'weekly',
  weekday: 1,
  hour: 9,
  time_zone: 'Africa/Cairo',
  status: 'active',
  pause_reason: null,
  owner_membership_id: 'b1111111-1111-4111-8111-111111111111',
  next_run_at: '2026-11-30T07:00:00Z',
  last_run: { at: '2026-11-23T07:00:00Z', outcome: 'built', error_code: null, notified: 2, skipped: 1 },
  consecutive_failures: 0,
  receiving: false,
  recipients: ['b1111111-1111-4111-8111-111111111111'],
  created_at: '2026-11-01T00:00:00Z',
  updated_at: '2026-11-01T00:00:00Z',
  ...given,
});

const youssef = member({ id: 'b2222222-2222-4222-8222-222222222222', user_id: 'u2', role: 'analyst', display_name: 'Youssef Salah', email_normalized: 'youssef@lumen.example', clients: [] });

const reporting = (routes: Record<string, unknown> = {}) =>
  ({
    ...withClients([client]),
    [`GET /agencies/${agency.id}/members`]: json(200, [member(), youssef]),
    [exportsRoute]: json(200, { exports: [exported(), revoked, expired], limit: 100, offset: 0 }),
    [schedulesRoute]: json(200, { schedules: [schedule()], limit: 100, offset: 0 }),
    ...routes,
  }) as Parameters<typeof fakeApi>[0];

/** The test environment has no object addresses; these stand in for the browser's while a file is saved. */
function withObjectAddresses() {
  Object.assign(URL, { createObjectURL: () => 'blob:export', revokeObjectURL: () => undefined });
  return () => {
    Reflect.deleteProperty(URL, 'createObjectURL');
    Reflect.deleteProperty(URL, 'revokeObjectURL');
  };
}

describe('the exports of a client', () => {
  it('shows each export with its state, its expiry, its size and its downloads', async () => {
    fakeApi(reporting());
    openApp(reportsPath);
    expect(await screen.findByText('1 of 50 kept. Each one is deleted 7 days after it was made.')).toBeInTheDocument();
    const ready = within(screen.getByRole('row', { name: /^Revenue/ }));
    expect(ready.getByText('Ready')).toBeInTheDocument();
    expect(ready.getByText('Schedule: Weekly revenue')).toBeInTheDocument();
    expect(ready.getByText('7 rows')).toBeInTheDocument();
    expect(ready.getByText('2 days left')).toBeInTheDocument();
    const gone = within(screen.getByRole('row', { name: /^Content, daily/ }));
    expect(gone.getByText('Revoked')).toBeInTheDocument();
    expect(gone.getByText('Its account was disconnected')).toBeInTheDocument();
    expect(gone.queryByRole('button', { name: /^Download/ })).not.toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /^Ad spend by campaign/ })).getByText('Expired')).toBeInTheDocument();
  });

  it('downloads a ready export through the API, and says why when it is gone', async () => {
    const restore = withObjectAddresses();
    try {
      const server = fakeApi(reporting({ [`GET ${base}/report-exports/${exported().id}/download`]: new Response('day,amount\n', { headers: { 'Content-Type': 'text/csv' } }) }));
      const user = userEvent.setup();
      openApp(reportsPath);
      await user.click(await screen.findByRole('button', { name: /^Download Revenue/ }));
      await waitFor(() => expect(server.sent(`GET ${base}/report-exports/${exported().id}/download`)).toHaveLength(1));

      server.routes[`GET ${base}/report-exports/${exported().id}/download`] = refused(410, 'export_gone');
      await user.click(screen.getByRole('button', { name: /^Download Revenue/ }));
      expect(await screen.findByText('This export is no longer available. The list says why.')).toBeInTheDocument();
      await waitFor(() => expect(server.sent(exportsRoute).length).toBeGreaterThan(1));
    } finally {
      restore();
    }
  });

  it('revokes an export after asking', async () => {
    const server = fakeApi(reporting({ [`DELETE ${base}/report-exports/${exported().id}`]: json(200, exported({ status: 'revoked', revoked_reason: 'manual' })) }));
    const user = userEvent.setup();
    openApp(reportsPath);
    await user.click(await screen.findByRole('button', { name: /^Actions for Revenue/ }));
    await user.click(await screen.findByRole('menuitem', { name: 'Revoke' }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.click(dialog.getByRole('button', { name: 'Revoke the export' }));
    await waitFor(() => expect(server.sent(`DELETE ${base}/report-exports/${exported().id}`)).toHaveLength(1));
  });
});

describe('the schedules of a client', () => {
  it('show an owner their timing, their last run and their recipients', async () => {
    fakeApi(reporting({ [schedulesRoute]: json(200, { schedules: [schedule(), schedule({ id: 's2', name: 'Daily Instagram', status: 'paused', pause_reason: 'repeated_failures', last_run: { at: '2026-11-27T07:00:00Z', outcome: 'failed', error_code: 'source_unavailable', notified: 0, skipped: 0 } })], limit: 100, offset: 0 }) }));
    const user = userEvent.setup();
    openApp(`${reportsPath}?tab=schedules`);
    const weekly = within(await screen.findByRole('row', { name: /^Weekly revenue/ }));
    expect(weekly.getByText('Every Monday at 09:00')).toBeInTheDocument();
    expect(weekly.getByText('Africa/Cairo')).toBeInTheDocument();
    expect(weekly.getByText('Built; 2 recipients told, 1 skipped')).toBeInTheDocument();
    const daily = within(screen.getByRole('row', { name: /^Daily Instagram/ }));
    expect(daily.getByText('Failed: its account cannot be read')).toBeInTheDocument();
    expect(daily.getByText('After three failed runs in a row')).toBeInTheDocument();
    expect(screen.getByText('1 of 10 active. A schedule runs with the access of its owner, checked at every run.')).toBeInTheDocument();
    await user.click(daily.getByRole('button', { name: 'Actions for Daily Instagram' }));
    expect(await screen.findByRole('menuitem', { name: 'Resume' })).toBeInTheDocument();
  });

  it('let a recipient who is no manager stop receiving one, and nothing else', async () => {
    const server = fakeApi(
      asRole(
        'analyst',
        reporting({
          [schedulesRoute]: json(200, { schedules: [schedule({ receiving: true, recipients: null })], limit: 100, offset: 0 }),
          [`DELETE ${base}/report-schedules/${schedule().id}/recipients/me`]: empty(),
        }),
      ),
    );
    const user = userEvent.setup();
    openApp(`${reportsPath}?tab=schedules`);
    expect(await screen.findByText('The schedules you receive. Owners and admins create and change schedules.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'New schedule' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'Recipients' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Stop receiving' }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.click(dialog.getByRole('button', { name: 'Stop receiving' }));
    await waitFor(() => expect(server.sent(`DELETE ${base}/report-schedules/${schedule().id}/recipients/me`)).toHaveLength(1));
  });

  it('are created with a name and members who may read the report, as the API takes them', async () => {
    const server = fakeApi(reporting({ [`POST ${base}/report-schedules`]: json(201, schedule()) }));
    const user = userEvent.setup();
    openApp(`${reportsPath}?tab=schedules`);
    await user.click(await screen.findByRole('button', { name: 'New schedule' }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.click(dialog.getByRole('button', { name: 'Create schedule' }));
    expect(await dialog.findByText('Enter a name.')).toBeInTheDocument();
    expect(server.sent(`POST ${base}/report-schedules`)).toHaveLength(0);

    // Revenue needs financial access: an analyst without a grant of the client cannot receive it.
    expect(dialog.getByRole('checkbox', { name: /Youssef Salah/ })).toBeDisabled();
    expect(dialog.getByText('Cannot receive it: no access to this client')).toBeInTheDocument();
    await user.type(dialog.getByLabelText('Name'), 'Weekly revenue');
    await user.click(dialog.getByRole('checkbox', { name: /Mona Hassan/ }));
    await user.click(dialog.getByRole('button', { name: 'Create schedule' }));
    await waitFor(() => expect(server.sent(`POST ${base}/report-schedules`)).toHaveLength(1));
    expect(server.sent(`POST ${base}/report-schedules`)[0]?.body).toEqual({
      name: 'Weekly revenue',
      report: { family: 'revenue', compare: 'previous' },
      sale_values: false,
      cadence: 'weekly',
      weekday: 1,
      hour: 9,
      time_zone: expect.any(String),
      recipients: [member().id],
    });
  });

  it('say why the API refused a schedule', async () => {
    fakeApi(reporting({ [`POST ${base}/report-schedules`]: refused(409, 'schedule_limit_reached') }));
    const user = userEvent.setup();
    openApp(`${reportsPath}?tab=schedules`);
    await user.click(await screen.findByRole('button', { name: 'New schedule' }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.type(dialog.getByLabelText('Name'), 'One more');
    await user.click(dialog.getByRole('button', { name: 'Create schedule' }));
    expect(await dialog.findByText('This client already has 10 active schedules. Pause or delete one first.')).toBeInTheDocument();
  });
});

describe('the export a report email opens', () => {
  const exportPath = `${reportsPath}/exports/${exported().id}`;
  const exportRoute = `GET ${base}/report-exports/${exported().id}`;

  it('shows the export and downloads it', async () => {
    fakeApi(reporting({ [exportRoute]: json(200, exported()) }));
    openApp(exportPath);
    expect(await screen.findByRole('heading', { level: 1, name: /^Revenue/ })).toBeInTheDocument();
    expect(await screen.findByText(/Made by the schedule .Weekly revenue. on/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download CSV' })).toBeInTheDocument();
    expect(screen.getByText('Each download is checked again: it needs access to this client and to its financial data.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Revenue for these days' })).toHaveAttribute('href', expect.stringContaining('from=2026-11-23'));
  });

  it('says why an export is gone', async () => {
    fakeApi(reporting({ [exportRoute]: json(200, exported({ status: 'revoked', revoked_reason: 'erasure', revoked_at: '2026-11-27T11:02:00Z' })) }));
    openApp(exportPath);
    expect(await screen.findByRole('heading', { level: 1, name: 'This export is no longer available' })).toBeInTheDocument();
    expect(screen.getByText(/because a person's data was erased in this client\./)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Download CSV' })).not.toBeInTheDocument();
  });

  it('does not exist for a reader who may not see it', async () => {
    fakeApi(reporting({ [exportRoute]: refused(403, 'access_denied') }));
    openApp(exportPath);
    expect(await screen.findByRole('heading', { name: 'Page not found', level: 1 })).toBeInTheDocument();
  });
});

describe('saving a report as an export', () => {
  const scope = { agencyId: agency.id, clientId: client.id, range: { start: '2026-11-01', end: '2026-11-08' }, compare: true };
  const draw = (onSaved = vi.fn()) => {
    renderWithMessages(
      <QueryClientProvider client={new QueryClient()}>
        <SaveExportButton choice={{ scope, family: 'revenue', parameters: {} }} onSaved={onSaved} />
      </QueryClientProvider>,
    );
    return onSaved;
  };

  it('asks with the report, its days and its comparison, then saves the page’s report', async () => {
    const server = fakeApi({ [`POST ${base}/report-exports`]: json(201, exported()) } as Parameters<typeof fakeApi>[0]);
    const user = userEvent.setup();
    const onSaved = draw();
    await user.click(screen.getByRole('button', { name: 'Save as export' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Save this report as an export?' }));
    expect(dialog.getByText('Revenue')).toBeInTheDocument();
    expect(dialog.getByText(/7 days$/)).toBeInTheDocument();
    expect(dialog.getByText('Compared with')).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Save export' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(server.sent(`POST ${base}/report-exports`)[0]?.body).toEqual({ family: 'revenue', start: '2026-11-01', end: '2026-11-08', compare: 'previous' });
  });

  it('says when the client keeps as many exports as it may', async () => {
    fakeApi({ [`POST ${base}/report-exports`]: refused(409, 'export_limit_reached') } as Parameters<typeof fakeApi>[0]);
    const user = userEvent.setup();
    draw();
    await user.click(screen.getByRole('button', { name: 'Save as export' }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.click(dialog.getByRole('button', { name: 'Save export' }));
    expect(await dialog.findByText('This client already keeps 50 exports. Revoke one in Reports, or wait until one expires.')).toBeInTheDocument();
  });
});
