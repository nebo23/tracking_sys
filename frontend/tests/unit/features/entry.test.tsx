import { screen, waitFor } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { heldLinkToken } from '@/lib/linkToken';

import { agreementBox, enter, everythingStored } from '../support/actions';
import {
  accepted,
  agency,
  empty,
  fakeApi,
  json,
  linkToken,
  password,
  refused,
  session,
  signedIn,
  signedOut,
} from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

const acknowledged = () => json(202, { message: 'If eligible, a message has been queued.' });
const membership = { id: agency.id, agency_id: agency.id, user_id: session.user.id, role: 'analyst', status: 'active' };

async function register(user: UserEvent, { tick = true, secret = password } = {}): Promise<void> {
  await enter(user, await screen.findByLabelText('Your name'), 'Mona Hassan');
  await enter(user, screen.getByLabelText('Email'), 'mona@lumen.example');
  await enter(user, screen.getByLabelText('Password'), secret);
  if (tick) await user.click(agreementBox());
  await user.click(screen.getByRole('button', { name: 'Create account' }));
}

const typeCode = async (user: UserEvent, code: string) => {
  await user.click(screen.getByLabelText('Digit 1 of 6'));
  await user.keyboard(code);
};

describe('creating an account', () => {
  it('refuses a short password and a missing tick without sending anything', async () => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/register': acknowledged() });
    const user = userEvent.setup();
    openApp('/register');

    await register(user, { tick: false, secret: 'fourteen chars' });

    expect(await screen.findByText('Use at least 15 characters.')).toBeInTheDocument();
    expect(screen.getByText('Tick the box to agree before you continue.')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toHaveFocus();
    expect(server.sent('POST /auth/register')).toHaveLength(0);
  });

  it('sends the details once, then asks for the code without putting the address in the address bar', async () => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/register': acknowledged() });
    const user = userEvent.setup();
    openApp('/register');

    await register(user);

    expect(await screen.findByRole('heading', { name: 'Confirm your email' })).toBeInTheDocument();
    expect(server.sent('POST /auth/register').map((request) => request.body)).toEqual([
      { display_name: 'Mona Hassan', email: 'mona@lumen.example', password, agreements: accepted },
    ]);
    expect(screen.getByText('mona@lumen.example')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/verify-email');
    expect(window.location.href).not.toContain('mona');
    expect(everythingStored()).not.toContain(password);
  });

  it('explains terms that changed while the page was open, and registers with the new versions', async () => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/register': refused(422, 'agreement_required') });
    const user = userEvent.setup();
    openApp('/register');
    await register(user);

    expect(await screen.findByText('The terms changed while this page was open.')).toBeInTheDocument();
    expect(screen.getByText(/then tick the box again to create your account/)).toBeInTheDocument();
    expect(agreementBox()).not.toBeChecked();
    expect(agreementBox()).toHaveFocus();
    expect(screen.getByLabelText('Email')).toHaveValue('mona@lumen.example');

    const changed = { terms: 'draft-1', privacy: 'draft-2' };
    server.routes['GET /auth/agreements'] = json(200, { ...changed, published: true });
    server.routes['POST /auth/register'] = acknowledged();
    await user.click(agreementBox());
    await user.click(screen.getByRole('button', { name: 'Create account' }));

    expect(await screen.findByRole('heading', { name: 'Confirm your email' })).toBeInTheDocument();
    const sent = server.sent('POST /auth/register').map((request) => (request.body as { agreements?: unknown }).agreements);
    expect(sent).toEqual([accepted, changed]);
  });

  it('shows what the API refused', async () => {
    fakeApi({ ...signedOut(), 'POST /auth/register': refused(429, 'rate_limited') });
    const user = userEvent.setup();
    openApp('/register');
    await register(user);
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts. Wait a little and try again.');
  });
});

