import type { Page } from '@playwright/test';

import { expectStatus, send, signedIn, type Person, type Signed } from './api.ts';
import { approveAtProvider, runConnectorWorker, type BackendEnvironment, type StandInAccount } from './stack.ts';

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
      : account.provider === 'synthetic_meta_capi'
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
