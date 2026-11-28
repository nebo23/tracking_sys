import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { agenciesKey, tenantKey } from '@/api/agencies';
import { clientKey } from '@/api/clients';
import { agencyChoice } from '@/app/agency';

import { enter } from '../support/actions';
import {
  agency,
  asRole,
  client,
  clientsPath,
  connection,
  connectionsPath,
  coverage,
  empty,
  fakeApi,
  json,
  otherClient,
  password,
  refused,
  session,
  signedIn,
  signedOut,
  withClients,
} from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

const second = { id: '11111111-2222-4333-8444-555555555555', name: 'Northlight Media', status: 'active', created_at: '2026-10-02T08:00:00Z' };

const openAccountMenu = async (user: UserEvent) => {
  await user.click(await screen.findByRole('button', { name: 'Account: Mona Hassan' }));
  return screen.findByRole('menu');
};

const primary = async () => within(await screen.findByRole('navigation', { name: 'Primary' }));
const linkTexts = (navigation: ReturnType<typeof within>) => navigation.getAllByRole('link').map((link: HTMLElement) => link.textContent);
/** The switcher of the sidebar. The phone top bar holds a second, shorter one. */
const switcher = () => screen.getAllByRole('button', { name: /Switch client or agency/ })[0] as HTMLElement;

