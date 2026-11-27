import createClient, { type Middleware } from 'openapi-fetch';

import { apiOrigin } from '@/app/config';

import { ApiError, planLimitOf } from './errors';
import type { paths } from './schema';

// The session is an HttpOnly cookie that this code never sees. The request-forgery token comes
// from POST /auth/login and GET /auth/me and lives in memory only: never in storage, never in a URL.
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

const safeMethods = new Set(['GET', 'HEAD', 'OPTIONS']);

const forgeryToken: Middleware = {
  onRequest({ request }) {
    if (csrfToken !== null && !safeMethods.has(request.method)) {
      request.headers.set('X-CSRF-Token', csrfToken);
    }
    return request;
  },
};

export const api = createClient<paths>({
  baseUrl: apiOrigin,
  credentials: 'include',
  // Looked up at call time, so tests can replace the global.
  fetch: (request) => globalThis.fetch(request),
});
api.use(forgeryToken);

type Unauthorized = () => void;
let onUnauthorized: Unauthorized | null = null;

/** Called after a 401 that may mean the session ended. The listener asks the API and decides. */
export function setUnauthorizedListener(listener: Unauthorized | null): void {
  onUnauthorized = listener;
}

interface Answer<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function errorCode(body: unknown): string {
  if (typeof body === 'object' && body !== null && 'error' in body && typeof body.error === 'string') return body.error;
  return 'unknown_error';
}

function retryAfter(response: Response): number | null {
  // The header is readable only when the API exposes it to this origin.
  const seconds = Number(response.headers.get('Retry-After'));
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null;
}

interface CallOptions {
  /** True for the calls that ask about the session themselves: their 401 is the answer, not news. */
  asksAboutSession?: boolean;
}

/** Awaits an API call and returns its data, or throws an ApiError that carries the API's code. */
export async function call<T>(pending: Promise<Answer<T>>, options: CallOptions = {}): Promise<T> {
  let answer: Answer<T>;
  try {
    answer = await pending;
  } catch {
    throw new ApiError(0, 'network_error');
  }
  if (answer.response.ok) return answer.data as T;
  const code = errorCode(answer.error);
  // A wrong password is a 401 as well (invalid_credentials); it says nothing about the session.
  if (answer.response.status === 401 && code !== 'invalid_credentials' && !options.asksAboutSession) onUnauthorized?.();
  throw new ApiError(answer.response.status, code, retryAfter(answer.response), planLimitOf(answer.error));
}
