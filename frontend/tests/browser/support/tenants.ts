import { randomBytes, randomUUID } from 'node:crypto';

import type { Page } from '@playwright/test';

import { expectStatus, send, signedIn, type Person, type Signed } from './api.ts';
import {
  approveAtProvider,
  defineAdAccount,
  runAttributionWorker,
  runConnectorWorker,
  stack,
  type BackendEnvironment,
  type StandInAccount,
  type StandInAdObject,
} from './stack.ts';

// Clients, people and connections for the journeys, prepared through the API as the application
// itself would. Everything is synthetic, and the stand-in providers contact nobody.

function runningStack(): { python: string; backend: BackendEnvironment } {
  const python = process.env.CONNECT_E2E_PYTHON;
  const backend = process.env.CONNECT_E2E_BACKEND;
  if (!python || !backend) throw new Error('The disposable stack is not running (see global-setup.ts).');
  return { python, backend: JSON.parse(backend) as BackendEnvironment };
}

/** A person, or a session that person already has. */
type Who = Person | Signed;

/**
 * Does a piece of preparation as a person. The API limits how often an account signs in, so a
 * journey that prepares several things signs in once (`signedIn`) and passes that session on.
 */
async function as<T>(who: Who, work: (signed: Signed) => Promise<T>): Promise<T> {
  if ('cookie' in who) return work(who);
  const signed = await signedIn(who);
  try {
    return await work(signed);
  } finally {
    await send('POST /auth/logout', undefined, signed);
  }
}

/** Adds a client to the agency. Returns the client's id. */
export function withClient(owner: Who, agencyId: string, name: string): Promise<string> {
  return as(owner, async (signed) => {
    const response = await send(`POST /agencies/${agencyId}/clients`, { name }, signed);
    await expectStatus(response, 201, 'Adding the client');
    return ((await response.json()) as { id: string }).id;
  });
}

interface Grant {
  client_id: string;
  can_view_financials?: boolean;
}

/** Has the owner invite an address with a role and the clients it may open. The invitation arrives as captured mail. */
export function inviteAs(owner: Who, agencyId: string, email: string, role: 'admin' | 'analyst' | 'client_viewer', clients: Grant[] = []): Promise<void> {
  return as(owner, async (signed) => {
    await expectStatus(await send(`POST /agencies/${agencyId}/invitations`, { email, role, clients }, signed), 201, 'The invitation');
  });
}

/** Accepts an invitation through the API, as its recipient. */
export function acceptInvitation(guest: Who, token: string): Promise<void> {
  return as(guest, async (signed) => {
    await expectStatus(await send('POST /invitations/accept', { token }, signed), 200, 'Accepting the invitation');
  });
}

export const standInAccount = (label: string, provider: StandInAccount['provider'] = 'synthetic'): StandInAccount => ({
  provider,
  account: `acct-${label.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${Date.now().toString(36)}`,
  label,
});

/** A made-up Meta dataset at the stand-in provider: its number and its name. */
export const standInDataset = (label: string): StandInAccount => ({
  provider: 'synthetic_meta_capi',
  account: `9${String(Date.now()).slice(-9)}`,
  label,
});

/**
 * Connects a stand-in account to a client without a browser: starts the authorization as the
 * owner, approves it at the stand-in provider and follows the provider's return to the API.
 * Returns the connection's id.
 */
export function withConnection(owner: Who, agencyId: string, clientId: string, account: StandInAccount): Promise<string> {
  return as(owner, (signed) => connected(signed, agencyId, clientId, account));
}

