import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { goTo } from '@/lib/browser';

import { agreementBox } from '../support/actions';
import { fakeApi, json, refused, session, signedIn, signedOut } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

// A build with Google sign-in switched on (VITE_GOOGLE_SIGN_IN=true).
vi.mock('@/app/config', () => ({ apiOrigin: 'http://127.0.0.1:8000', googleSignInEnabled: true }));

// Leaving the application is recorded instead of done.
vi.mock('@/lib/browser', async (original) => ({ ...(await original<typeof import('@/lib/browser')>()), goTo: vi.fn() }));

afterEach(forgetEverything);

describe('Google sign-in, when the build enables it', () => {
  it('is offered on the sign-in screen and needs the agreement like any sign-in', async () => {
    fakeApi(signedOut());
    const user = userEvent.setup();
    openApp('/sign-in');

    await user.click(await screen.findByRole('button', { name: 'Sign in with Google' }));
    expect(await screen.findByText('Tick the box to agree before you continue.')).toBeInTheDocument();
    expect(agreementBox()).toHaveFocus();
    expect(goTo).not.toHaveBeenCalled();

    await user.click(agreementBox());
    await user.click(screen.getByRole('button', { name: 'Sign in with Google' }));
    await waitFor(() =>
      expect(goTo).toHaveBeenCalledWith('http://127.0.0.1:8000/auth/google/start?terms=draft-1&privacy=draft-1'),
    );
  });

  it('cannot start while the current versions cannot be read', async () => {
    fakeApi({ ...signedOut(), 'GET /auth/agreements': refused(503, 'temporarily_unavailable') });
    const user = userEvent.setup();
    openApp('/sign-in');

    await user.click(await screen.findByRole('button', { name: 'Sign in with Google' }));
    await user.click(agreementBox());
    await user.click(screen.getByRole('button', { name: 'Sign in with Google' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Connect is busy for a moment.');
    expect(goTo).not.toHaveBeenCalled();
  });

  it('comes back to the sign-in page when the terms changed before Google answered', async () => {
    fakeApi(signedOut());
    openApp('/auth/google/complete?error=agreement_required');

    expect(await screen.findByText('The terms changed while this page was open.')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/sign-in');
    expect(agreementBox()).not.toBeChecked();
  });

  it('is linked from the account page through the address the API hands over', async () => {
    const address = 'https://accounts.google.com/o/oauth2/v2/auth?state=synthetic';
    const server = fakeApi({ ...signedIn(), 'POST /auth/google/link': json(200, { authorization_url: address }) });
    const user = userEvent.setup();
    openApp('/account');

    await user.click(await screen.findByRole('button', { name: 'Link Google' }));

    await waitFor(() => expect(goTo).toHaveBeenCalledWith(address));
    expect(server.sent('POST /auth/google/link')[0]?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
  });

  it.each(['http://accounts.google.com/', 'javascript:alert(1)'])('does not follow %s', async (address) => {
    fakeApi({ ...signedIn(), 'POST /auth/google/link': json(200, { authorization_url: address }) });
    const user = userEvent.setup();
    openApp('/account');

    await user.click(await screen.findByRole('button', { name: 'Link Google' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in with Google did not work.');
    expect(goTo).not.toHaveBeenCalled();
  });

  it.each([
    [409, 'google_already_linked', 'Your account is already linked to a Google account.'],
    [404, 'not_found', 'Sign-in with Google did not work.'],
  ])('explains a refused link (%i %s)', async (status, code, sentence) => {
    fakeApi({ ...signedIn(), 'POST /auth/google/link': refused(status, code) });
    const user = userEvent.setup();
    openApp('/account');

    await user.click(await screen.findByRole('button', { name: 'Link Google' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(sentence);
    expect(goTo).not.toHaveBeenCalled();
  });
});