describe('confirming the email', () => {
  const arrive = async (user: UserEvent, routes: Parameters<typeof fakeApi>[0]) => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/register': acknowledged(), ...routes });
    openApp('/register');
    await register(user);
    await screen.findByRole('heading', { name: 'Confirm your email' });
    return server;
  };

  it('asks for all six digits before it sends', async () => {
    const user = userEvent.setup();
    const server = await arrive(user, {});
    await typeCode(user, '123');
    await user.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByText('Enter all six digits.')).toBeInTheDocument();
    expect(server.sent('POST /auth/verify-email-code')).toHaveLength(0);
  });

  it('clears a wrong code, says so and returns to the first cell', async () => {
    const user = userEvent.setup();
    await arrive(user, { 'POST /auth/verify-email-code': refused(400, 'invalid_or_expired_code') });
    await typeCode(user, '000000');
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('That code is not correct or has expired.');
    expect(screen.getByLabelText('Digit 1 of 6')).toHaveValue('');
    await waitFor(() => expect(screen.getByLabelText('Digit 1 of 6')).toHaveFocus());
  });

  it('sends the address and the code, then offers sign-in with the address filled in', async () => {
    const user = userEvent.setup();
    const server = await arrive(user, { 'POST /auth/verify-email-code': empty() });
    await typeCode(user, '042917');
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(await screen.findByText('Your email is confirmed. You can sign in now.')).toBeInTheDocument();
    expect(server.sent('POST /auth/verify-email-code')[0]?.body).toEqual({ email: 'mona@lumen.example', code: '042917' });
    expect(screen.getByLabelText('Email')).toHaveValue('mona@lumen.example');
    expect(window.location.href).not.toContain('042917');
  });

  it('waits before it offers a new code, because one was just sent', async () => {
    const user = userEvent.setup();
    const server = await arrive(user, { 'POST /auth/resend-verification': acknowledged() });
    const resend = screen.getByRole('button', { name: 'Send a new code' });
    expect(resend).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByText(/You can ask for a new code in \d+ seconds\./)).toBeInTheDocument();
    await user.click(resend);
    expect(server.sent('POST /auth/resend-verification')).toHaveLength(0);
  });

  it('asks for the address again after a reload, and answers a resend the same way for every address', async () => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/resend-verification': acknowledged() });
    const user = userEvent.setup();
    openApp('/verify-email');

    await user.click(await screen.findByRole('button', { name: 'Send a new code' }));
    expect(await screen.findByText('This field is needed.')).toBeInTheDocument();
    expect(server.sent('POST /auth/resend-verification')).toHaveLength(0);

    await enter(user, screen.getByLabelText('Email'), 'mona@lumen.example');
    await user.click(screen.getByRole('button', { name: 'Send a new code' }));

    expect(await screen.findByText('If this address is waiting to be confirmed, a new code is on its way.')).toBeInTheDocument();
    expect(server.sent('POST /auth/resend-verification')[0]?.body).toEqual({ email: 'mona@lumen.example' });
    expect(screen.getByRole('button', { name: 'Send a new code' })).toHaveAttribute('aria-disabled', 'true');
  });
});

describe('a forgotten password', () => {
  it('answers the same way for every address', async () => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/forgot-password': acknowledged() });
    const user = userEvent.setup();
    openApp('/forgot-password');

    await enter(user, await screen.findByLabelText('Email'), 'nobody@lumen.example');
    await user.click(screen.getByRole('button', { name: 'Send the link' }));

    expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('If an account uses nobody@lumen.example, a reset link is on its way.');
    expect(server.sent('POST /auth/forgot-password')[0]?.body).toEqual({ email: 'nobody@lumen.example' });
  });

  it('asks for a complete address first', async () => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/forgot-password': acknowledged() });
    const user = userEvent.setup();
    openApp('/forgot-password');
    await enter(user, await screen.findByLabelText('Email'), 'nobody');
    await user.click(screen.getByRole('button', { name: 'Send the link' }));
    expect(await screen.findByText('Enter a complete address, such as name@agency.com.')).toBeInTheDocument();
    expect(server.sent('POST /auth/forgot-password')).toHaveLength(0);
  });
});