async function connected(signed: Signed, agencyId: string, clientId: string, account: StandInAccount): Promise<string> {
  const { python, backend } = runningStack();
  const body =
    account.provider === 'synthetic_youtube'
      ? { provider: account.provider, agent_approval: { approved: true, disclosure: 'dev-agent-approval-1' } }
      : account.provider === 'synthetic_meta_capi' || account.provider === 'synthetic_meta_ads'
        ? { provider: account.provider, account: account.account }
        : { provider: account.provider };
  const started = await send(`POST /agencies/${agencyId}/clients/${clientId}/connections`, body, signed);
  await expectStatus(started, 200, 'Starting the connection');
  const binding = started.headers.getSetCookie().map((value) => value.split(';')[0]).join('; ');
  const { authorization_url: address } = (await started.json()) as { authorization_url: string };

  const back = new URL(approveAtProvider(python, backend, address, account));
  const returned = await send(`GET ${back.pathname}${back.search}`, undefined, { cookie: `${signed.cookie}; ${binding}`, token: signed.token });
  await expectStatus(returned, 303, 'The return from the provider');
  const outcome = new URL(returned.headers.get('location') ?? '').searchParams;
  const id = outcome.get('connection_id');
  if (outcome.get('result') !== 'connected' || !id) throw new Error(`The connection was not made: ${outcome.toString()}`);
  return id;
}

/** One pass of the connector worker: queued reads are done and requested removals carried out. */
export function workerPass(): Record<string, Record<string, number>> {
  const { python, backend } = runningStack();
  return JSON.parse(runConnectorWorker(python, backend).trim().split(/\r?\n/).at(-1) ?? '{}') as Record<string, Record<string, number>>;
}

// Each stand-in provider has an address of its own under the reserved .invalid domain, which resolves nowhere.
const standInProviders = /^https:\/\/synthetic-[a-z-]+\.invalid\//;

/**
 * Stands in for the consent page of the stand-in provider, which no browser can open: when the
 * application leaves for it, the authorization is approved for the given account and the browser
 * is sent where the provider would send it. With `refuse`, the provider reports that the person
 * said no.
 */
export async function answerAtProvider(page: Page, account: StandInAccount, { refuse = false } = {}): Promise<void> {
  const { python, backend } = runningStack();
  await page.unroute(standInProviders);
  await page.route(standInProviders, async (route) => {
    const asked = route.request().url();
    let back: string;
    if (refuse) {
      const params = new URL(asked).searchParams;
      const address = new URL(params.get('redirect_uri') ?? '');
      address.searchParams.set('error', 'access_denied');
      address.searchParams.set('state', params.get('state') ?? '');
      back = address.toString();
    } else {
      back = approveAtProvider(python, backend, asked, account);
    }
    await route.fulfill({ status: 302, headers: { location: back } });
  });
}

/** Posts one piece of preparation and returns the API's answer. */
async function made<T>(signed: Signed, route: string, body: unknown, status: number, what: string): Promise<T> {
  const response = await send(route, body, signed);
  await expectStatus(response, status, what);
  return (await response.json()) as T;
}

/**
 * A client with something on each page of the Collect group (018-D): a site, a campaign, a
 * template, content, a link and a domain; a website source and a form; a Paymob source, a signed
 * webhook source, a stage rule and a WhatsApp number; and a stand-in dataset with its destination.
 * Every value is synthetic; nothing calls a provider.
 */
