import { vi } from 'vitest';

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

/** The answers of an API where Mona is signed in and owns one agency. */
export const signedIn = (): Record<string, Answer> => ({
  'GET /auth/me': json(200, session),
  'GET /agencies': json(200, [{ agency_id: agency.id, role: 'owner' }]),
  [`GET /agencies/${agency.id}`]: json(200, agency),
});

export const signedOut = (): Record<string, Answer> => ({
  'GET /auth/me': refused(401, 'authentication_required'),
});
