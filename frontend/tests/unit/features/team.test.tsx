import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { enter, everythingStored } from '../support/actions';
import { agency, asRole, client, empty, fakeApi, json, otherClient, refused, session, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-26T12:00:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
  forgetEverything();
});

const teamPath = `/agencies/${agency.id}/team`;
const keysPath = `/agencies/${agency.id}/keys`;
const invitations = `/agencies/${agency.id}/invitations`;
const credentials = `/agencies/${agency.id}/service-credentials`;
type Routes = Parameters<typeof fakeApi>[0];

const invitation = (given: Record<string, unknown> = {}) => ({
  id: 'e1111111-1111-4111-8111-111111111111',
  agency_id: agency.id,
  email_normalized: 'youssef@lumen.example',
  role: 'analyst',
  status: 'pending',
  created_at: '2026-11-25T10:00:00Z',
  expires_at: '2026-12-02T10:00:00Z',
  ...given,
});

const credential = (given: Record<string, unknown> = {}) => ({
  id: 'f1111111-1111-4111-8111-111111111111',
  agency_id: agency.id,
  name: 'Reporting sheet',
  kind: 'read',
  status: 'active',
  created_at: '2026-11-20T10:00:00Z',
  expires_at: '2027-02-18T10:00:00Z',
  ...given,
});

const team = (listed: unknown[], more: Routes = {}): Routes => ({
  ...withClients([client, otherClient]),
  [`GET ${invitations}`]: json(200, listed),
  ...more,
});

const keys = (listed: unknown[], more: Routes = {}): Routes => ({
  ...withClients([client, otherClient]),
  [`GET ${credentials}`]: json(200, listed),
  ...more,
});

const rowOf = (text: string) => within(screen.getByText(text).closest('tr') as HTMLElement);
/** Chooses an option of a select, by the name of the field and of the option. */
const choose = async (user: UserEvent, scope: ReturnType<typeof within>, field: RegExp, option: RegExp) => {
  await user.click(scope.getByRole('button', { name: field }));
  await user.click(await screen.findByRole('option', { name: option }));
};