export function withCollectSetup(owner: Who, agencyId: string, clientId: string): Promise<void> {
  return as(owner, async (signed) => {
    const client = `/agencies/${agencyId}/clients/${clientId}`;
    const stamp = Date.now().toString(36);
    await made(signed, `POST ${client}/link-destination-origins`, { origin: 'https://shop.olive.example', query_names: ['lang'] }, 201, 'The site');
    const campaign = await made<{ id: string }>(signed, `POST ${client}/link-campaigns`, { public_code: 'ramadan-2026', label: 'Ramadan 2026' }, 201, 'The campaign');
    await made(signed, `POST ${client}/link-utm-templates`, { name: 'Instagram, unpaid', parameters: { utm_source: 'instagram', utm_medium: 'social' } }, 201, 'The template');
    await made(signed, `POST ${client}/link-content-references`, { external_code: '17890001', platform_label: 'Iftar menu carousel' }, 201, 'The content');
    await made(signed, `POST ${client}/managed-links`, { slug: `ramadan-${stamp}`, destination: 'https://shop.olive.example/ramadan-box', campaign_id: campaign.id }, 201, 'The link');
    await made(signed, `POST ${client}/link-domains`, { hostname: `go-${stamp}.olive.example` }, 201, 'The domain');
    await made(
      signed,
      `POST ${client}/ingestion-sources`,
      { kind: 'browser', name: 'Main website', allowed_origins: ['https://shop.olive.example'], notice_sha256: 'a'.repeat(64) },
      201,
      'The website source',
    );
    await made(signed, `PUT ${client}/collection-forms/lead`, { fields: [{ name: 'plan', data_class: 'form.option', options: ['basic', 'pro'] }] }, 200, 'The form');
    await made(
      signed,
      `POST ${client}/payment-sources`,
      { provider: 'paymob', region: 'egypt', name: 'Online shop', hmac_secret: `hmac-${stamp}-synthetic-secret`, live_integration_ids: [4567890] },
      201,
      'The Paymob source',
    );
    await made(signed, `POST ${client}/integration-sources`, { kind: 'signed_webhook', name: 'Booking tool' }, 201, 'The webhook source');
    await made(signed, `POST ${client}/crm/stage-rules`, { pipeline: 'Sales', stage: 'Closed won', outcome: 'won' }, 201, 'The stage rule');
    await made(signed, `POST ${client}/whatsapp-numbers`, { phone_number_id: `1065${String(Date.now()).slice(-10)}`, name: 'Orders line' }, 201, 'The number');
    const dataset = await connected(signed, agencyId, clientId, standInDataset('Olive pixel'));
    await made(signed, `POST ${client}/conversion-destinations`, { connection_id: dataset, event_name: 'Purchase', test_event_code: null }, 201, 'The destination');
  });
}

/**
 * Makes up an ad account at the stand-in Meta ads provider with its campaigns, ad sets and ads,
 * then connects it to a client as the owner. Returns the connection's id.
 */
export function withAdAccount(owner: Who, agencyId: string, clientId: string, account: StandInAccount, objects: StandInAdObject[]): Promise<string> {
  const { python, backend } = runningStack();
  defineAdAccount(python, backend, account.account, account.label, objects);
  return withConnection(owner, agencyId, clientId, account);
}

/** Records a declared sale of a client through the API, as an owner or admin does by hand. */
export function declareSale(owner: Who, agencyId: string, clientId: string, operationId: string, amount: string, effectiveAt: string): Promise<void> {
  return as(owner, async (signed) => {
    const body = { operation_id: operationId, kind: 'sale', amount, currency: 'EGP', effective_at: effectiveAt, reason: 'A synthetic sale of the journey' };
    await expectStatus(await send(`POST /agencies/${agencyId}/clients/${clientId}/revenue-declarations`, body, signed), 201, 'Declaring a sale');
  });
}

/**
 * The days that hold the stand-in providers' data: the synthetic Instagram account days around
 * 2026-11-01, the ads that run from 2026-10-20, and the sale declared on 2026-11-05. Analyze pages
 * are opened with these days in their address, so a journey sees the same states on any later date.
 */
export const analyzeDays = { from: '2026-10-20', to: '2026-11-09' } as const;

/**
 * Gives a client what its Analyze pages read: a stand-in Instagram account, a stand-in ad account
 * with a campaign, an ad set and an ad, one synchronization of both, and a declared sale.
 */
export async function withAnalyzeData(owner: Who, agencyId: string, clientId: string): Promise<{ instagram: string; ads: string }> {
  const instagram = await withConnection(owner, agencyId, clientId, standInAccount('@olive.thyme', 'synthetic_instagram'));
  const account = { provider: 'synthetic_meta_ads' as const, account: `act_${Date.now().toString().slice(-9)}`, label: 'Olive ads' };
  const ads = await withAdAccount(owner, agencyId, clientId, account, [
    { id: '1201', level: 'campaign', name: 'Ramadan offers' },
    { id: '1202', level: 'adset', name: 'Cairo women 25-34', campaign: '1201' },
    { id: '1203', level: 'ad', name: 'Reel: new menu', campaign: '1201', adset: '1202', first: analyzeDays.from, spend: '125.50', impressions: 900, clicks: 21 },
  ]);
  workerPass();
  await declareSale(owner, agencyId, clientId, `sale-${Date.now()}`, '1500.00', '2026-11-05T12:00:00Z');
  return { instagram, ads };
}

