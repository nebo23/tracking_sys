import { vi } from 'vitest';

import type { Connection, Coverage } from '@/api/connections';
import type { Member } from '@/api/team';

// A stand-in for the API: answers by method and path, and keeps what was sent so a test can
// look at it. Every value here is synthetic.

export interface Sent {
  method: string;
  path: string;
  url: string;
  headers: Headers;
  credentials: RequestCredentials;
  body: unknown;
}

type Answer = Response | ((sent: Sent) => Response);

export const json = (status: number, body: unknown, headers: Record<string, string> = {}): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

export const empty = (status = 204): Response => new Response(null, { status });

export const refused = (status: number, error: string, headers: Record<string, string> = {}): Response =>
  json(status, { error }, headers);

export const person = {
  id: '5d0c1f0e-6f0b-4f0f-9a57-1f1d4a3b2c01',
  email_normalized: 'mona@lumen.example',
  display_name: 'Mona Hassan',
  email_verified_at: '2026-11-20T10:00:00Z',
};

export const session = { user: person, csrf_token: 'csrf-kept-in-memory-only' };

export const agency = {
  id: '8a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d',
  name: 'Lumen Studio',
  status: 'active',
  created_at: '2026-11-21T09:00:00Z',
};

export const password = 'correct horse battery staple';

/** The agreement versions of GET /auth/agreements, and what a sign-in sends after ticking the box. */
export const agreementVersions = { terms: 'draft-1', privacy: 'draft-1', published: false };
export const accepted = { terms: 'draft-1', privacy: 'draft-1' };

/** A token of the shape the API puts in mail links (43 URL-safe characters). */
export const linkToken = 'Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC10b2tlbi0x';

export function fakeApi(routes: Record<string, Answer>) {
  const requests: Sent[] = [];
  const handle = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = input instanceof Request ? input : new Request(input, init);
    const url = new URL(request.url);
    const text = await request.clone().text();
    const sent: Sent = {
      method: request.method,
      path: url.pathname,
      url: request.url,
      headers: request.headers,
      credentials: request.credentials,
      body: text === '' ? undefined : (JSON.parse(text) as unknown),
    };
    requests.push(sent);
    const answer = routes[`${sent.method} ${sent.path}`];
    if (answer === undefined) return refused(404, 'not_found');
    return typeof answer === 'function' ? answer(sent) : answer.clone();
  };
  vi.stubGlobal('fetch', vi.fn(handle));
  return {
    requests,
    /** Routes can be replaced while a test runs, to change what the API answers next. */
    routes,
    sent: (route: string) => requests.filter((request) => `${request.method} ${request.path}` === route),
  };
}

/** The address of the first page of the workspace: the clients of the agency. */
export const clientsPath = `/agencies/${agency.id}/clients`;

export const client = {
  id: 'c1111111-1111-4111-8111-111111111111',
  agency_id: agency.id,
  name: 'Olive & Thyme',
  status: 'active',
  created_at: '2026-11-22T09:00:00Z',
};

export const otherClient = {
  id: 'c2222222-2222-4222-8222-222222222222',
  agency_id: agency.id,
  name: 'Cedar Fitness',
  status: 'active',
  created_at: '2026-11-23T09:00:00Z',
};

export const connectionsPath = `${clientsPath}/${client.id}/connections`;

/** A connection as the API lists it. Fields a test cares about are given; the rest are quiet defaults. */
export const connection = (given: Record<string, unknown> = {}): Connection =>
  ({
  id: 'd1111111-1111-4111-8111-111111111111',
  provider: 'synthetic',
  account: { external_account_id: 'acct-1', label: '@olive.thyme' },
  status: 'active',
  status_reason: null,
  granted_scopes: ['read'],
  connected_at: '2026-11-22T10:00:00Z',
  last_successful_sync_at: '2026-11-26T09:00:00Z',
  actions: { reconnect: false, disconnect: true },
  disconnect: null,
  grant_expires_at: null,
  ...given,
}) as Connection;

const quietRun = { state: 'idle', kind: null, reason: null, next_attempt_at: null };

/** The coverage of a connection, quiet and complete unless a test says otherwise. */
export const coverage = (given: Record<string, unknown> = {}): Coverage =>
  ({
  connection_id: 'd1111111-1111-4111-8111-111111111111',
  source: { provider: 'synthetic', adapter_version: 'synthetic-1', account_kind: 'business' },
  status: 'active',
  last_successful_sync_at: '2026-11-26T09:00:00Z',
  freshness: 'fresh',
  freshness_hours: 24,
  sync: quietRun,
  streams: [
    {
      stream: 'account',
      state: 'complete',
      covered_from: '2026-10-27T00:00:00Z',
      complete_through: '2026-11-25T00:00:00Z',
      history_limit_days: 30,
      sync: quietRun,
    },
  ],
  metrics: [],
  cost: {
    unit: 'synthetic_unit',
    period_start: '2026-11-26T00:00:00Z',
    consumed: 38,
    allocation: 100,
    remaining: 62,
    state: 'available',
    reason: null,
    buckets: [],
  },
  ...given,
}) as Coverage;

/** The answers of an API where Mona is signed in and owns one agency, which has no client yet. */
/** A member of the agency as the API lists members to its owners and admins (018-B plan, B1). */
export const member = (given: Partial<Member> = {}): Member => ({
  id: 'b1111111-1111-4111-8111-111111111111',
  agency_id: agency.id,
  user_id: person.id,
  role: 'owner',
  status: 'active',
  joined_at: '2026-11-21T09:00:00Z',
  display_name: person.display_name,
  email_normalized: person.email_normalized,
  account: 'active',
  clients: [],
  ...given,
});

/** The list of clients, active or archived as the address asks (018-B plan, B2). */
export const clientList = (active: unknown[], archived: unknown[] = []) => (sent: Sent) =>
  json(200, new URL(sent.url).searchParams.get('status') === 'archived' ? archived : active);

export const signedIn = (): Record<string, Answer> => ({
  'GET /auth/me': json(200, session),
  'GET /agencies': json(200, [{ agency_id: agency.id, role: 'owner', status: 'active' }]),
  [`GET /agencies/${agency.id}`]: json(200, agency),
  [`GET /agencies/${agency.id}/clients`]: clientList([]),
  [`GET /agencies/${agency.id}/members`]: json(200, [member()]),
});

/** The same agency with clients, each with the connections given for it (none by default). */
export const withClients = (
  clients: Array<typeof client>,
  connections: Record<string, unknown[]> = {},
  archived: Array<typeof client> = [],
): Record<string, Answer> => ({
  ...signedIn(),
  [`GET /agencies/${agency.id}/clients`]: clientList(clients, archived),
  ...Object.fromEntries(
    clients.flatMap((item) => [
      [`GET /agencies/${agency.id}/clients/${item.id}`, json(200, item)],
      [`GET /agencies/${agency.id}/clients/${item.id}/connections`, json(200, connections[item.id] ?? [])],
    ]),
  ),
});

/** Mona with another role in the agency. */
export const asRole = (role: 'owner' | 'admin' | 'analyst' | 'client_viewer', routes: Record<string, Answer>): Record<string, Answer> => ({
  ...routes,
  'GET /agencies': json(200, [{ agency_id: agency.id, role }]),
  // A client viewer may not read the agency's profile.
  ...(role === 'client_viewer' ? { [`GET /agencies/${agency.id}`]: refused(403, 'access_denied') } : {}),
});

export const signedOut = (): Record<string, Answer> => ({
  'GET /auth/me': refused(401, 'authentication_required'),
  'GET /auth/agreements': json(200, agreementVersions),
});
