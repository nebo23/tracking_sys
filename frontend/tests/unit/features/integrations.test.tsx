import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { pendingConnection } from '@/features/connections/pendingConnection';
import { goTo } from '@/lib/browser';

import { enter, everythingStored } from '../support/actions';
import { agency, asRole, client, connection, fakeApi, json, refused, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

// Leaving the application for a provider is recorded instead of done.
vi.mock('@/lib/browser', async (original) => ({ ...(await original<typeof import('@/lib/browser')>()), goTo: vi.fn() }));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-26T12:00:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
  vi.mocked(goTo).mockClear();
  forgetEverything();
});

const base = `/agencies/${agency.id}/clients/${client.id}`;
const page = `${base}/integrations`;
const stamp = { created_at: '2026-11-20T09:00:00Z', updated_at: '2026-11-20T09:00:00Z' };

const paymob = {
  id: 'a1111111-1111-4111-8111-111111111111',
  provider: 'paymob',
  region: 'egypt',
  name: 'Online shop',
  status: 'active',
  callback_path: `/payments/paymob/callback/ppk_${'P'.repeat(43)}`,
  live_integration_ids: [4567890, 4567891],
  ...stamp,
};
const calcom = { id: 'a2222222-2222-4222-8222-222222222222', kind: 'cal_com', name: 'Bookings', status: 'active', callback_path: `/integrations/cal-com/isk_${'C'.repeat(43)}`, ...stamp };
const rule = { id: 'a3333333-3333-4333-8333-333333333333', pipeline: 'Sales', stage: 'Closed won', outcome: 'won', status: 'active', ...stamp };
const pending = { id: 'a4444444-4444-4444-8444-444444444444', phone_number_id: '106540352242922', name: 'Orders line', status: 'pending', verified_at: null, ...stamp };
const verified = { ...pending, id: 'a5555555-5555-4555-8555-555555555555', name: 'Support line', phone_number_id: '106540352242923', status: 'active', verified_at: '2026-11-21T09:00:00Z' };
const dataset = connection({ id: 'd2222222-2222-4222-8222-222222222222', provider: 'meta_capi', account: { external_account_id: '1234567890', label: 'Olive pixel' } });
const destination = {
  id: 'a6666666-6666-4666-8666-666666666666',
  connection_id: dataset.id,
  event_name: 'Purchase',
  test_event_code: 'TEST123',
  enabled: false,
  actions: { update: true },
  ...stamp,
};
const delivery = (given: Record<string, unknown> = {}) => ({
  id: 'a7777777-7777-4777-8777-777777777777',
  destination_id: destination.id,
  event_name: 'Purchase',
  action_source: 'website',
  event_time: '2026-11-25T10:00:00Z',
  status: 'rejected',
  reason: null,
  rejection_class: 'configuration',
  value: '250.00',
  currency: 'EGP',
  attempts: 1,
  requeues: 0,
  next_attempt_at: null,
  deadline: '2026-12-02T09:00:00Z',
  created_at: '2026-11-25T10:00:01Z',
  delivered_at: null,
  ended_at: '2026-11-25T10:00:05Z',
  actions: { requeue: true, dismiss: true },
  ...given,
});

type Routes = Parameters<typeof fakeApi>[0];

const serving = (more: Routes = {}): Routes => ({
  ...withClients([client], { [client.id]: [dataset] }),
  [`GET ${base}/payment-sources`]: json(200, [paymob]),
  [`GET ${base}/integration-sources`]: json(200, [calcom]),
  [`GET ${base}/bookings`]: json(200, { totals: { requested: 1, scheduled: 6, cancelled: 2, rejected: 0, completed: 9, linked: 4 }, bookings: [] }),
  [`GET ${base}/crm/stage-rules`]: json(200, [rule]),
  [`GET ${base}/crm/deals`]: json(200, { totals: { open: 12, won_verified: 3, won_unverified: 1, lost: 5 }, deals: [], has_more: false, next_after: null }),
  [`GET ${base}/whatsapp-numbers`]: json(200, [pending, verified]),
  [`GET ${base}/whatsapp/referrals`]: json(200, {
    since: '2026-10-28',
    until: '2026-11-26',
    total: 30,
    unknown: 8,
    sources: [{ source_type: 'ad', source_id: '120210000000001', messages: 22, with_click_id: 20 }],
  }),
  [`GET ${base}/conversion-destinations`]: json(200, [destination]),
  [`GET ${base}/conversion-deliveries`]: json(200, [delivery()]),
  ...more,
});