/** One pass of the attribution worker: the stored conversions get their credit, which is published. */
export function attributionPass(): string {
  const { python, backend } = runningStack();
  return runAttributionWorker(python, backend);
}

const shop = 'https://shop.olive.example';
const everything = { 'analytics.first_party': 'granted', attribution: 'granted', identity_link: 'granted' };

async function collected<T>(publicKey: string, path: string, body: unknown, status: number, what: string): Promise<T> {
  const response = await fetch(`${stack.apiOrigin}/collect/v1/${publicKey}/${path}`, {
    method: 'POST',
    headers: { Origin: shop, 'Content-Type': 'text/plain' },
    body: JSON.stringify(body),
  });
  if (response.status !== status) throw new Error(`${what}: the API answered ${response.status} ${await response.text()}`);
  return (response.status === 202 ? {} : await response.json()) as T;
}

/**
 * A person who came through a campaign link and became a lead (006, 008-B), all through the API:
 * a campaign and its managed link, a website source and an ingest key; then a visitor who agrees
 * to analytics, attribution and identity, is identified by a verified email, views the page
 * through the link, and sends a trusted lead signal from the shop's server. One attribution pass
 * credits the lead to the campaign. Every value is synthetic.
 */
export function withCreditedLead(owner: Who, agencyId: string, clientId: string, code = 'ramadan-2026'): Promise<{ linkId: string }> {
  return as(owner, async (signed) => {
    const client = `/agencies/${agencyId}/clients/${clientId}`;
    const stamp = Date.now().toString(36);
    await made(signed, `POST ${client}/link-destination-origins`, { origin: shop, query_names: [] }, 201, 'The site');
    const campaign = await made<{ id: string }>(signed, `POST ${client}/link-campaigns`, { public_code: code, label: 'Ramadan 2026' }, 201, 'The campaign');
    const link = await made<{ id: string }>(signed, `POST ${client}/managed-links`, { slug: `ramadan-${stamp}`, destination: `${shop}/ramadan-box`, campaign_id: campaign.id }, 201, 'The link');
    const source = await made<{ source: { public_key: string } }>(
      signed,
      `POST ${client}/ingestion-sources`,
      { kind: 'browser', name: 'Main website', allowed_origins: [shop], notice_sha256: 'a'.repeat(64) },
      201,
      'The website source',
    );
    const issued = await made<{ key: string }>(signed, `POST /agencies/${agencyId}/service-credentials`, { name: 'Shop server', kind: 'ingest', clients: [{ client_id: clientId }] }, 201, 'The ingest key');
    const key = source.source.public_key;
    const ingest = async (route: string, body: unknown, what: string) => {
      const response = await fetch(`${stack.apiOrigin}${client}/${route}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${issued.key}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (response.status !== 200 && response.status !== 201) throw new Error(`${what}: the API answered ${response.status} ${await response.text()}`);
    };

    const consent = await collected<{ subject_token: string }>(key, 'consent', { choices: everything }, 200, 'The consent');
    const token = consent.subject_token;
    const event = (type: string, payload: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
      schema_version: 1,
      event_id: randomUUID(),
      event_type: type,
      // After the identification: an event joins a person's journey from the moment the link holds.
      occurred_at: new Date().toISOString(),
      subject_token: token,
      payload,
      ...extra,
    });
    const challenge = randomBytes(24).toString('base64url');
    const handoff = await collected<{ code: string }>(key, 'identity-handoff', { subject_token: token, challenge }, 201, 'The identity handoff');
    await ingest(
      'identity-assertions',
      {
        assertion_id: randomUUID(),
        identifiers: [{ kind: 'email', value: `buyer-${stamp}@example.test`, method: 'email_code', verified_at: new Date(Date.now() - 5_000).toISOString() }],
        handoff: handoff.code,
        challenge,
      },
      'The identity assertion',
    );
    // The visitor is known before the visit, as in the attribution tests of the backend.
    await collected(key, 'events', event('page_view', { url: `${shop}/ramadan-box` }, { link_id: link.id }), 202, 'The page view');
    await ingest('events', event('lead_signal', { action: 'consultation_request' }), 'The lead signal');
    return { linkId: link.id };
  });
}
