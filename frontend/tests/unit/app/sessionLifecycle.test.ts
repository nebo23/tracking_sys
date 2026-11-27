import { QueryClient } from '@tanstack/react-query';
import type { AnyRouter } from '@tanstack/react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { agenciesKey, agencyQuery, tenantKey } from '@/api/agencies';
import { api, call, setCsrfToken, setUnauthorizedListener } from '@/api/client';
import { sessionKey } from '@/api/session';
import { agencyChoice, currentAccess, forgetOtherAgencies } from '@/app/agency';
import { beginSession, confirmSessionEnded, endSession, watchSession } from '@/app/sessionLifecycle';

import { agency, fakeApi, json, refused, session } from '../support/api';

afterEach(() => {
  setCsrfToken(null);
  setUnauthorizedListener(null);
  agencyChoice.set(null);
});

const otherAgency = '11111111-2222-4333-8444-555555555555';

function routerAt(pathname: string, searchStr = '') {
  const navigate = vi.fn().mockResolvedValue(undefined);
  const router = { state: { location: { pathname, searchStr } }, navigate } as unknown as AnyRouter;
  return { router, navigate };
}

/** A cache as it is in the middle of a visit: the session, the agencies and data of one agency. */
function cacheInUse(): QueryClient {
  const queryClient = new QueryClient();
  queryClient.setQueryData(sessionKey, session);
  queryClient.setQueryData(agenciesKey, [{ agency_id: agency.id, role: 'owner' }]);
  queryClient.setQueryData(agencyQuery(agency.id).queryKey, agency);
  queryClient.setQueryData(tenantKey(agency.id, 'clients'), [{ name: 'Olive and Thyme' }]);
  queryClient.setQueryData(tenantKey(otherAgency, 'clients'), [{ name: 'Another agency client' }]);
  return queryClient;
}

const keysLeft = (queryClient: QueryClient) =>
  queryClient
    .getQueryCache()
    .getAll()
    .map((query) => query.queryKey[0]);

const tokenOfNextMutation = async (server: ReturnType<typeof fakeApi>): Promise<string | null> => {
  server.routes['POST /agencies'] = json(201, agency);
  await call(api.POST('/agencies', { body: { name: 'Lumen Studio' } }));
  return server.sent('POST /agencies').at(-1)?.headers.get('X-CSRF-Token') ?? null;
};

describe('starting a session', () => {
  it('begins from an empty cache, so nothing an earlier visitor loaded is shown', () => {
    const queryClient = cacheInUse();
    const next = { ...session, csrf_token: 'the-next-visitor' };
    beginSession(queryClient, next);
    expect(keysLeft(queryClient)).toEqual(['session']);
    expect(queryClient.getQueryData(sessionKey)).toEqual(next);
  });
});

describe('ending a session', () => {
  it('forgets the token, the agency and every answer, then shows the sign-in screen', async () => {
    const server = fakeApi({});
    const queryClient = cacheInUse();
    setCsrfToken(session.csrf_token);
    agencyChoice.set(agency.id);
    const { router, navigate } = routerAt('/account');

    await endSession(queryClient, router, 'signedOut');

    expect(queryClient.getQueryData(sessionKey)).toBeNull();
    expect(keysLeft(queryClient)).toEqual(['session']);
    expect(agencyChoice.get()).toBeNull();
    expect(window.localStorage.getItem('connect.agency')).toBeNull();
    expect(await tokenOfNextMutation(server)).toBeNull();
    expect(navigate).toHaveBeenCalledWith({ to: '/sign-in', search: { notice: 'signedOut', next: undefined } });
  });

  it('can return to the page the person was on, but never names the start page', async () => {
    const onAccount = routerAt('/account', '?notice=googleLinked');
    await endSession(cacheInUse(), onAccount.router, 'expired', { keepPlace: true });
    expect(onAccount.navigate).toHaveBeenCalledWith({
      to: '/sign-in',
      search: { notice: 'expired', next: '/account?notice=googleLinked' },
    });

    const onStart = routerAt('/');
    await endSession(cacheInUse(), onStart.router, 'expired', { keepPlace: true });
    expect(onStart.navigate).toHaveBeenCalledWith({ to: '/sign-in', search: { notice: 'expired', next: undefined } });
  });
});

