import { createHash } from 'node:crypto';

import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { enter, everythingStored } from '../support/actions';
import { agency, asRole, client, fakeApi, json, refused, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-26T12:00:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
  forgetEverything();
});

const base = `/agencies/${agency.id}/clients/${client.id}`;
const trackingPath = `${base}/tracking`;
const publicKey = `pk_${'A'.repeat(43)}`;
const browserSource = {
  id: 'b5555555-5555-4555-8555-555555555555',
  agency_id: agency.id,
  client_id: client.id,
  kind: 'browser',
  name: 'Main website',
  status: 'active',
  public_key: publicKey,
  allowed_origins: ['https://shop.olive.example'],
  notice_sha256: 'a'.repeat(64),
  created_at: '2026-11-20T09:00:00Z',
};
const webhookSource = {
  ...browserSource,
  id: 'b6666666-6666-4666-8666-666666666666',
  kind: 'webhook',
  name: 'Order server',
  public_key: null,
  allowed_origins: null,
  notice_sha256: null,
};
const form = {
  id: 'f7777777-7777-4777-8777-777777777777',
  form_key: 'lead',
  version: 2,
  status: 'active',
  fields: { fields: [{ name: 'plan', input_type: 'text', autocomplete: '', label: 'Plan', data_class: 'form.option', options: ['basic', 'pro'] }] },
  updated_at: '2026-11-24T09:00:00Z',
};
const counters = [
  { day: '2026-11-25', channel: 'browser', outcome: 'accepted', reason: 'new', count: 41 },
  { day: '2026-11-25', channel: 'browser', outcome: 'suppressed', reason: 'consent_unknown', count: 7 },
  { day: '2026-11-26', channel: 'webhook', outcome: 'rejected', reason: 'signature_invalid', count: 2 },
  { day: '2026-11-26', channel: 'browser', outcome: 'minimized', reason: 'some_new_reason', count: 1 },
];
const token = `sbj_${'B'.repeat(43)}`;

type Routes = Parameters<typeof fakeApi>[0];

const tracking = (more: Routes = {}): Routes => ({
  ...withClients([client]),
  [`GET ${base}/ingestion-sources`]: json(200, [browserSource, webhookSource]),
  [`GET ${base}/collection-forms`]: json(200, [form]),
  [`GET ${base}/event-diagnostics`]: json(200, counters),
  [`GET ${base}/deletion-requests`]: json(200, []),
  ...more,
});

const card = async (title: string) => within((await screen.findByRole('heading', { name: title, level: 2 })).closest('section') as HTMLElement);
const rowOf = async (text: string) => within((await screen.findByText(text, { selector: '.c-table__primary' })).closest('tr') as HTMLElement);
const menuOf = async (user: UserEvent, name: string) => {
  await user.click((await rowOf(name)).getByRole('button', { name: `Actions for ${name}` }));
  return within(await screen.findByRole('menu'));
};
const cached = (queryClient: ReturnType<typeof openApp>['queryClient']) =>
  JSON.stringify(queryClient.getQueryCache().getAll().map((query) => query.state.data)) +
  JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => mutation.state.data));

describe('website tracking', () => {
  it('shows a manager the sources, the forms, what arrived and the erasures', async () => {
    fakeApi(tracking());
    openApp(trackingPath);

    const sources = await card('Sources');
    expect((await rowOf('Main website')).getByText('shop.olive.example')).toBeInTheDocument();
    expect(sources.getByText(publicKey)).toBeInTheDocument();
    expect((await rowOf('Order server')).getByText('A server')).toBeInTheDocument();
    expect((await rowOf('lead')).getByText('plan')).toBeInTheDocument();
    expect(await card('Erasure requests')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Website tracking', level: 1 })).toBeInTheDocument();
  });

  it('shows a reader what arrived only, and never asks for what the API keeps for managers', async () => {
    const server = fakeApi(asRole('analyst', tracking()));
    openApp(trackingPath);

    expect(await card('What arrived')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Sources' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Erasure requests' })).not.toBeInTheDocument();
    for (const list of ['ingestion-sources', 'collection-forms', 'deletion-requests']) expect(server.sent(`GET ${base}/${list}`), list).toHaveLength(0);
  });

  it('says when the server has no event collection set up', async () => {
    fakeApi(tracking({ [`GET ${base}/ingestion-sources`]: refused(503, 'collection_not_configured') }));
    openApp(trackingPath);
    expect(await screen.findByText('Event collection is not set up on this server yet.')).toBeInTheDocument();
  });
});

