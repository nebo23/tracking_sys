import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import type { Member } from '@/api/team';

import { agency, asRole, client, empty, fakeApi, json, member, otherClient, refused, session, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

const teamPath = `/agencies/${agency.id}/team`;
const members = `/agencies/${agency.id}/members`;
type Routes = Parameters<typeof fakeApi>[0];

// Mona is the owner of the agency; the others are synthetic people of the same agency.
const mona = member();
const karim = member({ id: 'b2222222-2222-4222-8222-222222222222', user_id: 'a2222222-2222-4222-8222-222222222222', display_name: 'Karim Adel', email_normalized: 'karim@lumen.example', role: 'admin' });
const youssef = member({
  id: 'b3333333-3333-4333-8333-333333333333',
  user_id: 'a3333333-3333-4333-8333-333333333333',
  display_name: 'Youssef Salah',
  email_normalized: 'youssef@lumen.example',
  role: 'analyst',
  clients: [
    { client_id: client.id, can_view_financials: true, can_view_identities: false },
    { client_id: otherClient.id, can_view_financials: false, can_view_identities: true },
  ],
});
const laila = member({
  id: 'b4444444-4444-4444-8444-444444444444',
  user_id: 'a4444444-4444-4444-8444-444444444444',
  display_name: 'Laila Nabil',
  email_normalized: 'laila@lumen.example',
  role: 'client_viewer',
  status: 'disabled',
  clients: [{ client_id: client.id, can_view_financials: false, can_view_identities: false }],
});
const sara = member({ id: 'b5555555-5555-4555-8555-555555555555', user_id: 'a5555555-5555-4555-8555-555555555555', display_name: 'Sara Fouad', email_normalized: 'sara@lumen.example', role: 'analyst' });
const closed = member({
  id: 'b6666666-6666-4666-8666-666666666666',
  user_id: 'a6666666-6666-4666-8666-666666666666',
  display_name: null,
  email_normalized: null,
  account: 'closed',
  status: 'disabled',
  role: 'analyst',
});
const owner2 = member({ id: 'b7777777-7777-4777-8777-777777777777', user_id: 'a7777777-7777-4777-8777-777777777777', display_name: 'Hana Owner', email_normalized: 'hana@lumen.example', role: 'owner' });

const everyone = [mona, karim, youssef, laila, sara, closed, owner2];

const team = (listed: Member[] = everyone, more: Routes = {}): Routes => ({
  ...withClients([client, otherClient]),
  [`GET ${members}`]: json(200, listed),
  [`GET /agencies/${agency.id}/invitations`]: json(200, []),
  ...more,
});

const rowOf = async (name: string) => within((await screen.findByText(name, { selector: '.c-table__primary, .c-table__primary *' })).closest('tr') as HTMLElement);
const actions = async (user: UserEvent, name: string) => {
  await user.click((await rowOf(name)).getByRole('button', { name: `Actions for ${name}` }));
  return within(await screen.findByRole('menu'));
};

describe('the members of an agency', () => {
  it('lists each member by name, with role, clients, financial data and state', async () => {
    fakeApi(team());
    openApp(teamPath);

    expect(await screen.findByRole('tab', { name: /Members/, selected: true })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('tab', { name: /Members/ })).toHaveTextContent('Members7'));
    await waitFor(() => expect(screen.getByRole('tab', { name: /Invitations/ })).toHaveTextContent('Invitations0'));

    const you = await rowOf('Mona Hassan');
    expect(you.getByText('(you)')).toBeInTheDocument();
    expect(you.getByText('mona@lumen.example')).toBeInTheDocument();
    expect(you.getByText('Owner')).toBeInTheDocument();
    expect(you.getByText('All clients')).toBeInTheDocument();
    expect(you.getByText('All')).toBeInTheDocument();
    expect(you.getByText('Active')).toBeInTheDocument();

    const analyst = await rowOf('Youssef Salah');
    expect(analyst.getByText('2 clients')).toBeInTheDocument();
    expect(analyst.getByText('1 of 2')).toBeInTheDocument();

    const viewer = await rowOf('Laila Nabil');
    // One client is named; the paused member says so.
    expect(viewer.getByText('Olive & Thyme')).toBeInTheDocument();
    expect(viewer.getByText('None')).toBeInTheDocument();
    expect(viewer.getByText('Access paused')).toBeInTheDocument();

    expect((await rowOf('Sara Fouad')).getByText('No client yet')).toBeInTheDocument();
  });

  it('never names a closed account, and lists it last', async () => {
    fakeApi(team());
    openApp(teamPath);
    const row = await rowOf('Closed account');
    expect(row.getAllByText('Closed account')).toHaveLength(2);
    expect(row.queryByRole('button')).not.toBeInTheDocument();
    const names = [...document.querySelectorAll('tbody tr')].map((tr) => tr.querySelector('.c-table__primary')?.textContent);
    expect(names.at(-1)).toBe('Closed account');
    expect(names.slice(0, 3)).toEqual(['Hana Owner', 'Karim Adel', 'Laila Nabil']);
  });

  it('offers no change to a person\'s own access, and lets an owner change everyone else', async () => {
    fakeApi(team());
    openApp(teamPath);
    expect((await rowOf('Mona Hassan')).queryByRole('button')).not.toBeInTheDocument();
    for (const name of ['Hana Owner', 'Karim Adel', 'Youssef Salah']) {
      expect((await rowOf(name)).getByRole('button', { name: `Actions for ${name}` })).toBeInTheDocument();
    }
  });

  it('does not let an admin change an owner', async () => {
    const asAdmin = everyone.map((item) => (item.id === mona.id ? { ...item, role: 'admin' as const } : item));
    fakeApi(asRole('admin', team(asAdmin)));
    openApp(teamPath);
    expect((await rowOf('Hana Owner')).queryByRole('button')).not.toBeInTheDocument();
    expect((await rowOf('Youssef Salah')).getByRole('button', { name: 'Actions for Youssef Salah' })).toBeInTheDocument();
  });

  it('says so when the members could not be read, and tries again on request', async () => {
    const server = fakeApi(team(everyone, { [`GET ${members}`]: refused(503, 'temporarily_unavailable') }));
    const user = userEvent.setup();
    openApp(teamPath);
    expect(await screen.findByRole('alert', undefined, { timeout: 15_000 })).toHaveTextContent('Connect is busy for a moment.');
    server.routes[`GET ${members}`] = json(200, everyone);
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await rowOf('Youssef Salah')).toBeTruthy();
  });
});

