import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, call, setCsrfToken, setUnauthorizedListener } from '@/api/client';
import { ApiError } from '@/api/errors';

import { agency, empty, fakeApi, json, refused, session } from '../support/api';

afterEach(() => {
  setCsrfToken(null);
  setUnauthorizedListener(null);
});

const failure = async (pending: Promise<unknown>): Promise<ApiError> => {
  try {
    await pending;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error('The call was expected to fail.');
};

describe('the API client', () => {
  it('sends the session cookie with every request', async () => {
    const server = fakeApi({ 'GET /auth/me': json(200, session) });
    await call(api.GET('/auth/me'));
    expect(server.requests[0]?.credentials).toBe('include');
  });

  it('adds the request-forgery token to every mutation and to no read', async () => {
    const server = fakeApi({
      'GET /agencies': json(200, []),
      'POST /agencies': json(201, agency),
      [`PATCH /agencies/${agency.id}`]: json(200, agency),
      [`DELETE /agencies/${agency.id}/invitations/${agency.id}`]: empty(),
    });
    setCsrfToken('token-from-memory');

    await call(api.GET('/agencies'));
    await call(api.POST('/agencies', { body: { name: 'Lumen Studio' } }));
    await call(api.PATCH('/agencies/{agency_id}', { params: { path: { agency_id: agency.id } }, body: { name: 'Lumen' } }));
    await call(
      api.DELETE('/agencies/{agency_id}/invitations/{invitation_id}', {
        params: { path: { agency_id: agency.id, invitation_id: agency.id } },
      }),
    );

    expect(server.requests.map((request) => [request.method, request.headers.get('X-CSRF-Token')])).toEqual([
      ['GET', null],
      ['POST', 'token-from-memory'],
      ['PATCH', 'token-from-memory'],
      ['DELETE', 'token-from-memory'],
    ]);
  });

  it('sends no token header before one is known', async () => {
    const server = fakeApi({ 'POST /auth/login': json(200, session) });
    await call(api.POST('/auth/login', { body: { email: 'mona@lumen.example', password: 'a password' } }));
    expect(server.requests[0]?.headers.has('X-CSRF-Token')).toBe(false);
  });

  it("turns an error answer into an error that carries the API's code", async () => {
    fakeApi({ 'POST /agencies': refused(409, 'state_conflict') });
    const error = await failure(call(api.POST('/agencies', { body: { name: 'Lumen Studio' } })));
    expect(error).toMatchObject({ status: 409, code: 'state_conflict', retryAfterSeconds: null });
  });

  it('reads the waiting time of a rate limit when the browser may read it', async () => {
    fakeApi({ 'POST /auth/login': refused(429, 'rate_limited', { 'Retry-After': '41' }) });
    const error = await failure(call(api.POST('/auth/login', { body: { email: 'a@b.example', password: 'x' } })));
    expect(error).toMatchObject({ status: 429, code: 'rate_limited', retryAfterSeconds: 41 });
  });

  it('treats an answer that is not in the shape of the API as an unknown error', async () => {
    fakeApi({ 'GET /agencies': new Response('<html>Bad gateway</html>', { status: 502 }) });
    expect(await failure(call(api.GET('/agencies')))).toMatchObject({ status: 502, code: 'unknown_error' });
  });

  it('reports a request that never reached the API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    expect(await failure(call(api.GET('/agencies')))).toMatchObject({ status: 0, code: 'network_error' });
  });

  describe('a 401', () => {
    it('is reported as a session that may have ended', async () => {
      fakeApi({ 'GET /agencies': refused(401, 'authentication_required') });
      const listener = vi.fn();
      setUnauthorizedListener(listener);
      await failure(call(api.GET('/agencies')));
      expect(listener).toHaveBeenCalledTimes(1);
    });

    it('for a wrong password says nothing about the session', async () => {
      fakeApi({ 'POST /auth/change-password': refused(401, 'invalid_credentials') });
      const listener = vi.fn();
      setUnauthorizedListener(listener);
      const error = await failure(
        call(api.POST('/auth/change-password', { body: { current_password: 'wrong', new_password: 'a new long password' } })),
      );
      expect(error.code).toBe('invalid_credentials');
      expect(listener).not.toHaveBeenCalled();
    });

    it('is the answer itself for a call that asks about the session', async () => {
      fakeApi({ 'GET /auth/me': refused(401, 'authentication_required') });
      const listener = vi.fn();
      setUnauthorizedListener(listener);
      await failure(call(api.GET('/auth/me'), { asksAboutSession: true }));
      expect(listener).not.toHaveBeenCalled();
    });
  });
});