const tab = async (user: UserEvent, name: string) => user.click(await screen.findByRole('tab', { name }));
const card = async (title: string) => within((await screen.findByRole('heading', { name: title, level: 2 })).closest('section') as HTMLElement);
const rowOf = async (text: string) => within((await screen.findByText(text, { selector: '.c-table__primary' })).closest('tr') as HTMLElement);
const menuOf = async (user: UserEvent, row: ReturnType<typeof within>, name: string) => {
  await user.click(row.getByRole('button', { name: `Actions for ${name}` }));
  return within(await screen.findByRole('menu'));
};
const cached = (queryClient: ReturnType<typeof openApp>['queryClient']) =>
  JSON.stringify(queryClient.getQueryCache().getAll().map((query) => query.state.data)) +
  JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => [mutation.state.data, mutation.state.variables]));

describe('the integrations of a client', () => {
  it('give a manager the payments, bookings and CRM, WhatsApp and Meta conversions', async () => {
    fakeApi(serving());
    openApp(page);
    const tabs = within(await screen.findByRole('tablist', { name: 'Integrations' }));
    expect(tabs.getAllByRole('tab').map((item) => item.textContent)).toEqual(['Payments', 'Bookings and CRM', 'WhatsApp', 'Meta conversions']);
    expect(await card('Paymob payments')).toBeTruthy();
  });

  it('show a reader what the tools delivered, and never ask for what only managers may list', async () => {
    const server = fakeApi(asRole('analyst', serving()));
    const user = userEvent.setup();
    openApp(page);

    const tabs = within(await screen.findByRole('tablist', { name: 'Integrations' }));
    expect(tabs.getAllByRole('tab').map((item) => item.textContent)).toEqual(['Bookings and CRM', 'WhatsApp', 'Meta conversions']);
    const bookings = await card('Bookings');
    expect(within(bookings.getByText('Completed').closest('div') as HTMLElement).getByText('9')).toBeInTheDocument();
    expect(within((await card('CRM stages')).getByText('Won and paid').closest('div') as HTMLElement).getByText('3')).toBeInTheDocument();
    await tab(user, 'WhatsApp');
    expect(await card('Conversations started by ads')).toBeTruthy();
    await tab(user, 'Meta conversions');
    expect(await screen.findByText('Olive pixel')).toBeInTheDocument();
    for (const list of ['payment-sources', 'integration-sources', 'crm/stage-rules', 'whatsapp-numbers']) expect(server.sent(`GET ${base}/${list}`), list).toHaveLength(0);
  });
});

