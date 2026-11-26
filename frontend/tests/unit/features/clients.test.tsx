import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { enter } from '../support/actions';
import { agency, asRole, client, clientsPath, connection, fakeApi, json, otherClient, refused, session, signedIn, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

// The fixtures are dated around this moment, so "3 hours ago" means the same on every run.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-26T12:00:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
  forgetEverything();
});

const third = { ...client, id: 'c3333333-3333-4333-8333-333333333333', name: 'Nile Home', created_at: '2026-11-25T09:00:00Z' };
const clients = `GET /agencies/${agency.id}/clients`;
const connectionsOf = (id: string) => `GET /agencies/${agency.id}/clients/${id}/connections`;

const rowOf = async (name: string) => {
  const cell = await screen.findByText(name, { selector: '.c-table__primary' });
  return within(cell.closest('tr') as HTMLElement);
};
const tile = (label: string) => within(screen.getByText(label).closest('article') as HTMLElement);

describe('the list of clients', () => {
  it('shows each client with the state of its connections, from the API', async () => {
    fakeApi(
      withClients([client, otherClient, third], {
        [client.id]: [connection({ last_successful_sync_at: '2026-11-26T09:00:00Z' }), connection({ id: 'd2', provider: 'instagram', last_successful_sync_at: null })],
        [otherClient.id]: [
          connection({ provider: 'youtube', status: 'reconnect_required', status_reason: 'credential_expired' }),
          connection({ id: 'd3', provider: 'meta_ads' }),
        ],
        [third.id]: [connection({ status: 'disconnected' })],
      }),
    );
    openApp('/');

    const olive = await rowOf('Olive & Thyme');
    expect(olive.getByText(/^Added/)).toHaveTextContent('Added Nov 22, 2026');
    expect(await olive.findByText('Connected')).toBeInTheDocument();
    expect(olive.getByRole('img', { name: 'Sample provider' })).toBeInTheDocument();
    expect(olive.getByRole('img', { name: 'Instagram' })).toBeInTheDocument();
    expect(olive.getByText('3 hours ago')).toBeInTheDocument();
    expect(olive.getByRole('link', { name: 'Open: Olive & Thyme' })).toHaveAttribute('href', `${clientsPath}/${client.id}`);

    const cedar = await rowOf('Cedar Fitness');
    expect(await cedar.findByText('Reconnect YouTube')).toBeInTheDocument();

    // A connection that was removed is no connection: the client has nothing connected.
    const nile = await rowOf('Nile Home');
    expect(await nile.findByText('Connect the first account')).toBeInTheDocument();
    expect(nile.getByText('None yet')).toBeInTheDocument();
    expect(nile.getByText('Never')).toBeInTheDocument();
    expect(nile.getByRole('link', { name: 'Set up: Nile Home' })).toBeInTheDocument();

    await waitFor(() => expect(tile('Connections that need attention').getByText('1')).toBeInTheDocument());
    expect(tile('Active clients').getByText('3')).toBeInTheDocument();
    expect(tile('Clients with nothing connected').getByText('1')).toBeInTheDocument();
    expect(screen.getByText('3 clients')).toBeInTheDocument();
  });

  it('lists clients in the order a person reads names, whatever order the API returns', async () => {
    fakeApi(withClients([third, client, otherClient]));
    openApp('/');
    await rowOf('Nile Home');
    const names = [...document.querySelectorAll('.c-table__primary')].map((cell) => cell.textContent);
    expect(names).toEqual(['Cedar Fitness', 'Nile Home', 'Olive & Thyme']);
  });

  it('says when several accounts of one client need a reconnect', async () => {
    fakeApi(
      withClients([client], {
        [client.id]: [connection({ status: 'reconnect_required' }), connection({ id: 'd2', provider: 'youtube', status: 'reconnect_required' })],
      }),
    );
    openApp('/');
    expect(await (await rowOf('Olive & Thyme')).findByText('2 accounts to reconnect')).toBeInTheDocument();
  });

  it('draws no figure, and no zero, for what it could not read', async () => {
    fakeApi({ ...withClients([client, otherClient]), [connectionsOf(otherClient.id)]: refused(503, 'temporarily_unavailable') });
    openApp('/');

    const cedar = await rowOf('Cedar Fitness');
    expect(await cedar.findByText('Could not be read', { selector: '.c-badge' }, { timeout: 15_000 })).toBeInTheDocument();
    const attention = tile('Connections that need attention');
    expect(attention.getByText('Not every client could be read.')).toBeInTheDocument();
    expect(attention.queryByText('0')).not.toBeInTheDocument();
    // The count of clients itself is known.
    expect(tile('Active clients').getByText('2')).toBeInTheDocument();
  });

  it('reads a long list to its end', async () => {
    const many = Array.from({ length: 100 }, (_item, index) => ({
      ...client,
      id: `c0000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
      name: `Client ${index + 1}`,
    }));
    const server = fakeApi({
      ...signedIn(),
      [clients]: (sent) => {
        const asked = new URL(sent.url).searchParams;
        if (asked.get('status') === 'archived') return json(200, []);
        return json(200, asked.get('offset') === '0' ? many : [third]);
      },
    });
    openApp('/');

    expect(await screen.findByText('101 clients', undefined, { timeout: 15_000 })).toBeInTheDocument();
    const active = server.sent(clients).filter((request) => !request.url.includes('status='));
    expect(active.map((request) => new URL(request.url).search)).toEqual(['?limit=100&offset=0', '?limit=100&offset=100']);
    expect(tile('Active clients').getByText('101')).toBeInTheDocument();
  });

  it('filters by name and says how many are shown', async () => {
    fakeApi(withClients([client, otherClient, third]));
    const user = userEvent.setup();
    openApp('/');
    await rowOf('Nile Home');

    await user.type(screen.getByRole('searchbox', { name: 'Search clients' }), 'OLIVE');
    expect(screen.getByText('1 of 3 clients')).toBeInTheDocument();
    expect(screen.queryByText('Nile Home')).not.toBeInTheDocument();

    await user.clear(screen.getByRole('searchbox', { name: 'Search clients' }));
    await user.type(screen.getByRole('searchbox', { name: 'Search clients' }), 'zebra');
    expect(screen.getByText('No client matches “zebra”.')).toBeInTheDocument();
  });

  it('says so when the list could not be read, and tries again on request', async () => {
    const server = fakeApi({ ...signedIn(), [clients]: refused(403, 'access_denied') });
    const user = userEvent.setup();
    openApp('/');

    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to this.');
    server.routes[clients] = json(200, []);
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: 'No clients yet' })).toBeInTheDocument();
  });
});

describe('what a role may do with clients', () => {
  it('lets an owner add and rename', async () => {
    fakeApi(withClients([client]));
    openApp('/');
    const row = await rowOf('Olive & Thyme');
    expect(screen.getByRole('button', { name: 'Add client' })).toBeInTheDocument();
    expect(row.getByRole('button', { name: 'Actions for Olive & Thyme' })).toBeInTheDocument();
  });

  it.each(['analyst', 'client_viewer'] as const)('shows a %s their clients and no way to change them', async (role) => {
    fakeApi(asRole(role, withClients([client])));
    openApp('/');
    const row = await rowOf('Olive & Thyme');
    expect(screen.getByText('Clients you can open')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add client' })).not.toBeInTheDocument();
    expect(row.queryByRole('button', { name: /Actions for/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Show' })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: 'People with access' })).not.toBeInTheDocument();
    // A client with nothing connected is opened, not set up, by someone who cannot connect.
    expect(await row.findByRole('link', { name: 'Open: Olive & Thyme' })).toBeInTheDocument();
  });

  it('tells a member without a client whom to ask', async () => {
    fakeApi(asRole('analyst', signedIn()));
    openApp('/');
    expect(await screen.findByText('You have not been given a client yet. Ask an owner or admin of the agency.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add client' })).not.toBeInTheDocument();
  });
});

describe('adding and renaming a client', () => {
  it('asks for a name before it sends', async () => {
    const server = fakeApi({ ...signedIn(), [`POST /agencies/${agency.id}/clients`]: json(201, client) });
    const user = userEvent.setup();
    openApp('/');

    await user.click(await screen.findByRole('button', { name: 'Add client' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Add a client' }));
    expect(dialog.getByLabelText('Client name')).toHaveFocus();
    await user.click(dialog.getByRole('button', { name: 'Add client' }));

    expect(await dialog.findByText('This field is needed.')).toBeInTheDocument();
    expect(server.sent(`POST /agencies/${agency.id}/clients`)).toHaveLength(0);
  });

  it('adds the client with the token and opens it, ready for its first connection', async () => {
    let listed: unknown[] = [];
    const server = fakeApi({
      ...withClients([client]),
      [clients]: () => json(200, listed),
      [`POST /agencies/${agency.id}/clients`]: () => {
        listed = [client];
        return json(201, client);
      },
    });
    const user = userEvent.setup();
    openApp('/');

    await user.click(await screen.findByRole('button', { name: 'Add client' }));
    const dialog = within(await screen.findByRole('dialog'));
    await enter(user, dialog.getByLabelText('Client name'), '  Olive & Thyme ');
    await user.click(dialog.getByRole('button', { name: 'Add client' }));

    expect(await screen.findByRole('heading', { name: 'Connections', level: 1 })).toBeInTheDocument();
    const [request] = server.sent(`POST /agencies/${agency.id}/clients`);
    expect(request?.body).toEqual({ name: 'Olive & Thyme' });
    expect(request?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(window.location.pathname).toBe(`${clientsPath}/${client.id}/connections`);
  });

  it('keeps the dialog and says why when the API refuses', async () => {
    fakeApi({ ...signedIn(), [`POST /agencies/${agency.id}/clients`]: refused(403, 'access_denied') });
    const user = userEvent.setup();
    openApp('/');

    await user.click(await screen.findByRole('button', { name: 'Add client' }));
    const dialog = within(await screen.findByRole('dialog'));
    await enter(user, dialog.getByLabelText('Client name'), 'Olive & Thyme');
    await user.click(dialog.getByRole('button', { name: 'Add client' }));

    expect(await dialog.findByRole('alert')).toHaveTextContent('You do not have access to this.');
    expect(dialog.getByLabelText('Client name')).toHaveValue('Olive & Thyme');
  });

  it('renames a client and shows the new name', async () => {
    const renamed = { ...client, name: 'Olive and Thyme' };
    let listed = [client];
    const route = `PATCH /agencies/${agency.id}/clients/${client.id}`;
    const server = fakeApi({
      ...withClients([client]),
      [clients]: () => json(200, listed),
      [route]: () => {
        listed = [renamed];
        return json(200, renamed);
      },
    });
    const user = userEvent.setup();
    openApp('/');

    await user.click((await rowOf('Olive & Thyme')).getByRole('button', { name: 'Actions for Olive & Thyme' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Rename' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Rename Olive & Thyme' }));
    const field = dialog.getByLabelText('Client name');
    expect(field).toHaveValue('Olive & Thyme');
    await user.clear(field);
    await enter(user, field, 'Olive and Thyme');
    await user.click(dialog.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('The client is now called Olive and Thyme.')).toBeInTheDocument();
    expect(server.sent(route)[0]?.body).toEqual({ name: 'Olive and Thyme' });
    expect(await rowOf('Olive and Thyme')).toBeTruthy();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('leaves the dialog without sending anything on Cancel', async () => {
    const server = fakeApi(withClients([client]));
    const user = userEvent.setup();
    openApp('/');

    await user.click((await rowOf('Olive & Thyme')).getByRole('button', { name: 'Actions for Olive & Thyme' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Rename' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(server.requests.filter((request) => request.method !== 'GET')).toHaveLength(0);
  });
});
