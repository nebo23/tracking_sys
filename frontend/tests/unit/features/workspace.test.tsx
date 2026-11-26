import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { agenciesKey, tenantKey } from '@/api/agencies';
import { agencyChoice } from '@/app/agency';

import { enter } from '../support/actions';
import { agency, empty, fakeApi, json, password, refused, session, signedIn, signedOut } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

const second = { id: '11111111-2222-4333-8444-555555555555', name: 'Northlight Media', status: 'active', created_at: '2026-10-02T08:00:00Z' };

const openAccountMenu = async (user: UserEvent) => {
  await user.click(await screen.findByRole('button', { name: 'Account: Mona Hassan' }));
  return screen.findByRole('menu');
};

describe('the way into the workspace', () => {
  it('asks a visitor to sign in and remembers the page they wanted', async () => {
    fakeApi(signedOut());
    openApp('/account');
    expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get('next')).toBe('/account');
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
        agencies = [{ agency_id: agency.id, role: 'owner' }];
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

    expect(await screen.findByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument();
    const [request] = server.sent('POST /agencies');
    expect(request?.body).toEqual({ name: 'Lumen Studio' });
    expect(request?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(agencyChoice.get()).toBe(agency.id);
  });

  it('keeps a person who has an agency away from the first-agency screen', async () => {
    fakeApi(signedIn());
    openApp('/welcome');
    expect(await screen.findByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument();
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
    const navigation = within(screen.getByRole('navigation', { name: 'Primary' }));
    expect(navigation.getAllByRole('link').map((link) => link.textContent)).toEqual(['Create your agency', 'Account']);
    expect(screen.queryByRole('button', { name: /Switch agency/ })).not.toBeInTheDocument();
  });
});

describe('the workspace', () => {
  it('shows the agency, the role and who is signed in, from the API', async () => {
    fakeApi(signedIn());
    openApp('/');

    const main = within(await screen.findByRole('main'));
    expect(await main.findByText('Lumen Studio')).toBeInTheDocument();
    expect(main.getByText('Owner')).toBeInTheDocument();
    expect(main.getByText('November 21, 2026')).toBeInTheDocument();
    expect(main.getByText('Mona Hassan')).toBeInTheDocument();
    expect(main.getByText('mona@lumen.example')).toBeInTheDocument();
    expect(document.title).toBe('Overview · Connect');
  });

  it('offers only the destinations that exist in this slice', async () => {
    fakeApi(signedIn());
    openApp('/');
    const navigation = within(await screen.findByRole('navigation', { name: 'Primary' }));
    expect(navigation.getAllByRole('link').map((link) => link.textContent)).toEqual(['Overview', 'Account']);
    expect(navigation.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page');
    expect(navigation.getByRole('link', { name: 'Account' })).not.toHaveAttribute('aria-current');
  });

  it('says so when the agency could not be loaded, and tries again on request', async () => {
    const server = fakeApi({ ...signedIn(), [`GET /agencies/${agency.id}`]: refused(403, 'access_denied') });
    const user = userEvent.setup();
    openApp('/');

    const main = within(await screen.findByRole('main'));
    expect(await main.findByRole('alert')).toHaveTextContent('You do not have access to this.');

    server.routes[`GET /agencies/${agency.id}`] = json(200, agency);
    await user.click(main.getByRole('button', { name: 'Try again' }));
    expect(await main.findByText('November 21, 2026')).toBeInTheDocument();
  });

  it('changes the theme and the language from the account menu', async () => {
    fakeApi(signedIn());
    const user = userEvent.setup();
    openApp('/');

    await user.click(within(await openAccountMenu(user)).getByRole('menuitemradio', { name: 'Dark' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem('connect.theme')).toBe('dark');

    await user.click(within(await openAccountMenu(user)).getByRole('menuitemradio', { name: 'العربية' }));
    expect(await screen.findByRole('heading', { name: 'نظرة عامة', level: 1 })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('rtl');
    const main = within(screen.getByRole('main'));
    expect(await main.findByText('21 نوفمبر 2026')).toBeInTheDocument();
    expect(main.getByText('مالك')).toBeInTheDocument();
  });

  it('moves to another agency and drops what was loaded for the first', async () => {
    fakeApi({
      ...signedIn(),
      'GET /agencies': json(200, [
        { agency_id: agency.id, role: 'owner' },
        { agency_id: second.id, role: 'analyst' },
      ]),
      [`GET /agencies/${second.id}`]: json(200, second),
    });
    const user = userEvent.setup();
    const { queryClient } = openApp('/');
    const main = within(await screen.findByRole('main'));
    await main.findByText('Lumen Studio');
    queryClient.setQueryData(tenantKey(agency.id, 'clients'), [{ name: 'A client of the first agency' }]);

    await user.click(screen.getAllByRole('button', { name: /Switch agency/ })[0] as HTMLElement);
    await user.click(await screen.findByRole('menuitemradio', { name: 'Northlight Media' }));

    expect(await main.findByText('Northlight Media')).toBeInTheDocument();
    expect(main.getByText('Analyst')).toBeInTheDocument();
    expect(queryClient.getQueryData(tenantKey(agency.id, 'clients'))).toBeUndefined();
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
    expect(window.localStorage.getItem('connect.agency')).toBeNull();
  });

  it('stays signed in and says so when signing out failed', async () => {
    fakeApi({ ...signedIn(), 'POST /auth/logout': refused(403, 'csrf_failed') });
    const user = userEvent.setup();
    openApp('/');

    await user.click(within(await openAccountMenu(user)).getByRole('menuitem', { name: 'Sign out' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('This page is out of date. Reload it and try again.');
    expect(screen.getByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument();
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