describe('the way into the workspace', () => {
  it('asks a visitor to sign in and remembers the page they wanted', async () => {
    fakeApi(signedOut());
    openApp('/account');
    expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get('next')).toBe('/account');
  });

  it('remembers a page of a client, so a link works after signing in', async () => {
    fakeApi(signedOut());
    openApp(connectionsPath);
    await screen.findByRole('heading', { name: 'Sign in', level: 1 });
    expect(new URLSearchParams(window.location.search).get('next')).toBe(connectionsPath);
  });

  it('does not name the start page as a place to return to', async () => {
    fakeApi(signedOut());
    openApp('/');
    await screen.findByRole('heading', { name: 'Sign in', level: 1 });
    expect(window.location.search).toBe('');
  });

  it('has a person without an agency create one, as its owner', async () => {
    let agencies: unknown[] = [];
    const server = fakeApi({
      ...signedIn(),
      'GET /agencies': () => json(200, agencies),
      'POST /agencies': () => {
        agencies = [{ agency_id: agency.id, role: 'owner', status: 'active' }];
        return json(201, agency);
      },
    });
    const user = userEvent.setup();
    openApp('/');

    expect(await screen.findByRole('heading', { name: 'Create your agency' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create agency' }));
    expect(await screen.findByText('This field is needed.')).toBeInTheDocument();
    expect(server.sent('POST /agencies')).toHaveLength(0);

    await enter(user, screen.getByLabelText('Agency name'), '  Lumen Studio ');
    await user.click(screen.getByRole('button', { name: 'Create agency' }));

    expect(await screen.findByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
    const [request] = server.sent('POST /agencies');
    expect(request?.body).toEqual({ name: 'Lumen Studio' });
    expect(request?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(agencyChoice.get()).toBe(agency.id);
    expect(window.location.pathname).toBe(clientsPath);
  });

  it('keeps a person who has an agency away from the first-agency screen', async () => {
    fakeApi(signedIn());
    openApp('/welcome');
    expect(await screen.findByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
  });

  it('says so when the workspace could not load, in a main region of its own', async () => {
    fakeApi({ ...signedIn(), 'GET /agencies': refused(403, 'access_denied') });
    openApp('/');
    expect(await screen.findByRole('heading', { name: 'This page could not be shown' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('You do not have access to this.');
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });

  it('lets a person without an agency reach their account, where they can close it', async () => {
    fakeApi({ ...signedIn(), 'GET /agencies': json(200, []) });
    const user = userEvent.setup();
    openApp('/welcome');

    await user.click(await screen.findByRole('link', { name: 'Account' }));

    expect(await screen.findByRole('heading', { name: 'Account', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Close my account' })).toBeInTheDocument();
    expect(linkTexts(await primary())).toEqual(['Create your agency', 'Account']);
    expect(screen.queryByRole('button', { name: /Switch client or agency/ })).not.toBeInTheDocument();
  });
});

describe('the address', () => {
  it('leads from the start to the clients of the agency the person last worked in', async () => {
    fakeApi({
      ...signedIn(),
      'GET /agencies': json(200, [
        { agency_id: agency.id, role: 'owner', status: 'active' },
        { agency_id: second.id, role: 'analyst', status: 'active' },
      ]),
      [`GET /agencies/${second.id}`]: json(200, second),
      [`GET /agencies/${second.id}/clients`]: json(200, []),
    });
    agencyChoice.set(second.id);
    openApp('/');
    await screen.findByRole('heading', { name: 'Clients', level: 1 });
    expect(window.location.pathname).toBe(`/agencies/${second.id}/clients`);
  });

  it('is not permission: an agency the person does not belong to does not exist for them', async () => {
    const server = fakeApi(signedIn());
    openApp(`/agencies/${second.id}/clients`);
    expect(await screen.findByRole('heading', { name: 'Page not found', level: 1 })).toBeInTheDocument();
    expect(screen.getAllByRole('main')).toHaveLength(1);
    // Nothing of that agency was asked for, and the agency of the person stays the one they work in.
    expect(server.requests.some((request) => request.path.includes(second.id))).toBe(false);
    expect(agencyChoice.get()).not.toBe(second.id);
  });

  it.each([
    ['refused by the API', refused(403, 'access_denied')],
    ['unknown to the API', refused(404, 'not_found')],
  ])('shows "not found" for a client that is %s', async (_case, answer) => {
    fakeApi({ ...signedIn(), [`GET /agencies/${agency.id}/clients/${client.id}`]: answer });
    openApp(connectionsPath);
    expect(await screen.findByRole('heading', { name: 'Page not found', level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Connections' })).not.toBeInTheDocument();
  });

  it('never sends something that is not an identifier to the API as a client', async () => {
    const server = fakeApi(signedIn());
    openApp(`${clientsPath}/not-an-identifier/connections`);
    expect(await screen.findByRole('heading', { name: 'Page not found', level: 1 })).toBeInTheDocument();
    expect(server.requests.some((request) => request.path.includes('not-an-identifier'))).toBe(false);
  });

  it('opens the overview of a client when the address names only the client', async () => {
    fakeApi(withClients([client]));
    openApp(`${clientsPath}/${client.id}`);
    expect(await screen.findByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe(`${clientsPath}/${client.id}`);
  });
});

describe('the workspace', () => {
  it('offers an owner the agency level: the clients, the team, the keys and the audit log', async () => {
    fakeApi(signedIn());
    openApp('/');
    const navigation = await primary();
    expect(linkTexts(navigation)).toEqual(['Clients', 'Team and access', 'API keys', 'Audit log', 'Agency settings', 'Account']);
    expect(navigation.getByRole('link', { name: 'Clients' })).toHaveAttribute('aria-current', 'page');
    expect(navigation.getByRole('link', { name: 'Account' })).not.toHaveAttribute('aria-current');
    expect(navigation.getByRole('group', { name: 'Agency' })).toBeInTheDocument();
    expect(document.title).toBe('Clients · Connect');
  });

  it('offers an analyst the clients and Agency settings, where the plan can be read', async () => {
    fakeApi(asRole('analyst', signedIn()));
    openApp('/');
    expect(linkTexts(await primary())).toEqual(['Clients', 'Agency settings', 'Account']);
  });

  it('offers a client viewer the clients only', async () => {
    fakeApi(asRole('client_viewer', signedIn()));
    openApp('/');
    expect(linkTexts(await primary())).toEqual(['Clients', 'Account']);
  });

  it.each(['team', 'keys', 'audit'])('has no %s page for a person who does not manage the agency', async (page) => {
    const server = fakeApi(asRole('analyst', signedIn()));
    openApp(`/agencies/${agency.id}/${page}`);
    expect(await screen.findByRole('heading', { name: 'Page not found', level: 1 })).toBeInTheDocument();
    expect(server.sent(`GET /agencies/${agency.id}/invitations`)).toHaveLength(0);
    expect(server.sent(`GET /agencies/${agency.id}/service-credentials`)).toHaveLength(0);
    expect(server.sent(`GET /agencies/${agency.id}/audit`)).toHaveLength(0);
    expect(server.sent(`GET /agencies/${agency.id}/members`)).toHaveLength(0);
  });

  it('does not ask for the agency profile of a client viewer, who may not read it', async () => {
    const server = fakeApi(asRole('client_viewer', withClients([client])));
    openApp('/');
    expect(await screen.findByText('Olive & Thyme')).toBeInTheDocument();
    expect(server.sent(`GET /agencies/${agency.id}`)).toHaveLength(0);
    expect(switcher()).toHaveTextContent('Your agency');
  });

  it('fits the phone tab bar to five destinations, leaving the account to the top bar inside a client', async () => {
    fakeApi(withClients([client], { [client.id]: [] }));
    const { router } = openApp(connectionsPath);
    await screen.findByRole('heading', { name: 'Connections', level: 1 });
    const bar = () => within(screen.getByRole('navigation', { name: 'Sections' }));
    // Inside a client (D5): the way back, the overview, attribution and the links, then More for the rest.
    expect(bar().getAllByRole('link').map((link) => link.textContent)).toEqual(['Clients', 'Overview', 'Attribution', 'Links']);
    // Connections is under More, so More reads as the current place.
    expect(bar().getByRole('button', { name: 'More' })).toHaveClass('is-active');
    const user = userEvent.setup();
    await user.click(bar().getByRole('button', { name: 'More' }));
    const more = within(await screen.findByRole('menu', { name: 'More' }));
    expect(more.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
      'Content',
      'Revenue',
      'Ad spend',
      'Website tracking',
      'Integrations',
      'Connections',
      'Reports',
      'Account',
    ]);
    await user.keyboard('{Escape}');

    await router.navigate({ to: '/agencies/$agencyId/clients', params: { agencyId: agency.id } });
    await waitFor(() => expect(bar().getAllByRole('link').map((link) => link.textContent)).toEqual(['Clients', 'Team', 'API keys', 'Audit', 'Settings']));
  });

  it('shows the client level inside a client, with the way back to the agency', async () => {
    fakeApi(withClients([client], { [client.id]: [] }));
    openApp(connectionsPath);

    const navigation = await primary();
    await screen.findByRole('heading', { name: 'Connections', level: 1 });
    expect(linkTexts(navigation)).toEqual([
      'Overview',
      'Content',
      'Revenue',
      'Ad spend',
      'Attribution',
      'Links',
      'Website tracking',
      'Integrations',
      'Connections',
      'Reports',
      'Account',
    ]);
    expect(navigation.getByRole('link', { name: 'Connections' })).toHaveAttribute('aria-current', 'page');
    expect(navigation.getByRole('link', { name: 'Overview' })).not.toHaveAttribute('aria-current');
    expect(navigation.getByRole('group', { name: 'Analyze' })).toBeInTheDocument();
    expect(navigation.getByRole('group', { name: 'Collect' })).toBeInTheDocument();
    expect(navigation.getByRole('group', { name: 'Manage' })).toBeInTheDocument();

    const crumbs = within(screen.getByRole('navigation', { name: 'Breadcrumb' }));
    expect(await crumbs.findByRole('link', { name: 'Lumen Studio' })).toHaveAttribute('href', clientsPath);
    expect(crumbs.getByText('Olive & Thyme')).toBeInTheDocument();
    expect(switcher()).toHaveTextContent('Olive & Thyme');
    expect(switcher()).toHaveTextContent('Lumen Studio');
  });

  it('names the way back to the agency while its name is unknown, and never marks it as the page', async () => {
    fakeApi({ ...withClients([client], { [client.id]: [] }), [`GET /agencies/${agency.id}`]: refused(403, 'access_denied') });
    openApp(connectionsPath);
    await screen.findByRole('heading', { name: 'Connections', level: 1 });
    const crumbs = within(screen.getByRole('navigation', { name: 'Breadcrumb' }));
    const back = await crumbs.findByRole('link', { name: 'Clients' });
    expect(back).toHaveAttribute('href', clientsPath);
    expect(back).not.toHaveAttribute('aria-current');
    for (const logo of screen.getAllByRole('link', { name: 'Connect' })) expect(logo).not.toHaveAttribute('aria-current');
  });

  it('moves between clients from the switcher', async () => {
    fakeApi(withClients([client, otherClient]));
    const user = userEvent.setup();
    openApp('/');
    await screen.findByRole('heading', { name: 'Clients', level: 1 });

    await user.click(switcher());
    const menu = within(await screen.findByRole('menu'));
    expect(menu.getByRole('menuitemradio', { name: 'All clients' })).toHaveAttribute('aria-checked', 'true');
    // In the order a person reads names, whatever order the API lists them in.
    expect(menu.getAllByRole('menuitemradio').map((item) => item.textContent)).toEqual(['All clients', 'CFCedar Fitness', 'OTOlive & Thyme']);
    await user.click(menu.getByRole('menuitemradio', { name: 'Cedar Fitness' }));

    expect(await screen.findByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe(`${clientsPath}/${otherClient.id}`);
  });

  it('removes what was loaded for a client once the person has left it', async () => {
    const routes = withClients([client, otherClient], { [client.id]: [connection()] });
    fakeApi({ ...routes, [`GET /agencies/${agency.id}/clients/${client.id}/connections/${connection().id}/coverage`]: json(200, coverage()) });
    const user = userEvent.setup();
    const { queryClient } = openApp(connectionsPath);
    await screen.findByText('@olive.thyme');
    const held = () => queryClient.getQueryCache().findAll({ queryKey: clientKey(agency.id, client.id) }).length;
    expect(held()).toBeGreaterThan(0);

    // To another client: nothing of the first one is kept.
    await user.click(switcher());
    await user.click(await screen.findByRole('menuitemradio', { name: 'Cedar Fitness' }));
    await screen.findByRole('heading', { name: 'Overview', level: 1 });
    await waitFor(() => expect(held()).toBe(0));
    expect(screen.queryByText('@olive.thyme')).not.toBeInTheDocument();

    // And back to the agency level: nothing of the second one either.
    await user.click(switcher());
    await user.click(await screen.findByRole('menuitemradio', { name: 'All clients' }));
    await screen.findByRole('heading', { name: 'Clients', level: 1 });
    await waitFor(() => expect(queryClient.getQueryCache().findAll({ queryKey: clientKey(agency.id, otherClient.id) })).toHaveLength(0));
  });

  it('changes the theme and the language from the account menu', async () => {
    fakeApi(signedIn());
    const user = userEvent.setup();
    openApp('/');

    await user.click(within(await openAccountMenu(user)).getByRole('menuitemradio', { name: 'Dark' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem('connect.theme')).toBe('dark');

    await user.click(within(await openAccountMenu(user)).getByRole('menuitemradio', { name: 'العربية' }));
    expect(await screen.findByRole('heading', { name: 'العملاء', level: 1 })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('rtl');
    const navigation = within(screen.getByRole('navigation', { name: 'التنقل الرئيسي' }));
    expect(linkTexts(navigation)).toEqual(['العملاء', 'الفريق والصلاحيات', 'مفاتيح API', 'سجل التدقيق', 'إعدادات الوكالة', 'الحساب']);
  });

  it('opens only the closing page of a closing agency, drawn as B15, and offers the other agencies from the account page', async () => {
    const server = fakeApi({
      ...signedIn(),
      'GET /agencies': json(200, [
        { agency_id: agency.id, role: 'owner', status: 'active' },
        { agency_id: second.id, role: 'owner', status: 'closing' },
      ]),
      [`GET /agencies/${second.id}`]: json(200, second),
      [`GET /agencies/${second.id}/clients`]: refused(403, 'access_denied'),
    });
    const user = userEvent.setup();
    openApp(`/agencies/${second.id}/clients`);

    expect(await screen.findByRole('heading', { name: 'This agency is closing', level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe(`/agencies/${second.id}/closing`);
    expect(screen.getByText(/Members and client viewers no longer see the agency/)).toBeInTheDocument();
    // B15: the top bar and the page only, and nothing the API refuses for a closing agency (R018-04).
    expect(screen.queryAllByRole('button', { name: /Switch client or agency/ })).toHaveLength(0);
    expect(server.sent(`GET /agencies/${second.id}`)).toHaveLength(0);
    expect(server.sent(`GET /agencies/${second.id}/clients`)).toHaveLength(0);

    // The account page keeps the switcher, which leads to the agency that is not closing.
    await user.click(screen.getByRole('link', { name: 'Go to my account' }));
    // The closing agency, still the current one, is called "Your agency", and no name is left loading.
    expect(await waitFor(() => switcher())).toHaveTextContent('Your agency');
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' }).querySelector('.c-skel')).toBeNull();
    await user.click(switcher());
    const menu = within(await screen.findByRole('menu'));
    expect(menu.getByRole('menuitem', { name: /Lumen Studio/ })).toHaveTextContent('Owner');
    expect(server.sent(`GET /agencies/${second.id}/clients`)).toHaveLength(0);
    expect(server.sent(`GET /agencies/${second.id}`)).toHaveLength(0);
  });

  it('has no closing page for an agency that is not closing', async () => {
    fakeApi(signedIn());
    openApp(`/agencies/${agency.id}/closing`);
    await screen.findByRole('heading', { name: 'Clients', level: 1 });
    expect(window.location.pathname).toBe(clientsPath);
  });

  it('marks another agency that is closing in the switcher, without asking for the profile the API refuses', async () => {
    const server = fakeApi({
      ...signedIn(),
      'GET /agencies': json(200, [
        { agency_id: agency.id, role: 'owner', status: 'active' },
        { agency_id: second.id, role: 'owner', status: 'closing' },
      ]),
      [`GET /agencies/${second.id}`]: refused(403, 'access_denied'),
    });
    const user = userEvent.setup();
    openApp(clientsPath);
    await screen.findByRole('heading', { name: 'Clients', level: 1 });

    await user.click(switcher());
    const menu = within(await screen.findByRole('menu'));
    expect(menu.getByRole('menuitem', { name: /Your agency/ })).toHaveTextContent('Closing');
    expect(server.sent(`GET /agencies/${second.id}`)).toHaveLength(0);
  });

  it('moves to another agency and drops what was loaded for the first', async () => {
    fakeApi({
      ...signedIn(),
      'GET /agencies': json(200, [
        { agency_id: agency.id, role: 'owner', status: 'active' },
        { agency_id: second.id, role: 'analyst', status: 'active' },
      ]),
      [`GET /agencies/${second.id}`]: json(200, second),
      [`GET /agencies/${second.id}/clients`]: json(200, []),
    });
    const user = userEvent.setup();
    const { queryClient } = openApp('/');
    await screen.findByRole('heading', { name: 'Clients', level: 1 });
    expect(queryClient.getQueryData(tenantKey(agency.id, 'clients'))).toEqual([]);

    await user.click(switcher());
    const menu = within(await screen.findByRole('menu'));
    expect(menu.getByText('Your other agencies')).toBeInTheDocument();
    await user.click(await menu.findByRole('menuitem', { name: /Northlight Media/ }));

    await waitFor(() => expect(window.location.pathname).toBe(`/agencies/${second.id}/clients`));
    expect(linkTexts(await primary())).toEqual(['Clients', 'Agency settings', 'Account']);
    await waitFor(() => expect(queryClient.getQueryData(tenantKey(agency.id, 'clients'))).toBeUndefined());
    expect(queryClient.getQueryData(tenantKey(second.id, 'clients'))).toEqual([]);
    expect(agencyChoice.get()).toBe(second.id);
  });

  it('signs out with the token and forgets what was loaded', async () => {
    const server = fakeApi({ ...signedIn(), 'POST /auth/logout': empty() });
    const user = userEvent.setup();
    const { queryClient } = openApp('/');

    await user.click(within(await openAccountMenu(user)).getByRole('menuitem', { name: 'Sign out' }));

    expect(await screen.findByText('You are signed out.')).toBeInTheDocument();
    expect(server.sent('POST /auth/logout')[0]?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    await waitFor(() => expect(queryClient.getQueryData(agenciesKey)).toBeUndefined());
    expect(queryClient.getQueryData(tenantKey(agency.id, 'clients'))).toBeUndefined();
    expect(window.localStorage.getItem('connect.agency')).toBeNull();
  });

  it('stays signed in and says so when signing out failed', async () => {
    fakeApi({ ...signedIn(), 'POST /auth/logout': refused(403, 'csrf_failed') });
    const user = userEvent.setup();
    openApp('/');

    await user.click(within(await openAccountMenu(user)).getByRole('menuitem', { name: 'Sign out' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('This page is out of date. Reload it and try again.');
    expect(screen.getByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
  });
});

describe('the account page', () => {
  const changePassword = async (user: UserEvent, current = 'the current long password') => {
    await enter(user, await screen.findByLabelText('Current password'), current);
    await enter(user, screen.getByLabelText('New password'), password);
    await user.click(screen.getByRole('button', { name: 'Change password' }));
  };

  it('shows the profile from the session', async () => {
    fakeApi(signedIn());
    openApp('/account');
    const main = within(await screen.findByRole('main'));
    expect(await main.findByText('Mona Hassan')).toBeInTheDocument();
    expect(main.getByText('mona@lumen.example')).toBeInTheDocument();
    expect(main.getByText('November 20, 2026')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Google sign-in' })).not.toBeInTheDocument();
  });

  it('returns to sign-in, with the page remembered, when the API says the session ended', async () => {
    const server = fakeApi(signedIn());
    const user = userEvent.setup();
    const { queryClient } = openApp('/account');
    await screen.findByLabelText('Current password');

    server.routes['GET /auth/me'] = refused(401, 'authentication_required');
    server.routes['POST /auth/change-password'] = refused(401, 'authentication_required');
    await changePassword(user);

    expect(await screen.findByText('Your session ended. Sign in again.')).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get('next')).toBe('/account');
    await waitFor(() => expect(queryClient.getQueryData(agenciesKey)).toBeUndefined());
    expect(agencyChoice.get()).toBeNull();
  });

  it('keeps the session when only the current password was wrong', async () => {
    const server = fakeApi({ ...signedIn(), 'POST /auth/change-password': refused(401, 'invalid_credentials') });
    const user = userEvent.setup();
    openApp('/account');

    await changePassword(user, 'not the password');

    expect(await screen.findByRole('alert')).toHaveTextContent('The current password is not correct.');
    expect(screen.getByRole('heading', { name: 'Account', level: 1 })).toBeInTheDocument();
    expect(server.sent('GET /auth/me')).toHaveLength(1);
  });

  it('applies the password rule before it sends', async () => {
    const server = fakeApi({ ...signedIn(), 'POST /auth/change-password': empty() });
    const user = userEvent.setup();
    openApp('/account');
    await enter(user, await screen.findByLabelText('Current password'), 'the current long password');
    await enter(user, screen.getByLabelText('New password'), 'too short');
    await user.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('Use at least 15 characters.')).toBeInTheDocument();
    expect(server.sent('POST /auth/change-password')).toHaveLength(0);
  });

  it('ends the session after the password changed, because the API ended every session', async () => {
    const server = fakeApi({ ...signedIn(), 'POST /auth/change-password': empty() });
    const user = userEvent.setup();
    openApp('/account');

    await changePassword(user);

    expect(await screen.findByText('Your password was changed. Sign in with the new password.')).toBeInTheDocument();
    expect(server.sent('POST /auth/change-password')[0]?.body).toEqual({
      current_password: 'the current long password',
      new_password: password,
    });
  });

  it('signs out of every session on request', async () => {
    const server = fakeApi({ ...signedIn(), 'POST /auth/logout-all': empty() });
    const user = userEvent.setup();
    openApp('/account');
    await user.click(await screen.findByRole('button', { name: 'Sign out everywhere' }));
    expect(await screen.findByText('You are signed out.')).toBeInTheDocument();
    expect(server.sent('POST /auth/logout-all')).toHaveLength(1);
  });

  describe('closing the account', () => {
    const openDialog = async (user: UserEvent) => {
      await user.click(await screen.findByRole('button', { name: 'Close my account' }));
      return within(await screen.findByRole('alertdialog', { name: 'Close your account?' }));
    };

    it('asks twice and does nothing when the person cancels', async () => {
      const server = fakeApi({ ...signedIn(), 'POST /auth/close-account': empty() });
      const user = userEvent.setup();
      openApp('/account');

      const dialog = await openDialog(user);
      expect(dialog.getByText(/This cannot be undone\./)).toBeInTheDocument();
      await user.click(dialog.getByRole('button', { name: 'Cancel' }));

      await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
      expect(server.sent('POST /auth/close-account')).toHaveLength(0);
    });

    it.each([
      [401, 'invalid_credentials', 'The password is not correct.'],
      [409, 'state_conflict', 'An agency would be left without an owner. Make someone else an owner first.'],
      [403, 'reauthentication_required', 'Sign in with Google again, then close the account within ten minutes.'],
    ])('explains a refusal (%i %s) and keeps the account', async (status, code, sentence) => {
      fakeApi({ ...signedIn(), 'POST /auth/close-account': refused(status, code) });
      const user = userEvent.setup();
      openApp('/account');

      const dialog = await openDialog(user);
      await enter(user, dialog.getByLabelText('Password'), password);
      await user.click(dialog.getByRole('button', { name: 'Close account' }));

      expect(await dialog.findByRole('alert')).toHaveTextContent(sentence);
      expect(window.location.pathname).toBe('/account');
    });

    it('sends the password and ends the session when the API closed the account', async () => {
      const server = fakeApi({ ...signedIn(), 'POST /auth/close-account': empty() });
      const user = userEvent.setup();
      openApp('/account');

      const dialog = await openDialog(user);
      await enter(user, dialog.getByLabelText('Password'), password);
      await user.click(dialog.getByRole('button', { name: 'Close account' }));

      expect(await screen.findByText('Your account is closed.')).toBeInTheDocument();
      expect(server.sent('POST /auth/close-account')[0]?.body).toEqual({ password });
    });

    it('sends no password for an account that has none', async () => {
      const server = fakeApi({ ...signedIn(), 'POST /auth/close-account': empty() });
      const user = userEvent.setup();
      openApp('/account');

      const dialog = await openDialog(user);
      await user.click(dialog.getByRole('button', { name: 'Close account' }));

      await screen.findByText('Your account is closed.');
      expect(server.sent('POST /auth/close-account')[0]?.body).toEqual({});
    });
  });
});