describe('the invitations of an agency', () => {
  it('shows each invitation with its state, newest first', async () => {
    fakeApi(
      team([
        invitation({ id: 'e1', email_normalized: 'old@lumen.example', status: 'accepted', created_at: '2026-11-01T10:00:00Z' }),
        invitation({ id: 'e2', email_normalized: 'late@lumen.example', created_at: '2026-11-10T10:00:00Z', expires_at: '2026-11-17T10:00:00Z' }),
        invitation({ id: 'e3', email_normalized: 'gone@lumen.example', status: 'revoked', created_at: '2026-11-12T10:00:00Z' }),
        invitation({ id: 'e4', role: 'owner', email_normalized: 'karim@lumen.example' }),
      ]),
    );
    openApp(teamPath);

    await screen.findByText('karim@lumen.example');
    const emails = [...document.querySelectorAll('tbody .c-table__primary')].map((cell) => cell.textContent);
    expect(emails).toEqual(['karim@lumen.example', 'gone@lumen.example', 'late@lumen.example', 'old@lumen.example']);

    const pending = rowOf('karim@lumen.example');
    expect(pending.getByText('Owner')).toBeInTheDocument();
    expect(pending.getByText('Waiting')).toBeInTheDocument();
    expect(pending.getByText('Dec 2, 2026')).toBeInTheDocument();
    expect(pending.getByRole('button', { name: 'Withdraw the invitation to karim@lumen.example' })).toBeInTheDocument();

    expect(rowOf('old@lumen.example').getByText('Accepted')).toBeInTheDocument();
    expect(rowOf('gone@lumen.example').getByText('Withdrawn')).toBeInTheDocument();
    // An invitation that is still pending for the API but past its time can no longer be accepted.
    const expired = rowOf('late@lumen.example');
    expect(expired.getByText('Expired')).toBeInTheDocument();
    expect(expired.queryByRole('button')).not.toBeInTheDocument();
  });

  it('says what each role can do, and that members are not listed yet', async () => {
    fakeApi(team([]));
    openApp(teamPath);
    expect(await screen.findByRole('heading', { name: 'No invitations yet' })).toBeInTheDocument();
    const roles = within(screen.getByRole('heading', { name: 'What each role can do' }).closest('section') as HTMLElement);
    expect(roles.getAllByRole('term').map((term) => term.textContent)).toEqual(['Owner', 'Admin', 'Analyst', 'Client viewer']);
    expect(screen.getByText(/The list of members, with their clients, arrives in a later update\./)).toBeInTheDocument();
  });

  it('lets only an owner withdraw an invitation to become an owner', async () => {
    fakeApi(asRole('admin', team([invitation({ role: 'owner' })])));
    openApp(teamPath);
    await screen.findByText('youssef@lumen.example');
    expect(screen.queryByRole('button', { name: /Withdraw/ })).not.toBeInTheDocument();
  });

  it('withdraws an invitation after asking, with the token', async () => {
    let listed = [invitation()];
    const route = `DELETE ${invitations}/${invitation().id}`;
    const server = fakeApi(
      team([], {
        [`GET ${invitations}`]: () => json(200, listed),
        [route]: () => {
          listed = [invitation({ status: 'revoked' })];
          return empty();
        },
      }),
    );
    const user = userEvent.setup();
    openApp(teamPath);

    await user.click(await screen.findByRole('button', { name: 'Withdraw the invitation to youssef@lumen.example' }));
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Withdraw this invitation?' }));
    expect(dialog.getByText(/The link sent to/)).toHaveTextContent('youssef@lumen.example');
    await user.click(dialog.getByRole('button', { name: 'Withdraw' }));

    expect(await screen.findByText('Withdrawn')).toBeInTheDocument();
    expect(server.sent(route)[0]?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
  });
});

describe('inviting a person', () => {
  const route = `POST ${invitations}`;
  const openDialog = async (user: UserEvent) => {
    await user.click(await screen.findByRole('button', { name: 'Invite person' }));
    return within(await screen.findByRole('dialog', { name: 'Invite a person' }));
  };

  it('needs a complete address and, for a role that reads granted clients, at least one client', async () => {
    const server = fakeApi(team([], { [route]: json(201, invitation()) }));
    const user = userEvent.setup();
    openApp(teamPath);
    const dialog = await openDialog(user);

    await enter(user, dialog.getByLabelText('Email'), 'youssef@lumen');
    await user.click(dialog.getByRole('button', { name: 'Send invitation' }));
    expect(await dialog.findByText('Enter a complete address, such as name@agency.com.')).toBeInTheDocument();
    expect(dialog.getByText('Choose at least one client.')).toBeInTheDocument();
    expect(dialog.getByLabelText('Email')).toHaveFocus();
    expect(server.sent(route)).toHaveLength(0);
  });

  it('sends the role and the granted clients, with financial data only where it was ticked', async () => {
    let listed: unknown[] = [];
    const server = fakeApi(
      team([], {
        [`GET ${invitations}`]: () => json(200, listed),
        [route]: () => {
          listed = [invitation()];
          return json(201, invitation());
        },
      }),
    );
    const user = userEvent.setup();
    openApp(teamPath);
    const dialog = await openDialog(user);

    await enter(user, dialog.getByLabelText('Email'), ' Youssef@Lumen.example ');
    // Financial data cannot be granted for a client the person may not open.
    expect(dialog.getByRole('checkbox', { name: 'Financial data of Olive & Thyme' })).toBeDisabled();
    await user.click(await dialog.findByRole('checkbox', { name: 'Olive & Thyme' }));
    await user.click(dialog.getByRole('checkbox', { name: 'Financial data of Olive & Thyme' }));
    await user.click(dialog.getByRole('checkbox', { name: 'Cedar Fitness' }));
    await user.click(dialog.getByRole('button', { name: 'Send invitation' }));

    expect(await screen.findByText(/An invitation is on its way to/)).toHaveTextContent('youssef@lumen.example');
    const [request] = server.sent(route);
    expect(request?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(request?.body).toEqual({
      email: 'Youssef@Lumen.example',
      role: 'analyst',
      clients: [
        { client_id: client.id, can_view_financials: true },
        { client_id: otherClient.id, can_view_financials: false },
      ],
    });
    expect(await screen.findByText('Waiting')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('asks for no clients for an admin, who opens every client', async () => {
    const server = fakeApi(team([], { [route]: json(201, invitation({ role: 'admin' })) }));
    const user = userEvent.setup();
    openApp(teamPath);
    const dialog = await openDialog(user);

    await enter(user, dialog.getByLabelText('Email'), 'nadia@lumen.example');
    await user.click(await dialog.findByRole('checkbox', { name: 'Olive & Thyme' }));
    await choose(user, dialog, /Role/, /^Admin/);
    expect(dialog.queryByRole('group', { name: 'Clients this person can open' })).not.toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Send invitation' }));

    await waitFor(() => expect(server.sent(route)).toHaveLength(1));
    // The client ticked before the role changed is not carried along.
    expect(server.sent(route)[0]?.body).toEqual({ email: 'nadia@lumen.example', role: 'admin', clients: [] });
  });

  it('offers the owner role to an owner only', async () => {
    fakeApi(team([]));
    const user = userEvent.setup();
    openApp(teamPath);
    const dialog = await openDialog(user);
    await user.click(dialog.getByRole('button', { name: /Role/ }));
    expect((await screen.findAllByRole('option')).map((option) => option.textContent?.split(/(?=[A-Z])/)[0])).toHaveLength(4);
    expect(screen.getByRole('option', { name: /^Owner/ })).toBeInTheDocument();
  });

  it('does not offer the owner role to an admin', async () => {
    fakeApi(asRole('admin', team([])));
    const user = userEvent.setup();
    openApp(teamPath);
    const dialog = await openDialog(user);
    await user.click(dialog.getByRole('button', { name: /Role/ }));
    await screen.findByRole('option', { name: /^Admin/ });
    expect(screen.queryByRole('option', { name: /^Owner/ })).not.toBeInTheDocument();
  });

  it('says when the person is already a member or already invited', async () => {
    fakeApi(team([], { [route]: refused(409, 'state_conflict') }));
    const user = userEvent.setup();
    openApp(teamPath);
    const dialog = await openDialog(user);
    await enter(user, dialog.getByLabelText('Email'), 'youssef@lumen.example');
    await user.click(await dialog.findByRole('checkbox', { name: 'Olive & Thyme' }));
    await user.click(dialog.getByRole('button', { name: 'Send invitation' }));
    expect(await dialog.findByRole('alert')).toHaveTextContent('This person is already a member, or an invitation is still waiting for them.');
  });
});

describe('the keys of an agency', () => {
  it('shows what the API keeps about each key, and never a key', async () => {
    fakeApi(
      keys([
        credential(),
        credential({ id: 'f2', name: 'Shop events', kind: 'ingest', created_at: '2026-11-24T10:00:00Z' }),
        credential({ id: 'f3', name: 'Old script', status: 'revoked', created_at: '2026-10-01T10:00:00Z' }),
        credential({ id: 'f4', name: 'Trial', created_at: '2026-08-01T10:00:00Z', expires_at: '2026-10-30T10:00:00Z' }),
      ]),
    );
    openApp(keysPath);

    await screen.findByText('Reporting sheet');
    const sheet = rowOf('Reporting sheet');
    expect(sheet.getByText('Read')).toBeInTheDocument();
    expect(sheet.getByText('Active')).toBeInTheDocument();
    expect(sheet.getByText('Feb 18, 2027')).toBeInTheDocument();
    expect(sheet.getByRole('button', { name: 'Revoke the key Reporting sheet' })).toBeInTheDocument();
    expect(rowOf('Shop events').getByText('Send events')).toBeInTheDocument();
    expect(rowOf('Old script').getByText('Revoked')).toBeInTheDocument();
    // A key that was never revoked still stops working when its time has passed.
    const expired = rowOf('Trial');
    expect(expired.getByText('Expired')).toBeInTheDocument();
    expect(expired.queryByRole('button')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('tsk_');
  });

  it('revokes a key after asking', async () => {
    let listed = [credential()];
    const route = `DELETE ${credentials}/${credential().id}`;
    const server = fakeApi(
      keys([], {
        [`GET ${credentials}`]: () => json(200, listed),
        [route]: () => {
          listed = [credential({ status: 'revoked' })];
          return empty();
        },
      }),
    );
    const user = userEvent.setup();
    openApp(keysPath);

    await user.click(await screen.findByRole('button', { name: 'Revoke the key Reporting sheet' }));
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Revoke “Reporting sheet”?' }));
    await user.click(dialog.getByRole('button', { name: 'Revoke' }));

    expect(await screen.findByText('Revoked')).toBeInTheDocument();
    expect(server.sent(route)).toHaveLength(1);
  });
});

describe('creating a key', () => {
  const route = `POST ${credentials}`;
  const secret = 'tsk_made-up-for-tests-only-0123456789abcdefghijklm';
  const issued = (given: Record<string, unknown> = {}) => json(201, { credential: credential(given), key: secret });
  const openDialog = async (user: UserEvent) => {
    await user.click(await screen.findByRole('button', { name: 'Create key' }));
    return within(await screen.findByRole('dialog', { name: 'Create a key' }));
  };

  it('needs a name and at least one client', async () => {
    const server = fakeApi(keys([], { [route]: issued() }));
    const user = userEvent.setup();
    openApp(keysPath);
    const dialog = await openDialog(user);
    await user.click(dialog.getByRole('button', { name: 'Create key' }));
    expect(await dialog.findByText('This field is needed.')).toBeInTheDocument();
    expect(dialog.getByText('Choose at least one client.')).toBeInTheDocument();
    expect(server.sent(route)).toHaveLength(0);
  });

  it('shows the key once, and keeps it nowhere', async () => {
    const server = fakeApi(keys([], { [route]: issued() }));
    const user = userEvent.setup();
    const { queryClient } = openApp(keysPath);
    const dialog = await openDialog(user);

    await enter(user, dialog.getByLabelText('Name'), ' Reporting sheet ');
    await user.click(await dialog.findByRole('checkbox', { name: 'Olive & Thyme' }));
    await user.click(dialog.getByRole('checkbox', { name: 'Financial data of Olive & Thyme' }));
    await user.click(dialog.getByRole('button', { name: 'Create key' }));

    const shown = within(await screen.findByRole('dialog', { name: 'Key “Reporting sheet” is ready' }));
    expect(shown.getByLabelText('Key')).toHaveValue(secret);
    expect(shown.getByText('Copy the key now and keep it somewhere safe. It is not shown again.')).toBeInTheDocument();
    expect(server.sent(route)[0]?.body).toEqual({
      name: 'Reporting sheet',
      kind: 'read',
      expires_in_days: 90,
      clients: [{ client_id: client.id, can_view_financials: true }],
    });

    // The key is in the dialog and nowhere else: not in storage, the address or the cache.
    expect(everythingStored()).not.toContain(secret);
    expect(window.location.href).not.toContain(secret);
    const cached = JSON.stringify(queryClient.getQueryCache().getAll().map((query) => query.state.data));
    expect(cached).not.toContain(secret);

    await user.click(shown.getByRole('button', { name: 'Copy' }));
    expect(await shown.findByText('Copied.')).toBeInTheDocument();
    expect(await window.navigator.clipboard.readText()).toBe(secret);

    await user.click(shown.getByRole('button', { name: 'I have copied it' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(document.body.innerHTML).not.toContain(secret);
    const held = JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => mutation.state.data));
    expect(held).not.toContain(secret);
  });

  it('never asks for financial data with a key that only sends events', async () => {
    const server = fakeApi(keys([], { [route]: issued({ kind: 'ingest' }) }));
    const user = userEvent.setup();
    openApp(keysPath);
    const dialog = await openDialog(user);

    await enter(user, dialog.getByLabelText('Name'), 'Shop events');
    await user.click(await dialog.findByRole('checkbox', { name: 'Olive & Thyme' }));
    await user.click(dialog.getByRole('checkbox', { name: 'Financial data of Olive & Thyme' }));
    await choose(user, dialog, /Kind/, /^Send events/);
    expect(dialog.queryByRole('checkbox', { name: /Financial data/ })).not.toBeInTheDocument();
    await choose(user, dialog, /Valid for/, /^30 days/);
    await user.click(dialog.getByRole('button', { name: 'Create key' }));

    await waitFor(() => expect(server.sent(route)).toHaveLength(1));
    expect(server.sent(route)[0]?.body).toEqual({
      name: 'Shop events',
      kind: 'ingest',
      expires_in_days: 30,
      clients: [{ client_id: client.id, can_view_financials: false }],
    });
  });

  it('keeps the form and says why when the API refuses', async () => {
    fakeApi(keys([], { [route]: refused(403, 'access_denied') }));
    const user = userEvent.setup();
    openApp(keysPath);
    const dialog = await openDialog(user);
    await enter(user, dialog.getByLabelText('Name'), 'Reporting sheet');
    await user.click(await dialog.findByRole('checkbox', { name: 'Olive & Thyme' }));
    await user.click(dialog.getByRole('button', { name: 'Create key' }));
    expect(await dialog.findByRole('alert')).toHaveTextContent('You do not have access to this.');
    expect(dialog.getByLabelText('Name')).toHaveValue('Reporting sheet');
  });
});
