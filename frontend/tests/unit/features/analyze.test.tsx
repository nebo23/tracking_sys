import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';

import { presetRange, toReportRange } from '@/features/analyze/range';

import { agency, asRole, client, connection, fakeApi, json, refused, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

const base = `/agencies/${agency.id}/clients/${client.id}`;
const range = toReportRange(presetRange('last30'));
const instagram = connection({ id: 'e1111111-1111-4111-8111-111111111111', provider: 'synthetic_instagram', account: { external_account_id: 'ig-1', label: '@olive.thyme' } });
const meta = connection({ id: 'e2222222-2222-4222-8222-222222222222', provider: 'synthetic_meta_ads', account: { external_account_id: 'act_42', label: 'Olive ads' } });

const page = { page: 1, page_size: 500, total_rows: 0, total_pages: 1 };
const total = (metric: string, value: number | null, status: string, reason: string | null, extra: Record<string, unknown> = {}) => ({
  period: 'current',
  stream: 'account',
  metric,
  unit: 'count',
  metric_class: 'daily_additive',
  value,
  status,
  reason,
  provisional: false,
  definition_since: null,
  ...extra,
});
const day = (date: string, value: number | null, availability = 'available', reason: string | null = null) => ({
  stream: 'account',
  metric: 'views',
  unit: 'count',
  metric_class: 'daily_additive',
  date,
  value,
  availability,
  reason,
  provisional: false,
  definition_since: null,
  fetched_at: '2026-11-27T08:00:00Z',
});

const socialReport = (given: Record<string, unknown> = {}) => ({
  contract_version: '016b.1',
  family: 'social',
  client_id: client.id,
  connection_id: instagram.id,
  view: 'daily',
  period: { start: range.start, end: range.end, days: 30 },
  comparison_period: null,
  day_zone: 'UTC',
  basis: 'native_daily_activity',
  catalog_version: '016a.1',
  generated_at: '2026-11-28T08:00:00Z',
  revision: 'r1',
  totals: [total('views', 300, 'partial', 'incomplete_days'), total('total_interactions', null, 'unavailable', 'missing')],
  comparison: null,
  rows: [day(range.start, 100), day(addOne(range.start), null, 'missing', 'not_returned')],
  page,
  source_status: {
    provider: 'synthetic_instagram',
    family: 'instagram',
    adapter_state: 'available',
    adapter_version: '1',
    connection_status: 'active',
    connection_last_successful_sync_at: '2026-11-28T07:00:00Z',
    catalog_version: '016a.1',
    excluded_metrics: [],
    source_rows: 2,
    streams: [{ stream: 'account', coverage: {}, sync: { state: 'idle', reason: null, in_progress: false }, freshness: { state: 'stale' }, provisional_delay_hours: 48 }],
  },
  dependencies: [],
  ...given,
});

function addOne(date: string): string {
  const moment = new Date(`${date}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + 1);
  return moment.toISOString().slice(0, 10);
}

const spendReport = (given: Record<string, unknown> = {}) => ({
  contract_version: '016b.1',
  family: 'spend',
  client_id: client.id,
  connection_id: meta.id,
  level: 'campaign',
  period: { start: range.start, end: range.end, days: 30 },
  comparison_period: null,
  day_zone: 'Africa/Cairo',
  basis: 'account_local_days',
  generated_at: '2026-11-28T08:00:00Z',
  revision: 's1',
  totals: [
    { period: 'current', currency: 'EGP', exponent: 2, spend: { minor: 4230000, decimal: '42300.00' }, impressions: 12400, clicks: 310, days_with_spend: 9, provisional: false, status: 'partial', reason: 'refused_facts' },
  ],
  comparison: null,
  rows: [
    { object_id: '120200', currency: 'EGP', exponent: 2, spend: { minor: 3000000, decimal: '30000.00' }, impressions: 9000, clicks: 200, days_with_spend: 9, provisional: false },
    { object_id: '120300', currency: 'EGP', exponent: 2, spend: { minor: 1230000, decimal: '12300.00' }, impressions: 3400, clicks: 110, days_with_spend: 4, provisional: true },
  ],
  page,
  source_status: {
    provider: 'synthetic_meta_ads',
    adapter_state: 'available',
    adapter_version: '1',
    connection_status: 'active',
    connection_last_successful_sync_at: '2026-11-28T07:00:00Z',
    account: { currency: 'EGP', time_zone: 'Africa/Cairo', previous_currency: null, currency_changed_at: null, previous_time_zone: null, time_zone_changed_at: null },
    stream: { stream: 'ad_daily', covered_from: range.start, complete_through: range.end, sync: { state: 'idle', reason: null, in_progress: false }, freshness: { state: 'fresh' } },
    periods: [
      { period: 'current', start: range.start, end: range.end, coverage: 'complete', facts: 13, valued_facts: 12, refused: { unparseable_amount: 1, unsupported_currency: 0 }, provisional_dates: [], fact_zones: ['Africa/Cairo'], status: 'partial', reason: 'refused_facts' },
    ],
    source_rows: 13,
  },
  dependencies: [],
  ...given,
});

const revenueReport = () => ({
  contract_version: '016b.1',
  family: 'revenue',
  client_id: client.id,
  period: { start: range.start, end: range.end, days: 30 },
  comparison_period: null,
  day_zone: 'UTC',
  basis: 'ledger_effective_time',
  generated_at: '2026-11-28T08:00:00Z',
  revision: 'v1',
  totals: [
    {
      block: 'verified',
      period: 'current',
      currency: 'EGP',
      exponent: 2,
      captured: { minor: 13000000, decimal: '130000.00' },
      refunded: { minor: 155000, decimal: '1550.00' },
      charged_back: { minor: 0, decimal: '0.00' },
      reversed: { minor: 0, decimal: '0.00' },
      corrected: { minor: 0, decimal: '0.00' },
      net: { minor: 12845075, decimal: '128450.75' },
      postings: 40,
    },
    { block: 'declared', period: 'current', currency: 'EGP', exponent: 2, sales: { minor: 500000, decimal: '5000.00' }, refunds: { minor: 0, decimal: '0.00' }, items: 2 },
  ],
  comparison: null,
  unresolved: { scope: 'all_evidence', pending: 2, pending_reasons: {}, held: 1, reconciliation: 0, reconciliation_reasons: {}, evidence_rows: 50, evidence_limit: 100000, external_completeness: 'unknown' },
  rows: [{ block: 'verified', currency: 'EGP', exponent: 2, date: range.start, kind: 'capture', amount: { minor: 500000, decimal: '5000.00' }, postings: 2 }],
  page,
  dependencies: [],
});

const reports = `GET /agencies/${agency.id}/clients/${client.id}/reports`;
const world = (connections: unknown[], routes: Record<string, unknown> = {}) => ({
  ...withClients([client], { [client.id]: connections }),
  [`${reports}/social`]: json(200, socialReport()),
  [`${reports}/spend`]: json(200, spendReport()),
  [`${reports}/revenue`]: json(200, revenueReport()),
  [`GET /agencies/${agency.id}/clients/${client.id}/ad-spend`]: json(200, { rows: [{ object_id: '120200', name: 'Ramadan offers' }], next_after: null }),
  ...routes,
});

// The pages load by route with their charts (D4). Loading them once before the tests keeps the first
// test of a page from paying for it inside its wait when the whole suite runs at once.
beforeAll(async () => {
  await Promise.all([
    import('@/features/analyze/OverviewPage'),
    import('@/features/analyze/ContentPage'),
    import('@/features/analyze/RevenuePage'),
    import('@/features/analyze/AdSpendPage'),
  ]);
}, 30_000);

describe('the overview of a client', () => {
  it('names a total that is partial or unavailable instead of showing it as a number, with its source', async () => {
    fakeApi(world([instagram, meta]) as never);
    openApp(base);
    const figures = within(await screen.findByRole('region', { name: 'Key figures' }));
    const views = within(await figures.findByText('Views').then((label) => label.closest('article') as HTMLElement));
    expect(await views.findByText('300')).toBeInTheDocument();
    expect(views.getByText('Partial')).toBeInTheDocument();
    expect(views.getByText('Some days have no value.')).toBeInTheDocument();
    expect(views.getByText(/Synthetic Instagram|@olive.thyme/)).toBeInTheDocument();
    const interactions = within(figures.getByText('Interactions').closest('article') as HTMLElement);
    expect(interactions.getAllByText('Not available').length).toBeGreaterThan(0);
    expect(interactions.getByText('There are no values for this range.')).toBeInTheDocument();
    expect(interactions.queryByText('0')).not.toBeInTheDocument();
    expect(await figures.findByText(/128,450\.75/)).toBeInTheDocument();
    expect(figures.getByText('3 to match')).toBeInTheDocument();
    const spend = within(figures.getByText('Ad spend').closest('article') as HTMLElement);
    expect(spend.getByText(/42,300\.00/)).toBeInTheDocument();
    expect(spend.getByText('Some spend records could not be valued.')).toBeInTheDocument();
  });

  it('says what needs financial access and shows no amount without it', async () => {
    fakeApi(
      asRole('analyst', world([instagram, meta], { [`${reports}/revenue`]: refused(403, 'access_denied'), [`${reports}/spend`]: refused(403, 'access_denied') }) as never) as never,
    );
    openApp(base);
    const figures = within(await screen.findByRole('region', { name: 'Key figures' }));
    await waitFor(() => expect(figures.getAllByText('Needs financial access')).toHaveLength(2));
    expect(figures.queryByText(/EGP/)).not.toBeInTheDocument();
  });

  it('keeps the range and the comparison in the address and draws the previous period from its own report', async () => {
    const server = fakeApi(world([instagram]) as never);
    const user = userEvent.setup();
    openApp(base);
    await user.click(await screen.findByRole('checkbox', { name: 'Compare with the previous period' }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('compare')).toBe('true'));
    await waitFor(() => expect(server.sent(`${reports}/social`).length).toBeGreaterThanOrEqual(3));
    const asked = server.sent(`${reports}/social`).map((request) => new URL(request.url).searchParams);
    expect(asked.some((query) => query.get('compare') === 'previous' && query.get('start') === range.start)).toBe(true);
    // The previous period's own days, asked without a comparison of their own.
    expect(asked.some((query) => query.get('end') === range.start && query.get('compare') === null)).toBe(true);
  });

  it('asks a client without accounts to connect one', async () => {
    fakeApi(world([]) as never);
    openApp(base);
    const figures = within(await screen.findByRole('region', { name: 'Key figures' }));
    expect(figures.getAllByText('No account connected')).toHaveLength(2);
    expect(figures.getByText('No ad account connected')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Connect an account' })).toHaveAttribute('href', `${base}/connections`);
  });
});

describe('the content of a client', () => {
  it('names each day without a value in the table, never drawing it as zero', async () => {
    fakeApi(world([instagram], { [`${reports}/social`]: ({ url }: { url: string }) => json(200, socialReport(new URL(url).searchParams.get('view') === 'content_cohort' ? { view: 'content_cohort', totals: [], rows: [] } : {})) }) as never);
    const user = userEvent.setup();
    openApp(`${base}/content`);
    await user.click(await screen.findByRole('button', { name: 'Table' }));
    const table = within(await screen.findByRole('table', { name: 'Views by day' }));
    const rows = table.getAllByRole('row');
    expect(rows[1]).toHaveTextContent('100');
    expect(rows[2]).toHaveTextContent('Missing: the provider returned no value');
    expect(await screen.findByText('Nothing was published in this range.')).toBeInTheDocument();
  });
});

describe('revenue', () => {
  it('keeps verified payments and declarations apart, with what waits to be matched', async () => {
    fakeApi(world([]) as never);
    openApp(`${base}/revenue`);
    const blocks = within(await screen.findByRole('region', { name: 'Revenue blocks' }));
    const verified = within(blocks.getByRole('heading', { name: 'Verified payments' }).closest('article') as HTMLElement);
    expect(await verified.findByText(/128,450\.75/)).toBeInTheDocument();
    const declared = within(blocks.getByRole('heading', { name: 'Declared' }).closest('article') as HTMLElement);
    expect(declared.getByText(/5,000\.00/)).toBeInTheDocument();
    expect(declared.queryByText(/128,450\.75/)).not.toBeInTheDocument();
    const waiting = within(blocks.getByRole('heading', { name: 'Waiting to be matched' }).closest('article') as HTMLElement);
    expect(waiting.getByText('Pending').nextSibling).toHaveTextContent('2');
  });

  it('says that financial access is needed, with no amount and no download', async () => {
    fakeApi(asRole('client_viewer', world([], { [`${reports}/revenue`]: refused(403, 'access_denied') }) as never) as never);
    openApp(`${base}/revenue`);
    expect(await screen.findByText(/need financial access to this client/)).toBeInTheDocument();
    const main = within(screen.getByRole('main'));
    expect(main.queryByText(/EGP/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Download CSV' })).not.toBeInTheDocument();
  });
});

describe('ad spend', () => {
  it('names each object from the ad account beside its ID, and keeps the level in the address', async () => {
    const server = fakeApi(world([meta]) as never);
    const user = userEvent.setup();
    openApp(`${base}/ad-spend`);
    const named = await screen.findByText('Ramadan offers');
    expect(named.closest('th')).toHaveTextContent('120200');
    expect(screen.getByText('Name not known').closest('th')).toHaveTextContent('120300');
    expect(screen.getByText('Records not valued').nextSibling).toHaveTextContent('1');
    expect(screen.getByText('Africa/Cairo', { selector: 'dd' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Campaigns/ }));
    await user.click(await screen.findByRole('option', { name: 'Ads' }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('level')).toBe('ad'));
    await waitFor(() => expect(server.sent(`${reports}/spend`).some((request) => new URL(request.url).searchParams.get('level') === 'ad')).toBe(true));
  });

  it('asks for an ad account when the client has none', async () => {
    fakeApi(world([instagram]) as never);
    openApp(`${base}/ad-spend`);
    expect(await screen.findByRole('heading', { name: 'No ad account is connected' })).toBeInTheDocument();
  });
});

