import { afterEach, describe, expect, it, vi } from 'vitest';

import { api, call, setCsrfToken, setUnauthorizedListener } from '@/api/client';
import { acceptInvitation, fetchSession, resetPassword, signIn, signOut, signOutEverywhere } from '@/api/session';

import { accepted, agency, empty, fakeApi, json, linkToken, password, refused, session } from '../support/api';

afterEach(() => {
  setCsrfToken(null);
  setUnauthorizedListener(null);
});

const tokenOfNextMutation = async (server: ReturnType<typeof fakeApi>): Promise<string | null> => {
  server.routes['POST /agencies'] = json(201, agency);
  await call(api.POST('/agencies', { body: { name: 'Lumen Studio' } }));
  return server.sent('POST /agencies').at(-1)?.headers.get('X-CSRF-Token') ?? null;
};

describe('the session', () => {
  it('is read from the API, with the token that later mutations carry', async () => {
    const server = fakeApi({ 'GET /auth/me': json(200, session) });
    expect(await fetchSession()).toEqual(session);
    expect(await tokenOfNextMutation(server)).toBe(session.csrf_token);
  });

  it('is nobody when the API answers 401, without calling that an ended session', async () => {
    const server = fakeApi({ 'GET /auth/me': refused(401, 'authentication_required') });
    const listener = vi.fn();
    setUnauthorizedListener(listener);
    setCsrfToken('left-over');
    expect(await fetchSession()).toBeNull();
    expect(listener).not.toHaveBeenCalled();
    expect(await tokenOfNextMutation(server)).toBeNull();
  });

  it('passes on a failure that is not a 401', async () => {
    fakeApi({ 'GET /auth/me': refused(503, 'temporarily_unavailable') });
    await expect(fetchSession()).rejects.toMatchObject({ status: 503, code: 'temporarily_unavailable' });
  });

  it('starts at sign-in with the email, the password and the accepted versions in the request body only', async () => {
    const server = fakeApi({ 'POST /auth/login': json(200, session) });
    expect(await signIn('mona@lumen.example', password, accepted)).toEqual(session);
    const [request] = server.sent('POST /auth/login');
    expect(request?.body).toEqual({ email: 'mona@lumen.example', password, agreements: accepted });
    expect(new URL(request?.url ?? '').search).toBe('');
    expect(await tokenOfNextMutation(server)).toBe(session.csrf_token);
  });

  it.each([
    ['here', signOut, 'POST /auth/logout'],
    ['everywhere', signOutEverywhere, 'POST /auth/logout-all'],
  ] as const)('ends %s and forgets the token', async (_where, end, route) => {
    const server = fakeApi({ [route]: empty() });
    setCsrfToken(session.csrf_token);
    await end();
    expect(server.sent(route)[0]?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(await tokenOfNextMutation(server)).toBeNull();
  });

  it('counts a sign-out that finds no session as done', async () => {
    fakeApi({ 'POST /auth/logout': refused(401, 'authentication_required') });
    const listener = vi.fn();
    setUnauthorizedListener(listener);
    await expect(signOut()).resolves.toBeUndefined();
    expect(listener).not.toHaveBeenCalled();
  });

  it('does not hide a sign-out that failed', async () => {
    fakeApi({ 'POST /auth/logout': refused(503, 'temporarily_unavailable') });
    await expect(signOut()).rejects.toMatchObject({ code: 'temporarily_unavailable' });
  });
});

describe('a token from a mail link', () => {
  it.each([
    ['a password reset', () => resetPassword(linkToken, password), 'POST /auth/reset-password', { token: linkToken, password }],
    ['an invitation', () => acceptInvitation(linkToken), 'POST /invitations/accept', { token: linkToken }],
  ] as const)('travels in the body of %s and never in its address', async (_what, send, route, body) => {
    const server = fakeApi({
      'POST /auth/reset-password': empty(),
      'POST /invitations/accept': json(200, { id: agency.id, agency_id: agency.id, user_id: agency.id, role: 'analyst', status: 'active' }),
    });
    await send();
    const [request] = server.sent(route);
    expect(request?.body).toEqual(body);
    expect(request?.url).not.toContain(linkToken);
  });
});