describe('changing a member\'s access', () => {
  const grant = (who: Member, clientId: string) => `PUT ${members}/${who.id}/clients/${clientId}`;
  const ungrant = (who: Member, clientId: string) => `DELETE ${members}/${who.id}/clients/${clientId}`;

  it('shows the present role and clients, and sends only what changed', async () => {
    const server = fakeApi(
      team(everyone, {
        [grant(youssef, client.id)]: empty(),
        [grant(youssef, otherClient.id)]: empty(),
        [ungrant(youssef, otherClient.id)]: empty(),
      }),
    );
    const user = userEvent.setup();
    openApp(teamPath);

    await user.click((await actions(user, 'Youssef Salah')).getByRole('menuitem', { name: 'Change access' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Access of Youssef Salah' }));
    expect(dialog.getByRole('button', { name: /Role/ })).toHaveTextContent('Analyst');
    expect(dialog.getByRole('checkbox', { name: 'Olive & Thyme' })).toBeChecked();
    expect(dialog.getByRole('checkbox', { name: 'Financial data of Olive & Thyme' })).toBeChecked();
    expect(dialog.getByRole('checkbox', { name: 'Cedar Fitness' })).toBeChecked();
    expect(dialog.getByRole('checkbox', { name: 'Financial data of Cedar Fitness' })).not.toBeChecked();

    // Financial data of Olive & Thyme is taken away; Cedar Fitness is no longer opened.
    await user.click(dialog.getByRole('checkbox', { name: 'Financial data of Olive & Thyme' }));
    await user.click(dialog.getByRole('checkbox', { name: 'Cedar Fitness' }));
    await user.click(dialog.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('The access of Youssef Salah is saved.')).toBeInTheDocument();
    const [changed] = server.sent(grant(youssef, client.id));
    expect(changed?.body).toEqual({ can_view_financials: false });
    expect(changed?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    // The identity flag is never sent, so the API keeps it as it was.
    expect(JSON.stringify(changed?.body)).not.toContain('identities');
    expect(server.sent(ungrant(youssef, otherClient.id))).toHaveLength(1);
    expect(server.sent(grant(youssef, otherClient.id))).toHaveLength(0);
    expect(server.sent(`PATCH ${members}/${youssef.id}`)).toHaveLength(0);
  });

  it('leaves a grant that did not change as it is', async () => {
    const server = fakeApi(team(everyone, { [grant(youssef, otherClient.id)]: empty() }));
    const user = userEvent.setup();
    openApp(teamPath);
    await user.click((await actions(user, 'Youssef Salah')).getByRole('menuitem', { name: 'Change access' }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.click(dialog.getByRole('checkbox', { name: 'Financial data of Cedar Fitness' }));
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    await screen.findByText('The access of Youssef Salah is saved.');
    expect(server.sent(grant(youssef, otherClient.id))[0]?.body).toEqual({ can_view_financials: true });
    // Olive & Thyme kept its access and its financial data: nothing was sent for it.
    expect(server.requests.filter((request) => request.method !== 'GET')).toHaveLength(1);
  });

  it('gives a role that reads only granted clients its clients before the role', async () => {
    const order: string[] = [];
    const server = fakeApi(
      team(everyone, {
        [grant(karim, client.id)]: (sent) => {
          order.push(`${sent.method} grant`);
          return empty();
        },
        [`PATCH ${members}/${karim.id}`]: (sent) => {
          order.push(`${sent.method} role`);
          return json(200, { ...karim, role: 'analyst' });
        },
      }),
    );
    const user = userEvent.setup();
    openApp(teamPath);

    await user.click((await actions(user, 'Karim Adel')).getByRole('menuitem', { name: 'Change access' }));
    const dialog = within(await screen.findByRole('dialog'));
    expect(dialog.getByText('Owners and admins open every client and see its financial data.')).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: /Role/ }));
    await user.click(await screen.findByRole('option', { name: /^Analyst/ }));

    // A role that reads only granted clients needs one.
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    expect(await dialog.findByText('Choose at least one client.')).toBeInTheDocument();
    expect(server.requests.filter((request) => request.method !== 'GET')).toHaveLength(0);

    await user.click(dialog.getByRole('checkbox', { name: 'Olive & Thyme' }));
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    await screen.findByText('The access of Karim Adel is saved.');
    expect(order).toEqual(['PUT grant', 'PATCH role']);
    expect(server.sent(`PATCH ${members}/${karim.id}`)[0]?.body).toEqual({ role: 'analyst' });
  });

  it('offers an admin no owner role', async () => {
    const asAdmin = everyone.map((item) => (item.id === mona.id ? { ...item, role: 'admin' as const } : item));
    fakeApi(asRole('admin', team(asAdmin)));
    const user = userEvent.setup();
    openApp(teamPath);
    await user.click((await actions(user, 'Youssef Salah')).getByRole('menuitem', { name: 'Change access' }));
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /Role/ }));
    await screen.findByRole('option', { name: /^Admin/ });
    expect(screen.queryByRole('option', { name: /^Owner/ })).not.toBeInTheDocument();
  });

  it('explains that an agency keeps an owner, and shows what the API now holds', async () => {
    const server = fakeApi(team(everyone, { [`PATCH ${members}/${owner2.id}`]: refused(409, 'state_conflict') }));
    const user = userEvent.setup();
    openApp(teamPath);
    await user.click((await actions(user, 'Hana Owner')).getByRole('menuitem', { name: 'Change access' }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.click(dialog.getByRole('button', { name: /Role/ }));
    await user.click(await screen.findByRole('option', { name: /^Admin/ }));
    const before = server.sent(`GET ${members}`).length;
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    expect(await dialog.findByRole('alert')).toHaveTextContent('An agency must keep at least one active owner.');
    await waitFor(() => expect(server.sent(`GET ${members}`).length).toBeGreaterThan(before));
  });
});

describe('pausing and restoring access', () => {
  it('pauses access after asking', async () => {
    let listed = everyone;
    const route = `PATCH ${members}/${youssef.id}`;
    const server = fakeApi(
      team(everyone, {
        [`GET ${members}`]: () => json(200, listed),
        [route]: () => {
          listed = everyone.map((item) => (item.id === youssef.id ? { ...item, status: 'disabled' } : item));
          return json(200, { ...youssef, status: 'disabled' });
        },
      }),
    );
    const user = userEvent.setup();
    openApp(teamPath);

    await user.click((await actions(user, 'Youssef Salah')).getByRole('menuitem', { name: 'Pause access' }));
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Pause the access of Youssef Salah?' }));
    await user.click(dialog.getByRole('button', { name: 'Keep access' }));
    expect(server.sent(route)).toHaveLength(0);

    await user.click((await actions(user, 'Youssef Salah')).getByRole('menuitem', { name: 'Pause access' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Pause access' }));
    expect(await screen.findByText('The access of Youssef Salah is paused.')).toBeInTheDocument();
    expect(server.sent(route)[0]?.body).toEqual({ status: 'disabled' });
    expect((await rowOf('Youssef Salah')).getByText('Access paused')).toBeInTheDocument();
  });

  it('restores paused access in one step', async () => {
    const route = `PATCH ${members}/${laila.id}`;
    const server = fakeApi(team(everyone, { [route]: json(200, { ...laila, status: 'active' }) }));
    const user = userEvent.setup();
    openApp(teamPath);
    await user.click((await actions(user, 'Laila Nabil')).getByRole('menuitem', { name: 'Restore access' }));
    expect(await screen.findByText('The access of Laila Nabil is restored.')).toBeInTheDocument();
    expect(server.sent(route)[0]?.body).toEqual({ status: 'active' });
  });

  it('says why a restore was refused', async () => {
    fakeApi(team(everyone, { [`PATCH ${members}/${laila.id}`]: refused(409, 'plan_limit_reached') }));
    const user = userEvent.setup();
    openApp(teamPath);
    await user.click((await actions(user, 'Laila Nabil')).getByRole('menuitem', { name: 'Restore access' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("This goes beyond what the agency's plan allows.");
  });
});
