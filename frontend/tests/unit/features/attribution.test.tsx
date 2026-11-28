import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { agency, client, connection, fakeApi, json, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

const base = `/agencies/${agency.id}/clients/${client.id}/attribution`;
const reports = `GET /agencies/${agency.id}/clients/${client.id}/reports`;
const meta = connection({ id: 'e2222222-2222-4222-8222-222222222222', provider: 'synthetic_meta_ads', account: { external_account_id: 'act_42', label: 'Olive ads' } });
const share = (decimal: string) => ({ numerator: Math.round(Number(decimal) * 10), denominator: 10, decimal });
const money = (decimal: string) => ({ minor: Math.round(Number(decimal) * 100), decimal });
const period = { start: '2026-11-01', end: '2026-11-08', days: 7 };
const page = { page: 1, page_size: 500, total_rows: 0, total_pages: 1 };
const linear = { id: 'b1111111-1111-4111-8111-111111111111', version_key: 'linear-30', model: 'linear', window_days: 30, rules: 'r', is_default: true, status: 'active', created_at: '2026-11-01T00:00:00Z', retired_at: null };
const first = { ...linear, id: 'b2222222-2222-4222-8222-222222222222', version_key: 'first-30', model: 'first_click', is_default: false };
const caughtUp = { state: 'caught_up', reason: null, published_generation: 3, published_at: '2026-11-28T07:00:00Z', failure_code: null, unit: 'incremental', consumer: {}, current: {} };

const attribution = (given: Record<string, unknown> = {}) => ({
  contract_version: '016b.1',
  family: 'attribution',
  client_id: client.id,
  view: 'groups',
  group_by: 'campaign',
  period,
  comparison_period: null,
  day_zone: 'UTC',
  basis: 'conversion_date',
  generated_at: '2026-11-28T08:00:00Z',
  revision: 'a1',
  model_version: linear,
  model_versions: null,
  attribution: caughtUp,
  finance: 'available',
  values: { state: 'available', reason: null },
  totals: {
    sales: { state: 'available', reason: null, items: [{ period: 'current', currency: 'EGP', exponent: 2, recipient: 'all', credited_revenue: money('1500.00'), credited_sales: share('3'), conversions: 3 }] },
    leads: { state: 'available', reason: null, items: [{ period: 'current', recipient: 'all', credited_leads: share('58.5'), conversions: 60 }] },
  },
  model_totals: null,
  reconciliation: { state: 'available', reason: null, ledger: 'available', items: [{ period: 'current', currency: 'EGP', exponent: 2, credited_revenue: money('1500.00'), ledger_net: money('1600.00'), difference: money('100.00'), state: 'difference', reason: 'attribution_behind' }] },
  model_reconciliation: null,
  comparison: null,
  rows: [
    { recipient: 'campaign', group_ref: 'ramadan', registered: true, content_items: null, sales: { state: 'available', items: [{ currency: 'EGP', exponent: 2, credited_revenue: money('1200.00'), credited_sales: share('2.5'), conversions: 3 }] }, leads: { credited_leads: share('40.5'), conversions: 41 }, models: null },
    { recipient: 'unknown', group_ref: null, registered: null, content_items: null, sales: { state: 'available', items: [] }, leads: { credited_leads: share('18'), conversions: 18 }, models: null },
  ],
  page,
  dependencies: [],
  ...given,
});

const funnel = () => ({
  contract_version: '016b.1',
  family: 'funnel',
  client_id: client.id,
  group_by: 'campaign',
  period,
  comparison_period: null,
  day_zone: 'UTC',
  basis: 'mixed',
  bases: { visits: 'received_date', leads: 'conversion_date', sales: 'conversion_date', revenue: 'conversion_date' },
  generated_at: '2026-11-28T08:00:00Z',
  revision: 'f1',
  model_version: linear,
  attribution: caughtUp,
  finance: 'available',
  values: { state: 'available', reason: null },
  totals: [{ period: 'current', page_views: 4821, link_page_views: 1290, leads: { state: 'available', credited_leads: share('58.5'), lead_conversions: 60 }, sales: { state: 'available', ledger: 'available', items: [] } }],
  comparison: null,
  rows: [
    { recipient: 'campaign', group_ref: 'ramadan', registered: true, content_items: null, visits: { state: 'available', count: 684 }, leads: { credited_leads: share('40.5'), conversions: 41 }, sales: { state: 'available', items: [] } },
    { recipient: 'unknown', group_ref: null, registered: null, content_items: null, visits: { state: 'unsupported', count: null }, leads: { credited_leads: share('18'), conversions: 18 }, sales: { state: 'available', items: [] } },
  ],
  page,
  dependencies: [],
});

const roasRow = (objectId: string, given: Record<string, unknown> = {}) => ({
  level: 'campaign',
  object_id: objectId,
  campaign_id: objectId,
  adset_id: null,
  currency: 'EGP',
  exponent: 2,
  spend: money('1000.00'),
  credited_revenue: money('1650.00'),
  roas: share('1.65'),
  roas_reason: null,
  spend_state: 'complete',
  credited_leads: share('3'),
  cost_per_lead: share('333.33'),
  cost_per_lead_reason: null,
  ...given,
});
const roas = () => ({
  contract_version: '016b.1',
  family: 'roas',
  client_id: client.id,
  connection_id: meta.id,
  level: 'campaign',
  period,
  comparison_period: null,
  day_zone: 'Africa/Cairo',
  basis: 'account_local_days',
  generated_at: '2026-11-28T08:00:00Z',
  revision: 'r1',
  model_version: linear,
  attribution: caughtUp,
  finance: 'available',
  values: { state: 'available', reason: null },
  totals: [{ ...roasRow('act_42', { level: 'account' }), period: 'current' }],
  unmatched: [{ period: 'current', currency: 'EGP', exponent: 2, credited_revenue: money('74.10') }],
  unmatched_leads: [{ period: 'current', credited_leads: share('6.5') }],
  comparison: null,
  rows: [roasRow('1201'), roasRow('1209', { spend: money('0.00'), roas: null, roas_reason: 'zero_spend', cost_per_lead: null, cost_per_lead_reason: 'zero_spend' })],
  page,
  spend_source: {},
  dependencies: [],
});

const world = (routes: Record<string, unknown> = {}) => ({
  ...withClients([client], { [client.id]: [meta] }),
  [`GET /agencies/${agency.id}/clients/${client.id}/attribution/models`]: json(200, { versions: [first, linear], default_version_id: linear.id, active_limit: 5 }),
  [`${reports}/attribution`]: ({ url }: { url: string }) =>
    json(200, new URL(url).searchParams.get('view') === 'models' ? attribution({ view: 'models', model_version: null, model_versions: [linear, first], model_totals: [] }) : attribution()),
  [`${reports}/funnel`]: json(200, funnel()),
  [`${reports}/roas`]: json(200, roas()),
  [`GET /agencies/${agency.id}/clients/${client.id}/ad-spend`]: json(200, { rows: [{ object_id: '1201', name: 'Ramadan offers' }], next_after: null }),
  ...routes,
});

describe('the credit of a client', () => {
  it('reads under the client default model first, and names every group and the difference with the ledger', async () => {
    const server = fakeApi(world() as never);
    openApp(base);
    expect(await screen.findByRole('heading', { name: 'Credit by campaign' })).toBeInTheDocument();
    expect(screen.getByText(/30-day window\. Linear is the default for this client\./)).toBeInTheDocument();
    const asked = new URL(server.sent(`${reports}/attribution`)[0]?.url ?? '').searchParams;
    expect(asked.get('model_version')).toBe(linear.id);
    const table = within(screen.getByRole('region', { name: 'Credit by campaign' }));
    const ramadan = table.getByText('ramadan').closest('tr') as HTMLElement;
    expect(ramadan).toHaveTextContent('A Connect campaign');
    expect(ramadan).toHaveTextContent('40.5');
    expect(ramadan).toHaveTextContent('2.5');
    expect(ramadan).toHaveTextContent('1,200.00');
    expect(table.getByText('No journey could be linked, often because the visitor did not consent')).toBeInTheDocument();
    const reconciliation = within(screen.getByRole('heading', { name: 'Checked against the ledger' }).closest('article') as HTMLElement);
    expect(reconciliation.getByText('The difference comes from attribution catching up with newer sales.')).toBeInTheDocument();
  });

  it('keeps lead credit and says what needs financial access when sale values are refused', async () => {
    const refused = attribution({
      finance: 'permission_unavailable',
      totals: { sales: { state: 'permission_unavailable', reason: null, items: null }, leads: attribution().totals.leads },
      reconciliation: { state: 'permission_unavailable', reason: null, ledger: null, items: null },
      rows: [{ ...attribution().rows[0], sales: { state: 'permission_unavailable', items: null } }],
    });
    fakeApi(world({ [`${reports}/attribution`]: json(200, refused) }) as never);
    openApp(base);
    const table = within(await screen.findByRole('region', { name: 'Credit by campaign' }));
    const ramadan = table.getByText('ramadan').closest('tr') as HTMLElement;
    expect(ramadan).toHaveTextContent('40.5');
    expect(within(ramadan).getAllByText('Needs financial access')).toHaveLength(2);
    expect(screen.queryByText(/1,200\.00/)).not.toBeInTheDocument();
  });

  it('says that attribution has not been calculated instead of showing zero, and names a store that is behind', async () => {
    const notReady = attribution({
      values: { state: 'not_ready', reason: 'attribution_not_ready' },
      totals: { sales: { state: 'not_ready', reason: 'attribution_not_ready', items: null }, leads: { state: 'not_ready', reason: 'attribution_not_ready', items: null } },
      reconciliation: { state: 'not_ready', reason: 'attribution_not_ready', ledger: null, items: null },
      rows: [],
    });
    fakeApi(world({ [`${reports}/attribution`]: json(200, notReady) }) as never);
    openApp(base);
    expect((await screen.findAllByText(/has not been calculated for this client yet/)).length).toBeGreaterThan(0);
    expect(screen.queryByText('0.00')).not.toBeInTheDocument();
  });

  it('warns while the store is behind and keeps the published values', async () => {
    fakeApi(world({ [`${reports}/attribution`]: json(200, attribution({ attribution: { ...caughtUp, state: 'behind' } })) }) as never);
    openApp(base);
    expect(await screen.findByText(/Attribution is catching up with the newest conversions/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Credit by campaign' })).toHaveTextContent('1,200.00');
  });

  it('keeps the model and the grouping in the address and asks for them', async () => {
    const server = fakeApi(world() as never);
    const user = userEvent.setup();
    openApp(base);
    await screen.findByRole('heading', { name: 'Credit by campaign' });
    await user.click(screen.getByRole('button', { name: /Linear/ }));
    await user.click(await screen.findByRole('option', { name: /First click/ }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('model')).toBe(first.id));
    await user.click(screen.getByRole('button', { name: /^Campaign/ }));
    await user.click(await screen.findByRole('option', { name: 'Link' }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('group')).toBe('link'));
    await waitFor(() =>
      expect(
        server.sent(`${reports}/attribution`).some((request) => {
          const query = new URL(request.url).searchParams;
          return query.get('model_version') === first.id && query.get('group_by') === 'link';
        }),
      ).toBe(true),
    );
  });
});

describe('the funnel of a client', () => {
  it('counts each step on its own and names visits it cannot measure', async () => {
    fakeApi(world() as never);
    openApp(`${base}?tab=funnel`);
    const table = within(await screen.findByRole('region', { name: 'Steps by campaign' }));
    expect(table.getByText('ramadan').closest('tr')).toHaveTextContent('684');
    expect(table.getByText('Unknown').closest('tr')).toHaveTextContent('Not measured');
    expect(screen.getByText('4,821')).toBeInTheDocument();
    expect(screen.getByText(/the steps are not divided into one another/)).toBeInTheDocument();
  });
});

describe('the return on ad spend of a client', () => {
  it('names each campaign from the ad account, and says why a return is not worked out', async () => {
    fakeApi(world() as never);
    openApp(`${base}?tab=roas`);
    const named = await screen.findByText('Ramadan offers');
    expect(named.closest('tr')).toHaveTextContent('1.65');
    const unnamed = screen.getByText('1209').closest('tr') as HTMLElement;
    expect(within(unnamed).getAllByText('No spend, so no return')).toHaveLength(2);
    const unmatched = within(screen.getByRole('heading', { name: 'Not matched to this account' }).closest('article') as HTMLElement);
    expect(unmatched.getByText(/74\.10/)).toBeInTheDocument();
    expect(unmatched.getByText('6.5')).toBeInTheDocument();
  });
});