describe('a website source', () => {
  it('is created for its exact sites with the fingerprint of the notice, and then shows its install code', async () => {
    const notice = 'We use first-party analytics with your consent.\nYou can change your choice at any time.';
    const created = { ...browserSource, id: 'b8888888-8888-4888-8888-888888888888', name: 'Shop' };
    const server = fakeApi(tracking({ [`POST ${base}/ingestion-sources`]: json(201, { source: created, signing_secret: null }) }));
    const user = userEvent.setup();
    openApp(trackingPath);

    await user.click(await (await card('Sources')).findByRole('button', { name: 'New source' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'New source' }));
    expect(dialog.getByRole('radio', { name: /Website/ })).toBeChecked();
    await enter(user, dialog.getByLabelText('Name'), 'Shop');
    await enter(user, dialog.getByLabelText('Sites'), 'https://SHOP.olive.example/\nhttps://shop.olive.example:443');
    await enter(user, dialog.getByLabelText('Consent notice'), notice);
    await user.click(dialog.getByRole('button', { name: 'Create source' }));
    expect(await dialog.findByText('Write each site only once.')).toBeInTheDocument();

    await user.clear(dialog.getByLabelText('Sites'));
    await enter(user, dialog.getByLabelText('Sites'), 'https://SHOP.olive.example/\nhttp://localhost:3000');
    const digest = createHash('sha256').update(notice, 'utf8').digest('hex');
    expect(await dialog.findByText(digest)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Create source' }));

    await waitFor(() => expect(server.sent(`POST ${base}/ingestion-sources`)).toHaveLength(1));
    expect(server.sent(`POST ${base}/ingestion-sources`)[0]?.body).toEqual({
      kind: 'browser',
      name: 'Shop',
      allowed_origins: ['https://shop.olive.example', 'http://localhost:3000'],
      notice_sha256: digest,
    });
    const install = within(await screen.findByRole('dialog', { name: 'Install the tracker for Shop' }));
    expect(install.getByRole('textbox', { name: 'Public key' })).toHaveValue(publicKey);
    const code = (install.getByRole('textbox', { name: 'Code for the page' }) as HTMLTextAreaElement).value;
    expect(code).toContain('collector: "http://127.0.0.1:8000"');
    expect(code).toContain(`publicKey: "${publicKey}"`);
    expect(code).toContain('/assets/tracker-0.6.0/tracker.js');
  });

  it('is turned off only after saying what stops', async () => {
    const server = fakeApi(tracking({ [`PATCH ${base}/ingestion-sources/${browserSource.id}`]: json(200, { ...browserSource, status: 'disabled' }) }));
    const user = userEvent.setup();
    openApp(trackingPath);

    await user.click((await menuOf(user, 'Main website')).getByRole('menuitem', { name: 'Turn off' }));
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Turn this website source off?' }));
    await user.click(dialog.getByRole('button', { name: 'Turn off' }));
    await waitFor(() => expect(server.sent(`PATCH ${base}/ingestion-sources/${browserSource.id}`)[0]?.body).toEqual({ status: 'disabled' }));
  });

  it('keeps its notice when only its name changes', async () => {
    const server = fakeApi(tracking({ [`PATCH ${base}/ingestion-sources/${browserSource.id}`]: json(200, browserSource) }));
    const user = userEvent.setup();
    openApp(trackingPath);

    await user.click((await menuOf(user, 'Main website')).getByRole('menuitem', { name: 'Change' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Change Main website' }));
    expect(dialog.getByText('a'.repeat(64))).toBeInTheDocument();
    await user.clear(dialog.getByLabelText('Name'));
    await enter(user, dialog.getByLabelText('Name'), 'Shop website');
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(server.sent(`PATCH ${base}/ingestion-sources/${browserSource.id}`)).toHaveLength(1));
    expect(server.sent(`PATCH ${base}/ingestion-sources/${browserSource.id}`)[0]?.body).toEqual({ name: 'Shop website' });
  });
});

describe('a webhook source', () => {
  const secret = 'whsec_synthetic-signing-secret-shown-once';

  it('shows its signing secret once, with where to send and how to sign, and keeps it nowhere', async () => {
    const created = { ...webhookSource, id: 'b9999999-9999-4999-8999-999999999999', name: 'Bookings server' };
    const server = fakeApi(tracking({ [`POST ${base}/ingestion-sources`]: json(201, { source: created, signing_secret: secret }) }));
    const user = userEvent.setup();
    const { queryClient } = openApp(trackingPath);

    await user.click(await (await card('Sources')).findByRole('button', { name: 'New source' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'New source' }));
    await user.click(dialog.getByRole('radio', { name: /Server webhook/ }));
    expect(dialog.queryByLabelText('Sites')).not.toBeInTheDocument();
    await enter(user, dialog.getByLabelText('Name'), 'Bookings server');
    await user.click(dialog.getByRole('button', { name: 'Create source' }));
    await waitFor(() => expect(server.sent(`POST ${base}/ingestion-sources`)[0]?.body).toEqual({ kind: 'webhook', name: 'Bookings server' }));

    const shown = within(await screen.findByRole('dialog', { name: 'Signing secret of Bookings server' }));
    expect(shown.getByRole('textbox', { name: 'Signing secret' })).toHaveValue(secret);
    expect(shown.getByRole('textbox', { name: 'Webhook address' })).toHaveValue(`http://127.0.0.1:8000/webhooks/v1/${created.id}/events`);
    await user.click(shown.getByRole('button', { name: 'I have copied it' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain(secret);
    expect(cached(queryClient)).not.toContain(secret);
    expect(everythingStored()).not.toContain(secret);
  });

  it('replaces its secret after asking, and says the previous one works for a day', async () => {
    const server = fakeApi(tracking({ [`POST ${base}/ingestion-sources/${webhookSource.id}/secret`]: json(201, { signing_secret: secret }) }));
    const user = userEvent.setup();
    const { queryClient } = openApp(trackingPath);

    await user.click((await menuOf(user, 'Order server')).getByRole('menuitem', { name: 'Replace signing secret' }));
    const ask = within(await screen.findByRole('alertdialog', { name: 'Replace the signing secret?' }));
    await user.click(ask.getByRole('button', { name: 'Replace signing secret' }));
    const shown = within(await screen.findByRole('dialog', { name: 'New signing secret of Order server' }));
    expect(shown.getByText(/The previous secret keeps working for 24 hours/)).toBeInTheDocument();
    expect(shown.getByRole('textbox', { name: 'Signing secret' })).toHaveValue(secret);
    expect(server.sent(`POST ${base}/ingestion-sources/${webhookSource.id}/secret`)).toHaveLength(1);
    await user.click(shown.getByRole('button', { name: 'I have copied it' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(cached(queryClient)).not.toContain(secret);
  });
});

describe('a form', () => {
  it('is registered field by field, and an option field lists its choices', async () => {
    const server = fakeApi(tracking({ [`PUT ${base}/collection-forms/booking`]: json(200, { ...form, form_key: 'booking', version: 1 }) }));
    const user = userEvent.setup();
    openApp(trackingPath);

    await user.click(await (await card('Forms')).findByRole('button', { name: 'Register form' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Register form' }));
    await enter(user, dialog.getByLabelText('Form'), 'Booking');
    await enter(user, dialog.getByLabelText('Name in the page'), 'menu');
    await user.click(dialog.getByRole('button', { name: 'Register' }));
    expect(await dialog.findByText('List the choices of this field.')).toBeInTheDocument();

    await enter(user, dialog.getByLabelText('Choices'), 'iftar\nsuhoor, iftar');
    await user.click(dialog.getByRole('button', { name: 'Register' }));
    expect(await dialog.findByText('Write each choice only once.')).toBeInTheDocument();
    await user.clear(dialog.getByLabelText('Choices'));
    await enter(user, dialog.getByLabelText('Choices'), 'iftar\nsuhoor');

    await user.click(dialog.getByRole('button', { name: 'Add field' }));
    const second = within(dialog.getByRole('group', { name: 'Field 2' }));
    await enter(user, second.getByLabelText('Name in the page'), 'guests');
    await user.click(second.getByRole('button', { name: /What it holds/ }));
    await user.click(await screen.findByRole('option', { name: /A number/ }));
    await user.click(dialog.getByRole('button', { name: 'Register' }));

    await waitFor(() => expect(server.sent(`PUT ${base}/collection-forms/booking`)).toHaveLength(1));
    expect(server.sent(`PUT ${base}/collection-forms/booking`)[0]?.body).toEqual({
      fields: [
        { name: 'menu', input_type: 'text', autocomplete: '', label: '', data_class: 'form.option', options: ['iftar', 'suhoor'] },
        { name: 'guests', input_type: 'text', autocomplete: '', label: '', data_class: 'form.quantity', options: [] },
      ],
    });
  });
});

describe('what arrived', () => {
  it('reads the last seven days, adds them up and says each reason in words where it can', async () => {
    const server = fakeApi(tracking());
    const user = userEvent.setup();
    openApp(trackingPath);

    const arrived = await card('What arrived');
    await waitFor(() => expect(server.sent(`GET ${base}/event-diagnostics`)).toHaveLength(1));
    const asked = new URL(server.sent(`GET ${base}/event-diagnostics`)[0]?.url ?? '').searchParams;
    expect([asked.get('start'), asked.get('end')]).toEqual(['2026-11-20', '2026-11-26']);
    expect(within(arrived.getByText('Kept', { selector: 'dt' }).closest('div') as HTMLElement).getByText('41')).toBeInTheDocument();
    expect(within(arrived.getByText('Held back without consent').closest('div') as HTMLElement).getByText('7')).toBeInTheDocument();
    expect(arrived.getByText('No consent asked yet')).toBeInTheDocument();
    expect(arrived.getByText('Wrong signature')).toBeInTheDocument();
    // A reason the interface has no words for is shown as the API's code, not hidden.
    expect(arrived.getByText('some_new_reason')).toBeInTheDocument();

    await user.click(within(arrived.getByRole('group', { name: 'Period' })).getByRole('button', { name: '30 days' }));
    await waitFor(() => expect(server.sent(`GET ${base}/event-diagnostics`)).toHaveLength(2));
    const wider = new URL(server.sent(`GET ${base}/event-diagnostics`)[1]?.url ?? '').searchParams;
    expect([wider.get('start'), wider.get('end')]).toEqual(['2026-10-28', '2026-11-26']);
  });
});

describe('an erasure', () => {
  it('checks the token, asks as an alert, and says when the visitor is unknown', async () => {
    const server = fakeApi(tracking({ [`POST ${base}/deletion-requests`]: refused(403, 'access_denied') }));
    const user = userEvent.setup();
    openApp(trackingPath);

    await user.click(await (await card('Erasure requests')).findByRole('button', { name: 'Erase a visitor' }));
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Erase a visitor?' }));
    expect(dialog.getByText(/It cannot be undone/)).toBeInTheDocument();
    await enter(user, dialog.getByRole('textbox', { name: 'Visitor token' }), 'sbj_short');
    await user.click(dialog.getByRole('button', { name: 'Erase visitor' }));
    expect(await dialog.findByText(/A visitor token is sbj_ followed by 43/)).toBeInTheDocument();
    expect(server.sent(`POST ${base}/deletion-requests`)).toHaveLength(0);

    await user.clear(dialog.getByRole('textbox', { name: 'Visitor token' }));
    await enter(user, dialog.getByRole('textbox', { name: 'Visitor token' }), token);
    await user.click(dialog.getByRole('checkbox', { name: /also objects/ }));
    await user.click(dialog.getByRole('button', { name: 'Erase visitor' }));
    expect(await dialog.findByText('No visitor of this client has this token or event.')).toBeInTheDocument();
    expect(server.sent(`POST ${base}/deletion-requests`)[0]?.body).toEqual({ subject_token: token, objected: true });
  });

  it('erases by an event identifier and lists what was erased', async () => {
    // Letters in the identifier, so that writing it in capitals changes it.
    const eventId = 'abcdef12-0000-4000-8000-00000000000a';
    let erasures: unknown[] = [];
    const done = {
      id: 'e9999999-9999-4999-8999-999999999999',
      requester_kind: 'agency_admin',
      status: 'completed',
      objected: false,
      received_at: '2026-11-26T11:59:00Z',
      completed_at: '2026-11-26T11:59:01Z',
      target_outcomes: { collected_events: 'done', consent_records: 'done', collection_subjects: 'done', booking_links: 'not_applicable' },
    };
    const server = fakeApi(
      tracking({
        [`GET ${base}/deletion-requests`]: () => json(200, erasures),
        [`POST ${base}/deletion-requests`]: () => {
          erasures = [done];
          return json(201, done);
        },
      }),
    );
    const user = userEvent.setup();
    openApp(trackingPath);

    await user.click(await (await card('Erasure requests')).findByRole('button', { name: 'Erase a visitor' }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.click(dialog.getByRole('radio', { name: 'Event identifier' }));
    await enter(user, dialog.getByRole('textbox', { name: 'Event identifier' }), eventId.toUpperCase());
    await user.click(dialog.getByRole('button', { name: 'Erase visitor' }));
    await waitFor(() => expect(server.sent(`POST ${base}/deletion-requests`)[0]?.body).toEqual({ event_id: eventId, objected: false }));
    expect(await screen.findByText('The visitor was erased. Their token and events are refused from now on.')).toBeInTheDocument();
    const row = within((await screen.findByText('An owner or admin of the agency')).closest('tr') as HTMLElement);
    expect(row.getByText('Done')).toBeInTheDocument();
    expect(row.getByText('events, consent records, visitor')).toBeInTheDocument();
  });
});