describe('a 401 from the API', () => {
  it('ends the session here when the API confirms it ended, and empties the cache', async () => {
    const server = fakeApi({ 'GET /auth/me': refused(401, 'authentication_required') });
    const queryClient = cacheInUse();
    setCsrfToken(session.csrf_token);
    const { router, navigate } = routerAt('/account');

    await confirmSessionEnded(queryClient, router);

    expect(server.sent('GET /auth/me')).toHaveLength(1);
    expect(queryClient.getQueryData(sessionKey)).toBeNull();
    expect(keysLeft(queryClient)).toEqual(['session']);
    expect(navigate).toHaveBeenCalledWith({ to: '/sign-in', search: { notice: 'expired', next: '/account' } });
    expect(await tokenOfNextMutation(server)).toBeNull();
  });

  it('changes nothing when the session is still there', async () => {
    fakeApi({ 'GET /auth/me': json(200, session) });
    const queryClient = cacheInUse();
    const { router, navigate } = routerAt('/account');

    await confirmSessionEnded(queryClient, router);

    expect(navigate).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(agenciesKey)).toBeDefined();
    expect(queryClient.getQueryData(sessionKey)).toEqual(session);
  });

  it('changes nothing when the API cannot be reached to ask', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const queryClient = cacheInUse();
    const { router, navigate } = routerAt('/account');

    await confirmSessionEnded(queryClient, router);

    expect(navigate).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(sessionKey)).toEqual(session);
  });

  it('asks nothing once the session is known to be over', async () => {
    const server = fakeApi({ 'GET /auth/me': refused(401, 'authentication_required') });
    const queryClient = new QueryClient();
    queryClient.setQueryData(sessionKey, null);
    const { router, navigate } = routerAt('/sign-in');

    await confirmSessionEnded(queryClient, router);

    expect(server.requests).toHaveLength(0);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('is watched for on every call once the application runs', async () => {
    fakeApi({
      'GET /auth/me': refused(401, 'authentication_required'),
      'GET /agencies': refused(401, 'authentication_required'),
    });
    const queryClient = cacheInUse();
    const { router, navigate } = routerAt('/');
    watchSession(queryClient, router);

    await expect(call(api.GET('/agencies'))).rejects.toMatchObject({ status: 401 });

    await vi.waitFor(() => expect(navigate).toHaveBeenCalledTimes(1));
    expect(queryClient.getQueryData(sessionKey)).toBeNull();
  });
});

describe('moving to another agency', () => {
  it('drops what was loaded for the agency left, and keeps the rest', () => {
    const queryClient = cacheInUse();
    forgetOtherAgencies(queryClient, otherAgency);
    // What belongs to the person, and what was loaded for the agency they work in now, stays.
    expect(keysLeft(queryClient).sort()).toEqual(['agencies', 'agencies', 'session', 'tenant']);
    expect(queryClient.getQueryData(tenantKey(otherAgency, 'clients'))).toBeDefined();
    expect(queryClient.getQueryData(tenantKey(agency.id, 'clients'))).toBeUndefined();
  });

  it('remembers the agency a person chose, for the next visit', () => {
    agencyChoice.set(otherAgency);
    expect(agencyChoice.get()).toBe(otherAgency);
    expect(window.localStorage.getItem('connect.agency')).toBe(otherAgency);
  });

  it('works in the chosen agency while the person belongs to it, otherwise in the first', () => {
    const agencies = [
      { agency_id: agency.id, role: 'owner' as const, status: 'active' as const },
      { agency_id: otherAgency, role: 'analyst' as const, status: 'active' as const },
    ];
    expect(currentAccess(agencies, otherAgency)?.agency_id).toBe(otherAgency);
    expect(currentAccess(agencies, 'an-agency-the-person-left')?.agency_id).toBe(agency.id);
    expect(currentAccess(agencies, null)?.agency_id).toBe(agency.id);
    expect(currentAccess([], agency.id)).toBeUndefined();
  });
});
