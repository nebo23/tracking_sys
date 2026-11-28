import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { clientQuery } from '@/api/clients';

import { agency, asRole, client, clientList, fakeApi, json, member, otherClient, refused, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

const clients = `GET /agencies/${agency.id}/clients`;
const patchOf = (id: string) => `PATCH /agencies/${agency.id}/clients/${id}`;

const rowOf = async (name: string) => within((await screen.findByText(name, { selector: '.c-table__primary' })).closest('tr') as HTMLElement);
const tile = (label: string) => within(screen.getByText(label).closest('article') as HTMLElement);
const showArchived = async (user: UserEvent) => user.click(within(await screen.findByRole('group', { name: 'Show' })).getByRole('button', { name: 'Archived' }));

describe('archived clients', () => {
  it('are counted under the active ones and listed on request, to be restored', async () => {
    let active = [client];
    let archived = [otherClient];
    const server = fakeApi({
      ...withClients([client, otherClient]),
      [clients]: (sent) => clientList(active, archived)(sent),
      [patchOf(otherClient.id)]: () => {
        active = [client, otherClient];
        archived = [];
        return json(200, { ...otherClient, status: 'active' });
      },
    });
    const user = userEvent.setup();
    openApp('/');

    await rowOf('Olive & Thyme');
    await waitFor(() => expect(tile('Active clients').getByText('1 archived')).toBeInTheDocument());
    expect(screen.queryByText('Cedar Fitness')).not.toBeInTheDocument();

    await showArchived(user);
    expect(within(screen.getByRole('group', { name: 'Show' })).getByRole('button', { name: 'Archived' })).toHaveAttribute('aria-pressed', 'true');
    const row = await rowOf('Cedar Fitness');
    expect(screen.queryByText('Olive & Thyme', { selector: '.c-table__primary' })).not.toBeInTheDocument();
    expect(screen.getByText('1 archived client')).toBeInTheDocument();
    // An archived client cannot be opened: the row offers its restoration only.
    expect(row.queryByRole('link')).not.toBeInTheDocument();

    await user.click(row.getByRole('button', { name: 'Restore Cedar Fitness' }));
    expect(await screen.findByText('Cedar Fitness is active again.')).toBeInTheDocument();
    expect(server.sent(patchOf(otherClient.id))[0]?.body).toEqual({ status: 'active' });
    expect(await screen.findByText('No client is archived.')).toBeInTheDocument();

    await user.click(within(screen.getByRole('group', { name: 'Show' })).getByRole('button', { name: 'Active' }));
    expect(await rowOf('Cedar Fitness')).toBeTruthy();
  });

  it('are asked for only by the people who manage the agency', async () => {
    const server = fakeApi(asRole('analyst', withClients([client])));
    openApp('/');
    await rowOf('Olive & Thyme');
    expect(screen.queryByRole('group', { name: 'Show' })).not.toBeInTheDocument();
    expect(server.sent(clients).some((request) => request.url.includes('status=archived'))).toBe(false);
    expect(server.sent(`GET /agencies/${agency.id}/members`)).toHaveLength(0);
  });

  it('keep the list in view when every client is archived', async () => {
    fakeApi(withClients([], {}, [client]));
    const user = userEvent.setup();
    openApp('/');
    expect(await screen.findByText('No client is active. Restore an archived client, or add a new one.')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'No clients yet' })).not.toBeInTheDocument();
    await showArchived(user);
    expect(await rowOf('Olive & Thyme')).toBeTruthy();
  });
});

describe('archiving a client', () => {
  it('asks first, then archives it and forgets what was loaded for it', async () => {
    let active = [client, otherClient];
    let archived: (typeof client)[] = [];
    const server = fakeApi({
      ...withClients([client, otherClient]),
      [clients]: (sent) => clientList(active, archived)(sent),
      [patchOf(client.id)]: () => {
        active = [otherClient];
        archived = [client];
        return json(200, { ...client, status: 'archived' });
      },
    });
    const user = userEvent.setup();
    const { queryClient } = openApp('/');
    queryClient.setQueryData(clientQuery(agency.id, client.id).queryKey, client);

    const open = async () => {
      await user.click((await rowOf('Olive & Thyme')).getByRole('button', { name: 'Actions for Olive & Thyme' }));
      await user.click(await screen.findByRole('menuitem', { name: 'Archive' }));
      return within(await screen.findByRole('alertdialog', { name: 'Archive Olive & Thyme?' }));
    };

    const first = await open();
    expect(first.getByText(/Nothing is deleted/)).toBeInTheDocument();
    await user.click(first.getByRole('button', { name: 'Keep it active' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(server.sent(patchOf(client.id))).toHaveLength(0);

    await user.click((await open()).getByRole('button', { name: 'Archive' }));
    expect(await screen.findByText(/Olive & Thyme is archived\./)).toBeInTheDocument();
    expect(server.sent(patchOf(client.id))[0]?.body).toEqual({ status: 'archived' });
    expect(queryClient.getQueryData(clientQuery(agency.id, client.id).queryKey)).toBeUndefined();
    await waitFor(() => expect(screen.queryByText('Olive & Thyme', { selector: '.c-table__primary' })).not.toBeInTheDocument());
    await waitFor(() => expect(tile('Active clients').getByText('1 archived')).toBeInTheDocument());
  });

  it('says why the API refused', async () => {
    fakeApi({ ...withClients([client]), [patchOf(client.id)]: refused(403, 'access_denied') });
    const user = userEvent.setup();
    openApp('/');
    await user.click((await rowOf('Olive & Thyme')).getByRole('button', { name: 'Actions for Olive & Thyme' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Archive' }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.click(dialog.getByRole('button', { name: 'Archive' }));
    expect(await dialog.findByRole('alert')).toHaveTextContent('You do not have access to this.');
  });
});

describe('the people who can open a client', () => {
  it('are every active manager and the active members it was granted to', async () => {
    const grant = { client_id: client.id, can_view_financials: false, can_view_identities: false };
    fakeApi({
      ...withClients([client, otherClient]),
      [`GET /agencies/${agency.id}/members`]: json(200, [
        member(),
        member({ id: 'b2', user_id: 'u2', role: 'admin', display_name: 'Karim Adel' }),
        member({ id: 'b3', user_id: 'u3', role: 'analyst', clients: [grant] }),
        member({ id: 'b4', user_id: 'u4', role: 'client_viewer', status: 'disabled', clients: [grant] }),
        member({ id: 'b5', user_id: 'u5', role: 'analyst', account: 'closed', display_name: null, email_normalized: null, clients: [grant] }),
        member({ id: 'b6', user_id: 'u6', role: 'admin', status: 'disabled' }),
      ]),
    });
    openApp('/');
    expect(await screen.findByRole('columnheader', { name: 'People with access' })).toBeInTheDocument();
    const cellOf = async (name: string) => (await rowOf(name)).getAllByRole('cell').at(-2);
    await waitFor(async () => expect(await cellOf('Olive & Thyme')).toHaveTextContent('3'));
    expect(await cellOf('Cedar Fitness')).toHaveTextContent('2');
  });

  it('are not counted when the members could not be read', async () => {
    fakeApi({ ...withClients([client]), [`GET /agencies/${agency.id}/members`]: refused(403, 'access_denied') });
    openApp('/');
    const cell = (await rowOf('Olive & Thyme')).getAllByRole('cell').at(-2) as HTMLElement;
    await waitFor(() => expect(within(cell).getByText('Could not be read')).toBeInTheDocument(), { timeout: 15_000 });
  });
});