describe('a Paymob source', () => {
  const secret = 'synthetic-hmac-secret-0123456789';

  it('is added with its live integrations, and its secret is kept nowhere', async () => {
    const server = fakeApi(serving({ [`POST ${base}/payment-sources`]: json(201, paymob) }));
    const user = userEvent.setup();
    const { queryClient } = openApp(page);

    await user.click(await (await card('Paymob payments')).findByRole('button', { name: 'Add Paymob source' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Add Paymob source' }));
    await enter(user, dialog.getByLabelText('Name'), 'Online shop');
    await enter(user, dialog.getByLabelText('HMAC secret'), secret);
    await enter(user, dialog.getByLabelText('Live integration IDs'), '4567890, test');
    await user.click(dialog.getByRole('button', { name: 'Add source' }));
    expect(await dialog.findByText('An integration ID is a whole number, such as 4567890.')).toBeInTheDocument();
    expect(dialog.getByText(/Never list a test integration/)).toBeInTheDocument();

    await user.clear(dialog.getByLabelText('Live integration IDs'));
    await enter(user, dialog.getByLabelText('Live integration IDs'), '4567890 4567891');
    await user.click(dialog.getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(server.sent(`POST ${base}/payment-sources`)).toHaveLength(1));
    expect(server.sent(`POST ${base}/payment-sources`)[0]?.body).toEqual({
      provider: 'paymob',
      region: 'egypt',
      name: 'Online shop',
      hmac_secret: secret,
      live_integration_ids: [4567890, 4567891],
    });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(cached(queryClient)).not.toContain(secret);
    expect(everythingStored()).not.toContain(secret);
  });

  it('shows where Paymob calls back, and replaces its secret', async () => {
    const server = fakeApi(serving({ [`PUT ${base}/payment-sources/${paymob.id}/secret`]: json(200, paymob) }));
    const user = userEvent.setup();
    openApp(page);

    const source = within((await screen.findByRole('heading', { name: 'Online shop', level: 3 })).closest('article') as HTMLElement);
    expect(source.getByRole('textbox', { name: 'Callback address' })).toHaveValue(`http://127.0.0.1:8000${paymob.callback_path}`);
    expect(source.getByText('Egypt · 2 live integrations')).toBeInTheDocument();
    await user.click((await menuOf(user, source, 'Online shop')).getByRole('menuitem', { name: 'Replace secret' }));
    const dialog = within(await screen.findByRole('dialog'));
    await enter(user, dialog.getByLabelText('HMAC secret'), 'short');
    await user.click(dialog.getByRole('button', { name: 'Save secret' }));
    expect(await dialog.findByText('Use 16 to 256 letters, digits and symbols, without spaces.')).toBeInTheDocument();
    await user.clear(dialog.getByLabelText('HMAC secret'));
    await enter(user, dialog.getByLabelText('HMAC secret'), secret);
    await user.click(dialog.getByRole('button', { name: 'Save secret' }));
    await waitFor(() => expect(server.sent(`PUT ${base}/payment-sources/${paymob.id}/secret`)[0]?.body).toEqual({ hmac_secret: secret }));
  });

  it('says at once when the server has payments switched off', async () => {
    fakeApi(serving({ [`GET ${base}/payment-sources`]: refused(503, 'payments_unavailable') }));
    openApp(page);
    expect(await screen.findByText('Paymob payments are not switched on on this server.')).toBeInTheDocument();
  });
});

describe('booking and CRM sources', () => {
  it('add Cal.com with its own secret, then say what to set in Cal.com', async () => {
    const created = { ...calcom, id: 'a8888888-8888-4888-8888-888888888888', name: 'Clinic bookings' };
    const server = fakeApi(serving({ [`POST ${base}/integration-sources`]: json(201, { source: created, signing_secret: null }) }));
    const user = userEvent.setup();
    openApp(`${page}?tab=bookings`);

    await user.click(await (await card('Booking and CRM sources')).findByRole('button', { name: 'Add source' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Add source' }));
    expect(dialog.getByRole('radio', { name: /Cal\.com/ })).toBeChecked();
    await enter(user, dialog.getByLabelText('Name'), 'Clinic bookings');
    await enter(user, dialog.getByLabelText('Cal.com secret'), 'cal-com-secret-0123456789');
    await user.click(dialog.getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(server.sent(`POST ${base}/integration-sources`)[0]?.body).toEqual({ kind: 'cal_com', name: 'Clinic bookings', secret: 'cal-com-secret-0123456789' }));
    const setup = within(await screen.findByRole('dialog', { name: 'Set up Clinic bookings in Cal.com' }));
    expect(setup.getByRole('textbox', { name: 'Callback address' })).toHaveValue(`http://127.0.0.1:8000${calcom.callback_path}`);
    expect(setup.getByText(/Booking Created, Requested, Rescheduled, Cancelled, Rejected and Meeting Ended/)).toBeInTheDocument();
  });

  it('add a signed webhook whose issued secret is shown once and kept nowhere', async () => {
    const issued = 'whsec_synthetic-integration-secret';
    const created = { ...calcom, id: 'a9999999-9999-4999-8999-999999999999', kind: 'signed_webhook', name: 'CRM', callback_path: `/integrations/webhook/isk_${'W'.repeat(43)}` };
    const server = fakeApi(serving({ [`POST ${base}/integration-sources`]: json(201, { source: created, signing_secret: issued }) }));
    const user = userEvent.setup();
    const { queryClient } = openApp(`${page}?tab=bookings`);

    await user.click(await (await card('Booking and CRM sources')).findByRole('button', { name: 'Add source' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Add source' }));
    await user.click(dialog.getByRole('radio', { name: /Signed webhook/ }));
    expect(dialog.queryByLabelText('Cal.com secret')).not.toBeInTheDocument();
    await enter(user, dialog.getByLabelText('Name'), 'CRM');
    await user.click(dialog.getByRole('button', { name: 'Add source' }));
    await waitFor(() => expect(server.sent(`POST ${base}/integration-sources`)[0]?.body).toEqual({ kind: 'signed_webhook', name: 'CRM' }));
    const shown = within(await screen.findByRole('dialog', { name: 'Signing secret of CRM' }));
    expect(shown.getByRole('textbox', { name: 'Signing secret' })).toHaveValue(issued);
    await user.click(shown.getByRole('button', { name: 'I have copied it' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain(issued);
    expect(cached(queryClient)).not.toContain(issued);
  });

  it('count a CRM stage as won or lost by rule', async () => {
    const server = fakeApi(
      serving({
        [`POST ${base}/crm/stage-rules`]: refused(409, 'state_conflict'),
        [`PATCH ${base}/crm/stage-rules/${rule.id}`]: json(200, { ...rule, outcome: 'lost' }),
      }),
    );
    const user = userEvent.setup();
    openApp(`${page}?tab=bookings`);

    const row = await rowOf('Closed won');
    expect(row.getByText('Won')).toBeInTheDocument();
    await user.click((await menuOf(user, row, 'Sales · Closed won')).getByRole('menuitem', { name: 'Count as lost' }));
    await waitFor(() => expect(server.sent(`PATCH ${base}/crm/stage-rules/${rule.id}`)[0]?.body).toEqual({ outcome: 'lost' }));

    await user.click(await (await card('CRM stages')).findByRole('button', { name: 'Add stage rule' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Add stage rule' }));
    await enter(user, dialog.getByLabelText('Pipeline'), 'Sales');
    await enter(user, dialog.getByLabelText('Stage'), 'Closed won');
    await user.click(dialog.getByRole('button', { name: 'Add rule' }));
    expect(await dialog.findByText('This pipeline and stage already have a rule.')).toBeInTheDocument();
    expect(server.sent(`POST ${base}/crm/stage-rules`)[0]?.body).toEqual({ pipeline: 'Sales', stage: 'Closed won', outcome: 'won' });
  });
});

describe('a WhatsApp number', () => {
  it('is registered as a claim the operator verifies, and only a verified one can be turned off', async () => {
    const server = fakeApi(
      serving({
        [`POST ${base}/whatsapp-numbers`]: json(201, pending),
        [`PATCH ${base}/whatsapp-numbers/${verified.id}`]: refused(409, 'verification_required'),
      }),
    );
    const user = userEvent.setup();
    openApp(`${page}?tab=whatsapp`);

    const claim = await rowOf('Orders line');
    expect(claim.getByText('Waiting for verification')).toBeInTheDocument();
    expect((await menuOf(user, claim, 'Orders line')).getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Rename']);
    await user.keyboard('{Escape}');

    await user.click((await menuOf(user, await rowOf('Support line'), 'Support line')).getByRole('menuitem', { name: 'Turn off' }));
    const ask = within(await screen.findByRole('alertdialog', { name: 'Turn Support line off?' }));
    await user.click(ask.getByRole('button', { name: 'Turn off' }));
    expect(await ask.findByText('The Connect operator has not verified this number yet, so it cannot be switched.')).toBeInTheDocument();
    await user.click(ask.getByRole('button', { name: 'Keep it on' }));

    await user.click(await (await card('WhatsApp numbers')).findByRole('button', { name: 'Register number' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Register number' }));
    expect(dialog.getByText(/waits until the Connect operator confirms/)).toBeInTheDocument();
    await enter(user, dialog.getByLabelText('Phone number ID'), '+20 100 000');
    await enter(user, dialog.getByLabelText('Name'), 'Sales line');
    await user.click(dialog.getByRole('button', { name: 'Register' }));
    expect(await dialog.findByText('A phone number ID is a whole number of up to 32 digits.')).toBeInTheDocument();
    await user.clear(dialog.getByLabelText('Phone number ID'));
    await enter(user, dialog.getByLabelText('Phone number ID'), '106540352242924');
    await user.click(dialog.getByRole('button', { name: 'Register' }));
    await waitFor(() => expect(server.sent(`POST ${base}/whatsapp-numbers`)[0]?.body).toEqual({ phone_number_id: '106540352242924', name: 'Sales line' }));
  });

  it('counts the conversations that ads started', async () => {
    fakeApi(serving());
    const user = userEvent.setup();
    openApp(page);
    await tab(user, 'WhatsApp');
    const referrals = await card('Conversations started by ads');
    // The API's until day is not counted, so the range ends the day before it.
    expect(referrals.getByText('From Oct 28, 2026 through Nov 25, 2026, in UTC.')).toBeInTheDocument();
    expect(within(referrals.getByText('From an ad or post').closest('div') as HTMLElement).getByText('22')).toBeInTheDocument();
    const row = within(referrals.getByText('An ad').closest('tr') as HTMLElement);
    expect(row.getByText('120210000000001')).toBeInTheDocument();
    expect(row.getByText('20')).toBeInTheDocument();
  });
});

describe('Meta conversions', () => {
  it('turn a destination on, and add one only for a dataset that has none', async () => {
    const server = fakeApi(serving({ [`PATCH ${base}/conversion-destinations/${destination.id}`]: json(200, { ...destination, enabled: true }) }));
    const user = userEvent.setup();
    openApp(`${page}?tab=conversions`);

    const row = await rowOf('Olive pixel');
    expect(row.getByText('Test events, code TEST123')).toBeInTheDocument();
    expect(row.getByText('Off')).toBeInTheDocument();
    // The only dataset has its destination already.
    expect((await card('Meta conversions')).queryByRole('button', { name: 'Add destination' })).not.toBeInTheDocument();
    await user.click((await menuOf(user, row, 'Olive pixel')).getByRole('menuitem', { name: 'Turn on' }));
    await waitFor(() => expect(server.sent(`PATCH ${base}/conversion-destinations/${destination.id}`)[0]?.body).toEqual({ clear_test_event_code: false, enabled: true }));
  });

  it('add a destination for a new dataset, off, with the Purchase event', async () => {
    const server = fakeApi(
      serving({
        [`GET ${base}/conversion-destinations`]: json(200, []),
        [`POST ${base}/conversion-destinations`]: json(201, destination),
      }),
    );
    const user = userEvent.setup();
    openApp(`${page}?tab=conversions`);

    await user.click(await (await card('Meta conversions')).findByRole('button', { name: 'Add destination' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Add destination' }));
    expect(dialog.getByRole('textbox', { name: 'Event name' })).toHaveValue('Purchase');
    expect(dialog.getByText(/A new destination starts off/)).toBeInTheDocument();
    await enter(user, dialog.getByLabelText('Test event code'), 'TEST 1');
    await user.click(dialog.getByRole('button', { name: 'Add destination' }));
    expect(await dialog.findByText('Use up to 32 letters and digits.')).toBeInTheDocument();
    await user.clear(dialog.getByLabelText('Test event code'));
    await user.click(dialog.getByRole('button', { name: 'Add destination' }));
    await waitFor(() => expect(server.sent(`POST ${base}/conversion-destinations`)[0]?.body).toEqual({ connection_id: dataset.id, event_name: 'Purchase', test_event_code: null }));
  });

  it('connect a dataset by its number and come back to this page', async () => {
    const server = fakeApi(serving({ [`POST ${base}/connections`]: json(201, { authorization_url: 'https://www.facebook.com/dialog/oauth?state=synthetic' }) }));
    const user = userEvent.setup();
    openApp(`${page}?tab=conversions`);

    await user.click(await (await card('Meta conversions')).findByRole('button', { name: 'Connect a dataset' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Connect an account' }));
    // A dataset receives the sales Connect sends; the dialog does not speak of reading it.
    expect(dialog.getByText(/allow Connect to send the verified sales of Olive & Thyme to the dataset/)).toBeInTheDocument();
    expect(dialog.getAllByRole('radio').map((item) => (item.closest('label') as HTMLElement).textContent)).toEqual([expect.stringContaining('Meta conversions')]);
    await enter(user, dialog.getByLabelText('Dataset ID'), 'act_123');
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    expect(await dialog.findByText('Enter the dataset ID: digits only.')).toBeInTheDocument();
    await user.clear(dialog.getByLabelText('Dataset ID'));
    await enter(user, dialog.getByLabelText('Dataset ID'), '1234567890');
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    await waitFor(() => expect(goTo).toHaveBeenCalledWith('https://www.facebook.com/dialog/oauth?state=synthetic'));
    expect(server.sent(`POST ${base}/connections`)[0]?.body).toEqual({ provider: 'meta_capi', account: '1234567890' });
    expect(pendingConnection.get()).toEqual({ agencyId: agency.id, clientId: client.id, place: 'integrations' });
  });

  it('return from Meta to the conversions of the client that was connecting', async () => {
    fakeApi(serving());
    pendingConnection.set({ agencyId: agency.id, clientId: client.id, place: 'integrations' });
    const { router } = openApp(`/connections/complete?result=connected&connection_id=${dataset.id}`);
    await waitFor(() => expect(router.state.location.pathname).toBe(page));
    expect(await screen.findByText('Add a destination for the dataset to start sending its conversions.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Meta conversions', selected: true })).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.search).toEqual({ tab: 'conversions' }));
    expect(pendingConnection.get()).toBeNull();
  });

  it('list deliveries with their value and what Meta answered, and dismiss one after asking', async () => {
    const server = fakeApi(serving({ [`POST ${base}/conversion-deliveries/${delivery().id}/dismiss`]: json(200, delivery({ status: 'dismissed', actions: { requeue: false, dismiss: false } })) }));
    const user = userEvent.setup();
    openApp(`${page}?tab=conversions`);

    const deliveries = await card('Deliveries');
    const row = within((await deliveries.findByText('Refused by Meta')).closest('tr') as HTMLElement);
    expect(row.getByText('Meta refused the settings of the destination')).toBeInTheDocument();
    expect(row.getByText(/250\.00/)).toBeInTheDocument();
    await user.click((await menuOf(user, row, 'Purchase')).getByRole('menuitem', { name: 'Dismiss' }));
    const ask = within(await screen.findByRole('alertdialog', { name: 'Dismiss this delivery?' }));
    await user.click(ask.getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(server.sent(`POST ${base}/conversion-deliveries/${delivery().id}/dismiss`)).toHaveLength(1));
  });

  it('say that deliveries need financial access when the API refuses them', async () => {
    fakeApi(asRole('analyst', serving({ [`GET ${base}/conversion-deliveries`]: refused(403, 'access_denied') })));
    openApp(`${page}?tab=conversions`);
    expect(await screen.findByText('Deliveries carry the value of each sale. People with financial access to this client see them.')).toBeInTheDocument();
  });
});
