import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { agreementBox, enter, everythingStored, signIn } from '../support/actions';
import { accepted, clientsPath, fakeApi, json, password, refused, session, signedIn, signedOut } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

/** Nobody is signed in yet, and the API accepts the sign-in. */
const acceptsSignIn = () => ({ ...signedIn(), ...signedOut(), 'POST /auth/login': json(200, session) });

describe('the sign-in screen', () => {
  it('starts with an empty agreement box and no Google button', async () => {
    fakeApi(signedOut());
    openApp('/sign-in');
    expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
    expect(agreementBox()).not.toBeChecked();
    expect(screen.queryByRole('button', { name: 'Sign in with Google' })).not.toBeInTheDocument();
    expect(document.title).toBe('Sign in · Connect');
  });

  it('sends nothing until the agreement box is ticked', async () => {
    const server = fakeApi(acceptsSignIn());
    const user = userEvent.setup();
    openApp('/sign-in');

    await signIn(user, { tick: false });

    expect(await screen.findByText('Tick the box to agree before you continue.')).toBeInTheDocument();
    expect(server.sent('POST /auth/login')).toHaveLength(0);
    expect(agreementBox()).toHaveFocus();
    expect(agreementBox()).toBeInvalid();
    expect(agreementBox()).not.toBeChecked();

    await user.click(agreementBox());
    expect(screen.queryByText('Tick the box to agree before you continue.')).not.toBeInTheDocument();
  });

  it('asks for the email and the password before anything is sent', async () => {
    const server = fakeApi(acceptsSignIn());
    const user = userEvent.setup();
    openApp('/sign-in');

    await user.click(await screen.findByRole('button', { name: 'Sign in' }));

    expect(await screen.findAllByText('This field is needed.')).toHaveLength(2);
    expect(screen.getByLabelText('Email')).toHaveFocus();
    expect(screen.getByLabelText('Email')).toBeInvalid();
    expect(server.sent('POST /auth/login')).toHaveLength(0);
  });

  it('signs in, opens the workspace and keeps the token out of storage and the address', async () => {
    const server = fakeApi(acceptsSignIn());
    const user = userEvent.setup();
    openApp('/sign-in');

    await signIn(user);

    expect(await screen.findByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
    expect(server.sent('POST /auth/login')[0]?.body).toEqual({ email: 'mona@lumen.example', password, agreements: accepted });
    expect(window.location.pathname).toBe(clientsPath);
    expect(window.location.href).not.toContain(session.csrf_token);
    expect(everythingStored()).not.toContain(session.csrf_token);
    expect(everythingStored()).not.toContain(password);
  });

  it('explains terms that changed while the page was open, and signs in with the new versions', async () => {
    const server = fakeApi({ ...acceptsSignIn(), 'POST /auth/login': refused(422, 'agreement_required') });
    const user = userEvent.setup();
    openApp('/sign-in');

    await signIn(user);

    expect(await screen.findByText('The terms changed while this page was open.')).toBeInTheDocument();
    expect(screen.getByText(/then tick the box again to sign in/)).toBeInTheDocument();
    expect(agreementBox()).not.toBeChecked();
    expect(agreementBox()).toHaveFocus();
    expect(screen.getByLabelText('Email')).toHaveValue('mona@lumen.example');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    const changed = { terms: 'draft-2', privacy: 'draft-1' };
    server.routes['GET /auth/agreements'] = json(200, { ...changed, published: true });
    server.routes['POST /auth/login'] = json(200, session);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Tick the box to agree before you continue.')).toBeInTheDocument();
    expect(server.sent('POST /auth/login')).toHaveLength(1);

    await user.click(agreementBox());
    await user.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
    const sent = server.sent('POST /auth/login').map((request) => (request.body as { agreements?: unknown }).agreements);
    expect(sent).toEqual([accepted, changed]);
    expect(server.sent('GET /auth/agreements')).toHaveLength(2);
  });

  it('says one sentence for a wrong email or a wrong password, and does not doubt the session', async () => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/login': refused(401, 'invalid_credentials') });
    const user = userEvent.setup();
    openApp('/sign-in');

    await signIn(user);

    expect(await screen.findByRole('alert')).toHaveTextContent('The email or password is not correct.');
    expect(screen.getByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
    expect(server.sent('GET /auth/me')).toHaveLength(1);
  });

  it('offers the code screen when the email is not confirmed yet', async () => {
    fakeApi({ ...signedOut(), 'POST /auth/login': refused(403, 'email_verification_required') });
    const user = userEvent.setup();
    openApp('/sign-in');

    await signIn(user);
    expect(await screen.findByRole('alert')).toHaveTextContent('Confirm your email before you sign in.');
    await user.click(screen.getByRole('link', { name: 'Enter the code we sent you' }));

    expect(await screen.findByRole('heading', { name: 'Confirm your email' })).toBeInTheDocument();
    expect(screen.getByText('mona@lumen.example')).toBeInTheDocument();
    expect(window.location.href).not.toContain('mona');
  });

  it('says to wait when too many attempts were made', async () => {
    fakeApi({ ...signedOut(), 'POST /auth/login': refused(429, 'rate_limited', { 'Retry-After': '41' }) });
    const user = userEvent.setup();
    openApp('/sign-in');

    await signIn(user);

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts. Try again in 41 seconds.');
  });

  it('returns to the page the person wanted', async () => {
    fakeApi(acceptsSignIn());
    const user = userEvent.setup();
    openApp('/sign-in?next=%2Faccount');

    await signIn(user);

    expect(await screen.findByRole('heading', { name: 'Account', level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/account');
  });

  it.each([
    ['another site', 'https%3A%2F%2Fevil.example%2Faccount'],
    ['an address without a scheme', '%2F%2Fevil.example'],
  ])('does not follow a next that names %s', async (_what, next) => {
    fakeApi(acceptsSignIn());
    const user = userEvent.setup();
    const origin = window.location.origin;
    openApp(`/sign-in?next=${next}`);

    await signIn(user);

    expect(await screen.findByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
    expect(window.location.origin).toBe(origin);
    expect(window.location.pathname).toBe(clientsPath);
  });

  it('sends a person who is already signed in on to the workspace', async () => {
    fakeApi(signedIn());
    openApp('/sign-in');
    expect(await screen.findByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
  });

  it.each([
    ['expired', 'Your session ended. Sign in again.'],
    ['signedOut', 'You are signed out.'],
    ['verified', 'Your email is confirmed. You can sign in now.'],
    ['reset', 'Your new password is saved. Sign in with it.'],
    ['passwordChanged', 'Your password was changed. Sign in with the new password.'],
    ['closed', 'Your account is closed.'],
  ])('explains why the person is at sign-in (%s)', async (notice, sentence) => {
    fakeApi(signedOut());
    openApp(`/sign-in?notice=${notice}`);
    expect(await screen.findByText(sentence)).toBeInTheDocument();
  });

  it('shows no notice for a value it does not know', async () => {
    fakeApi(signedOut());
    openApp('/sign-in?notice=%3Cb%3Ehello');
    await screen.findByRole('heading', { name: 'Sign in', level: 1 });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(screen.queryByText(/hello/)).not.toBeInTheDocument();
  });

  it('lets the person see what they typed as the password', async () => {
    fakeApi(signedOut());
    const user = userEvent.setup();
    openApp('/sign-in');
    const field = await screen.findByLabelText('Password');
    await enter(user, field, password);
    expect(field).toHaveAttribute('type', 'password');
    await user.click(screen.getByRole('button', { name: 'Show password' }));
    expect(field).toHaveAttribute('type', 'text');
    await user.click(screen.getByRole('button', { name: 'Hide password' }));
    expect(field).toHaveAttribute('type', 'password');
  });

  it('carries the token on the next mutation after signing in', async () => {
    const server = fakeApi({ ...acceptsSignIn(), 'POST /auth/logout': new Response(null, { status: 204 }) });
    const user = userEvent.setup();
    openApp('/sign-in');
    await signIn(user);
    await screen.findByRole('heading', { name: 'Clients', level: 1 });

    await user.click(screen.getByRole('button', { name: 'Account: Mona Hassan' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Sign out' }));

    await waitFor(() => expect(server.sent('POST /auth/logout')).toHaveLength(1));
    expect(server.sent('POST /auth/logout')[0]?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
  });
});
