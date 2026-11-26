import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { agency, client, fakeApi, json, member, otherClient, person, refused, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

afterEach(forgetEverything);

const auditPath = `/agencies/${agency.id}/audit`;
const youssef = member({ id: 'b3333333-3333-4333-8333-333333333333', user_id: 'a3333333-3333-4333-8333-333333333333', display_name: 'Youssef Salah', role: 'analyst' });
const closed = member({ id: 'b6666666-6666-4666-8666-666666666666', user_id: 'a6666666-6666-4666-8666-666666666666', display_name: null, email_normalized: null, account: 'closed' });

let made = 0;
const event = (action: string, given: Record<string, unknown> = {}) => {
  made += 1;
  return {
    id: `e0000000-0000-4000-8000-${String(made).padStart(12, '0')}`,
    agency_id: agency.id,
    client_id: null,
    actor_user_id: person.id,
    action,
    resource_type: 'thing',
    resource_id: '00000000-0000-4000-8000-000000000000',
    occurred_at: '2026-11-26T10:00:00Z',
    ...given,
  };
};

const world = (events: unknown[]) => ({
  ...withClients([client], {}, [otherClient]),
  [`GET /agencies/${agency.id}/members`]: json(200, [member(), youssef, closed]),
  [`GET /agencies/${agency.id}/invitations`]: json(200, [
    {
      id: 'f1111111-1111-4111-8111-111111111111',
      agency_id: agency.id,
      email_normalized: 'sara@lumen.example',
      role: 'analyst',
      status: 'pending',
      created_at: '2026-11-25T10:00:00Z',
      expires_at: '2026-12-02T10:00:00Z',
    },
  ]),
  [`GET /agencies/${agency.id}/service-credentials`]: json(200, [
    {
      id: 'f2222222-2222-4222-8222-222222222222',
      agency_id: agency.id,
      name: 'Reporting sheet',
      kind: 'read',
      status: 'active',
      created_at: '2026-11-20T10:00:00Z',
      expires_at: '2027-02-18T10:00:00Z',
    },
  ]),
  [`GET /agencies/${agency.id}/audit`]: json(200, events),
});

const rowOf = (text: string) => within(screen.getByText(text).closest('tr') as HTMLElement);

describe('the audit log', () => {
  it('says who did what, to which client and when, with the names of the agency', async () => {
    fakeApi(
      world([
        event('client.created', { resource_id: client.id, client_id: client.id }),
        event('client.updated', { resource_id: otherClient.id, client_id: otherClient.id }),
        event('grant.created', { actor_user_id: person.id, resource_id: youssef.id, client_id: client.id }),
        event('invitation.created', { resource_id: 'f1111111-1111-4111-8111-111111111111' }),
        event('credential.revoked', { resource_id: 'f2222222-2222-4222-8222-222222222222' }),
        event('invitation.accepted', { actor_user_id: youssef.user_id }),
        event('connector.connected', { client_id: client.id }),
        event('membership.updated', { actor_user_id: closed.user_id, resource_id: closed.id }),
      ]),
    );
    openApp(auditPath);

    expect(await screen.findByRole('heading', { name: 'Audit log', level: 1 })).toBeInTheDocument();
    expect(await screen.findByText('Added the client Olive & Thyme')).toBeInTheDocument();
    // An archived client is still named.
    expect(rowOf('Changed the client Cedar Fitness').getByText('Cedar Fitness', { selector: 'td' })).toBeInTheDocument();
    const grant = rowOf('Gave Youssef Salah access to a client');
    expect(grant.getByText('Mona Hassan')).toBeInTheDocument();
    expect(grant.getByText('Olive & Thyme')).toBeInTheDocument();
    expect(screen.getByText('Invited sara@lumen.example')).toBeInTheDocument();
    expect(screen.getByText('Revoked the API key Reporting sheet')).toBeInTheDocument();
    expect(rowOf('Accepted an invitation').getByText('Youssef Salah')).toBeInTheDocument();
    expect(rowOf('Connected an account').getByText('Olive & Thyme')).toBeInTheDocument();
    // A closed account is never named, as actor or as subject.
    const closedRow = rowOf('Changed the role or access of Closed account');
    expect(closedRow.getByText('Closed account', { selector: '.c-table__primary' })).toBeInTheDocument();
    expect(screen.getByText('8 changes are shown. Connect records every change and never edits or removes one.')).toBeInTheDocument();
  });

  it('names an action it does not know by the API\'s own code, and an unknown actor as such', async () => {
    fakeApi(world([event('something.new', { actor_user_id: 'a9999999-9999-4999-8999-999999999999' })]));
    openApp(auditPath);
    const code = await screen.findByText('something.new');
    const row = within(code.closest('tr') as HTMLElement);
    expect(code.closest('td')).toHaveTextContent('Made a change something.new');
    expect(row.getByText('someone who is not a member')).toBeInTheDocument();
  });

  it('says so when nothing is recorded', async () => {
    fakeApi(world([]));
    openApp(auditPath);
    expect(await screen.findByRole('heading', { name: 'Nothing is recorded yet' })).toBeInTheDocument();
  });

  it('says so when the log could not be read, and tries again on request', async () => {
    const server = fakeApi({ ...world([]), [`GET /agencies/${agency.id}/audit`]: refused(403, 'access_denied') });
    const user = userEvent.setup();
    openApp(auditPath);
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to this.');
    server.routes[`GET /agencies/${agency.id}/audit`] = json(200, [event('agency.created')]);
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Created the agency')).toBeInTheDocument();
  });

  it('asks the API for its newest hundred changes', async () => {
    const server = fakeApi(world([event('agency.created')]));
    openApp(auditPath);
    await screen.findByText('Created the agency');
    expect(new URL(server.sent(`GET /agencies/${agency.id}/audit`)[0]?.url ?? '').search).toBe('?limit=100');
  });
});