describe('the reset link', () => {
  it('loses its token from the address bar at once and sends it once, in the request body', async () => {
    const server = fakeApi({ ...signedOut(), 'POST /auth/reset-password': empty() });
    const user = userEvent.setup();
    openApp(`/auth/reset-password#token=${linkToken}`);

    const field = await screen.findByLabelText('New password');
    expect(window.location.hash).toBe('');
    expect(window.location.href).not.toContain(linkToken);
    expect(everythingStored()).not.toContain(linkToken);

    await enter(user, field, password);
    await user.click(screen.getByRole('button', { name: 'Save the password' }));

    expect(await screen.findByText('Your new password is saved. Sign in with it.')).toBeInTheDocument();
    const [request] = server.sent('POST /auth/reset-password');
    expect(request?.body).toEqual({ token: linkToken, password });
    expect(request?.url).not.toContain(linkToken);
    expect(heldLinkToken('reset')).toBeNull();
    expect(window.location.href).not.toContain(linkToken);
  });

  it('says so when the link has expired or was used, and forgets the token', async () => {
    fakeApi({ ...signedOut(), 'POST /auth/reset-password': refused(400, 'invalid_or_expired_token') });
    const user = userEvent.setup();
    openApp(`/auth/reset-password#token=${linkToken}`);

    await enter(user, await screen.findByLabelText('New password'), password);
    await user.click(screen.getByRole('button', { name: 'Save the password' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('This link has expired or was already used. Ask for a new one.');
    expect(screen.getByRole('link', { name: 'Ask for a new link' })).toHaveAttribute('href', '/forgot-password');
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument();
    expect(heldLinkToken('reset')).toBeNull();
  });

  it('cannot be used without its token', async () => {
    fakeApi(signedOut());
    openApp('/auth/reset-password');
    expect(await screen.findByRole('heading', { name: 'This link cannot be used' })).toBeInTheDocument();
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument();
  });

  it('is also taken when it is pasted into a tab that already shows the page', async () => {
    fakeApi(signedOut());
    openApp('/auth/reset-password');
    await screen.findByRole('heading', { name: 'This link cannot be used' });

    window.location.hash = `#token=${linkToken}`;

    expect(await screen.findByLabelText('New password')).toBeInTheDocument();
    expect(window.location.hash).toBe('');
    expect(everythingStored()).not.toContain(linkToken);
  });
});

describe('an invitation', () => {
  it('keeps its token in memory while the person signs in, and out of every address', async () => {
    fakeApi(signedOut());
    openApp(`/auth/accept-invitation#token=${linkToken}`);

    const link = await screen.findByRole('link', { name: 'Sign in to continue' });
    expect(link).toHaveAttribute('href', '/sign-in?next=%2Fauth%2Faccept-invitation');
    expect(window.location.hash).toBe('');
    expect(document.body.innerHTML).not.toContain(linkToken);
    expect(heldLinkToken('invitation')).toBe(linkToken);
  });

  it('is accepted by a signed-in person and opens the agency', async () => {
    const server = fakeApi({ ...signedIn(), 'POST /invitations/accept': json(200, membership) });
    const user = userEvent.setup();
    openApp(`/auth/accept-invitation#token=${linkToken}`);

    await user.click(await screen.findByRole('button', { name: 'Accept the invitation' }));

    expect(await screen.findByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
    const [request] = server.sent('POST /invitations/accept');
    expect(request?.body).toEqual({ token: linkToken });
    expect(request?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(heldLinkToken('invitation')).toBeNull();
  });

  it('explains an invitation that expired, was withdrawn or belongs to another address', async () => {
    fakeApi({ ...signedIn(), 'POST /invitations/accept': refused(400, 'invalid_or_expired_token') });
    const user = userEvent.setup();
    openApp(`/auth/accept-invitation#token=${linkToken}`);

    await user.click(await screen.findByRole('button', { name: 'Accept the invitation' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This invitation has expired, was withdrawn or belongs to another email.',
    );
    expect(screen.queryByRole('button', { name: 'Accept the invitation' })).not.toBeInTheDocument();
  });

  it('cannot be used without its token', async () => {
    fakeApi(signedOut());
    openApp('/auth/accept-invitation');
    expect(await screen.findByRole('heading', { name: 'This invitation link cannot be used' })).toBeInTheDocument();
  });

  it('comes before creating an agency of one\'s own', async () => {
    fakeApi({ ...signedIn(), 'GET /agencies': json(200, []) });
    openApp(`/auth/accept-invitation#token=${linkToken}`);
    await screen.findByRole('button', { name: 'Accept the invitation' });
    // Even on the way to the workspace, a person without an agency is brought back to the invitation.
    window.history.pushState(null, '', '/');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(await screen.findByRole('button', { name: 'Accept the invitation' })).toBeInTheDocument();
    await waitFor(() => expect(window.location.pathname).toBe('/auth/accept-invitation'));
  });
});

describe('coming back from Google', () => {
  it.each([
    ['google_link_required', 'An account already uses this email.'],
    ['google_sign_in_cancelled', 'Sign-in with Google was cancelled.'],
    ['something_new', 'Sign-in with Google did not work.'],
  ])('explains %s', async (code, sentence) => {
    fakeApi(signedOut());
    openApp(`/auth/google/complete?error=${code}`);
    expect(await screen.findByRole('alert')).toHaveTextContent(sentence);
    expect(screen.getByRole('link', { name: 'Back to sign in' })).toBeInTheDocument();
  });

  it('opens the workspace after a successful sign-in', async () => {
    fakeApi(signedIn());
    openApp('/auth/google/complete?result=signed_in');
    expect(await screen.findByRole('heading', { name: 'Clients', level: 1 })).toBeInTheDocument();
  });

  it('returns to the account page after a link, and says it worked', async () => {
    fakeApi(signedIn());
    openApp('/auth/google/complete?result=linked');
    expect(await screen.findByText('Google is now linked to your account.')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/account');
  });

  it('does not claim success when no session came back', async () => {
    fakeApi(signedOut());
    openApp('/auth/google/complete?result=signed_in');
    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in with Google did not work.');
  });
});

describe('the language switch', () => {
  it('turns the screen to Arabic, right to left, and remembers it', async () => {
    fakeApi(signedOut());
    const user = userEvent.setup();
    openApp('/sign-in');

    await user.click(await screen.findByRole('radio', { name: 'العربية' }));

    expect(await screen.findByRole('heading', { name: 'تسجيل الدخول', level: 1 })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('ar');
    expect(document.documentElement.dir).toBe('rtl');
    expect(window.localStorage.getItem('connect.language')).toBe('ar');
    await waitFor(() => expect(document.title).toBe('تسجيل الدخول · كونكت'));
    expect(screen.getByRole('img', { name: 'كونكت' })).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'English' }));
    expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('keeps what was typed when the language changes', async () => {
    fakeApi(signedOut());
    const user = userEvent.setup();
    openApp('/sign-in');
    await enter(user, await screen.findByLabelText('Email'), 'mona@lumen.example');
    await user.click(screen.getByRole('radio', { name: 'العربية' }));
    expect(await screen.findByLabelText('البريد الإلكتروني')).toHaveValue('mona@lumen.example');
  });
});

describe('the other pages', () => {
  it.each([
    ['/terms', 'Terms of Service'],
    ['/privacy', 'Privacy Policy'],
  ])('say honestly that %s has no published text yet', async (address, title) => {
    fakeApi(signedOut());
    openApp(address);
    expect(await screen.findByRole('heading', { name: title, level: 1 })).toBeInTheDocument();
    expect(screen.getByText('This text has not been published yet.')).toBeInTheDocument();
  });

  it('say when an address does not exist', async () => {
    fakeApi(signedOut());
    openApp('/nowhere');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });

  it('say when a page could not load what it needs, and try again on request', async () => {
    const server = fakeApi({ 'GET /auth/me': refused(404, 'not_found') });
    const user = userEvent.setup();
    openApp('/sign-in');
    expect(await screen.findByRole('heading', { name: 'This page could not be shown' })).toBeInTheDocument();
    // The message stands inside the frame of the entry screens, which already has the main region.
    expect(screen.getAllByRole('main')).toHaveLength(1);

    server.routes['GET /auth/me'] = refused(401, 'authentication_required');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
  });
});
