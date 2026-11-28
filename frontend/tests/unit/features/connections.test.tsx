import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clientKey } from '@/api/clients';
import { pendingConnection } from '@/features/connections/pendingConnection';
import { goTo } from '@/lib/browser';

import { enter, everythingStored } from '../support/actions';
import { agency, asRole, client, connection, connectionsPath, coverage, empty, fakeApi, json, refused, session, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

// Leaving the application for a provider is recorded instead of done.
vi.mock('@/lib/browser', async (original) => ({ ...(await original<typeof import('@/lib/browser')>()), goTo: vi.fn() }));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-26T12:00:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
  forgetEverything();
});

const base = `/agencies/${agency.id}/clients/${client.id}/connections`;
const one = `${base}/${connection().id}`;
const quiet = { state: 'idle', kind: null, reason: null, next_attempt_at: null };
type Routes = Parameters<typeof fakeApi>[0];

/** The client with the given connections, each with the same coverage unless a test replaces it. */
const serving = (connections: unknown[], given: Record<string, unknown> = {}, more: Routes = {}): Routes => ({
  ...withClients([client], { [client.id]: connections }),
  [`GET ${one}/coverage`]: json(200, coverage(given)),
  ...more,
});

const card = async (name = 'Sample provider') => within((await screen.findByRole('heading', { name, level: 2 })).closest('article') as HTMLElement);

describe('a connected account', () => {
  it('shows what it is, whether it works and how much is stored', async () => {
    fakeApi(serving([connection()]));
    openApp(connectionsPath);

    const account = await card();
    expect(account.getByText('@olive.thyme')).toBeInTheDocument();
    expect(account.getByText('Connected')).toBeInTheDocument();
    expect(await account.findByText('3 hours ago')).toBeInTheDocument();
    expect(account.getByText('Fresh')).toBeInTheDocument();
    expect(account.getByText('Account days')).toBeInTheDocument();
    expect(account.getByText('Complete')).toBeInTheDocument();
    expect(account.getByRole('img', { name: 'Oct 27, 2026 to Nov 25, 2026' })).toBeInTheDocument();
    expect(account.getByRole('img', { name: '38 of 100 used today' })).toBeInTheDocument();
    // Nothing is running, so the latest run is not mentioned.
    expect(account.queryByText('Latest sync')).not.toBeInTheDocument();
  });

  it.each([
    ['stale', 'Stale'],
    ['never_synced', 'Not synced'],
  ])('says when its data is %s, and never calls it fresh', async (freshness, word) => {
    fakeApi(serving([connection()], { freshness, last_successful_sync_at: freshness === 'stale' ? '2026-11-22T09:00:00Z' : null }));
    openApp(connectionsPath);
    const account = await card();
    expect(await account.findByText(word)).toBeInTheDocument();
    expect(account.queryByText('Fresh')).not.toBeInTheDocument();
  });

  it('names a stream it does not know by the API\'s own word, and shows no range for one that was never read', async () => {
    const streams = [
      { stream: 'something_new', state: 'not_synced', covered_from: null, complete_through: null, history_limit_days: 30, sync: quiet },
      { stream: 'media', state: 'partial', covered_from: '2026-11-01T00:00:00Z', complete_through: '2026-11-20T00:00:00Z', history_limit_days: 730, sync: quiet },
    ];
    fakeApi(serving([connection()], { streams }));
    openApp(connectionsPath);

    const account = await card();
    expect(await account.findByText('something_new')).toBeInTheDocument();
    expect(account.getByText('Posts and reels')).toBeInTheDocument();
    expect(account.getByText('Partial')).toBeInTheDocument();
    expect(account.getAllByRole('img', { name: / to / })).toHaveLength(1);
  });

  it.each([
    [{ state: 'queued', kind: 'incremental', reason: null, next_attempt_at: null }, 'Waiting to start', null],
    [{ state: 'running', kind: 'incremental', reason: null, next_attempt_at: null }, 'Reading now', null],
    [{ state: 'delayed', kind: 'incremental', reason: 'rate_limited', next_attempt_at: '2026-11-26T14:00:00Z' }, 'Delayed', 'The provider asked Connect to slow down.'],
    [{ state: 'budget_stopped', kind: 'incremental', reason: 'budget_exhausted', next_attempt_at: '2026-11-27T00:00:00Z' }, 'Paused for today', "Today's allowance for this account is used."],
    [{ state: 'failed', kind: 'incremental', reason: 'forbidden', next_attempt_at: null }, 'Failed', 'The provider refused the request.'],
  ])('says what the latest run is doing ($0.state)', async (sync, word, why) => {
    fakeApi(serving([connection()], { sync }));
    openApp(connectionsPath);
    const account = await card();
    expect(await account.findByText('Latest sync')).toBeInTheDocument();
    expect(account.getByText(word)).toBeInTheDocument();
    if (why) expect(account.getByText(why, { exact: false })).toBeInTheDocument();
    if (sync.next_attempt_at) expect(account.getByText(/Next attempt:/)).toBeInTheDocument();
  });

  it('says why the allowance of the day is used up', async () => {
    const cost = { ...coverage().cost, consumed: 100, remaining: 0, state: 'exhausted', reason: 'connection_allocation' };
    fakeApi(serving([connection()], { cost }));
    openApp(connectionsPath);
    const account = await card();
    expect(await account.findByText('This account has used its allowance for today.')).toBeInTheDocument();
    expect(account.getByRole('img', { name: '100 of 100 used today' })).toHaveClass('c-meter--danger');
  });

  it('shows one allowance for each of a provider\'s limits', async () => {
    const bucket = (name: string, consumed: number, allocation: number) => ({
      bucket: name,
      unit: 'unit',
      period_start: '2026-11-26T08:00:00Z',
      consumed,
      allocation,
      remaining: allocation - consumed,
      state: 'available',
    });
    const cost = { ...coverage().cost, buckets: [bucket('youtube_data', 12, 100), bucket('youtube_analytics', 3, 30)] };
    fakeApi(serving([connection({ provider: 'youtube' })], { cost }));
    openApp(connectionsPath);
    const account = await card('YouTube');
    expect(await account.findByRole('img', { name: '12 of 100 used today' })).toBeInTheDocument();
    expect(account.getByRole('img', { name: '3 of 30 used today' })).toBeInTheDocument();
  });

  it('says so when its coverage could not be read, and still shows the account', async () => {
    fakeApi(serving([connection()], {}, { [`GET ${one}/coverage`]: refused(403, 'access_denied') }));
    openApp(connectionsPath);
    const account = await card();
    expect(await account.findByRole('alert')).toHaveTextContent('Only an owner or admin of the agency can do this.');
    expect(account.getByText('Connected')).toBeInTheDocument();
  });
});

describe('an account that stopped', () => {
  const stopped = (reason: string) =>
    connection({ provider: 'youtube', status: 'reconnect_required', status_reason: reason, actions: { reconnect: true, disconnect: true } });

  it.each([
    ['credential_expired', 'YouTube no longer accepts this connection'],
    ['provider_revoked', 'Access was removed at YouTube'],
    ['a_reason_added_later', 'YouTube no longer accepts this connection'],
  ])('says why (%s) and offers one action', async (reason, sentence) => {
    fakeApi(serving([stopped(reason)], { status: 'reconnect_required', freshness: 'stale' }));
    openApp(connectionsPath);
    const account = await card('YouTube');
    expect(account.getByText('Reconnect needed')).toBeInTheDocument();
    expect(account.getByText(sentence)).toBeInTheDocument();
    expect(account.getByText('Stored data stays available. New data stops until you reconnect the account.')).toBeInTheDocument();
    expect(account.getByRole('button', { name: 'Reconnect' })).toBeInTheDocument();
    // A state of the page is read in its place; it is not announced as news on every visit.
    expect(account.queryByRole('alert')).not.toBeInTheDocument();
    expect(account.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
  });

  it('tells a person who cannot reconnect who can', async () => {
    const forMember = { ...stopped('credential_expired'), actions: { reconnect: false, disconnect: false } };
    fakeApi(asRole('analyst', serving([forMember], { status: 'reconnect_required' })));
    openApp(connectionsPath);
    const account = await card('YouTube');
    expect(account.getByText('Stored data stays available. New data stops until an owner or admin reconnects the account.')).toBeInTheDocument();
    expect(account.queryByRole('button')).not.toBeInTheDocument();
  });

  it('reconnects a provider that needs nothing more with one request, and goes where the API says', async () => {
    const instagram = connection({ provider: 'instagram', status: 'reconnect_required', actions: { reconnect: true, disconnect: true } });
    const server = fakeApi(
      serving([instagram], { status: 'reconnect_required' }, { [`POST ${one}/reconnect`]: json(200, { authorization_url: 'https://provider.example/authorize?state=abc' }) }),
    );
    const user = userEvent.setup();
    openApp(connectionsPath);

    await user.click((await card('Instagram')).getByRole('button', { name: 'Reconnect' }));

    await waitFor(() => expect(goTo).toHaveBeenCalledWith('https://provider.example/authorize?state=abc'));
    expect(server.sent(`POST ${one}/reconnect`)[0]?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(pendingConnection.get()).toEqual({ agencyId: agency.id, clientId: client.id });
  });

  it('asks for the account holder\'s approval again before reconnecting a provider that needs it', async () => {
    const server = fakeApi(
      serving([stopped('credential_expired')], { status: 'reconnect_required' }, { [`POST ${one}/reconnect`]: json(200, { authorization_url: 'https://accounts.example/o/oauth2' }) }),
    );
    const user = userEvent.setup();
    openApp(connectionsPath);

    await user.click((await card('YouTube')).getByRole('button', { name: 'Reconnect' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Reconnect YouTube' }));
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    expect(await dialog.findByText('Tick the box to give this approval before you continue.')).toBeInTheDocument();
    expect(server.sent(`POST ${one}/reconnect`)).toHaveLength(0);

    await user.click(dialog.getByRole('checkbox', { name: /approve the agency/ }));
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));

    await waitFor(() => expect(goTo).toHaveBeenCalledWith('https://accounts.example/o/oauth2'));
    expect(server.sent(`POST ${one}/reconnect`)[0]?.body).toEqual({ agent_approval: { approved: true, disclosure: 'dev-agent-approval-1' } });
  });

  it('shows an account that is being removed, with the date its data is gone, and no way to use it', async () => {
    const leaving = connection({
      status: 'disconnecting',
      status_reason: 'user_requested',
      actions: { reconnect: false, disconnect: false },
      disconnect: {
        requested_at: '2026-11-26T11:00:00Z',
        completed_at: null,
        revocation: 'pending',
        secret_destruction: 'pending',
        data_purge: 'pending',
        purge_due_at: '2026-11-29T11:00:00Z',
        deadline_met: null,
      },
    });
    fakeApi(serving([leaving], { status: 'disconnecting' }));
    openApp(connectionsPath);
    const account = await card();
    expect(account.getByText('Disconnecting')).toBeInTheDocument();
    expect(account.getByText('This account is being disconnected')).toBeInTheDocument();
    expect(account.getByText(/Its stored data is removed by/)).toHaveTextContent('Nov 29, 2026');
    expect(account.queryByRole('button')).not.toBeInTheDocument();
  });

  it('lists accounts that were disconnected apart, with what became of them', async () => {
    const gone = (id: string, revocation: string) =>
      connection({
        id,
        provider: 'instagram',
        account: null,
        status: 'disconnected',
        actions: { reconnect: false, disconnect: false },
        disconnect: {
          requested_at: '2026-11-20T11:00:00Z',
          completed_at: '2026-11-21T11:00:00Z',
          revocation,
          secret_destruction: 'done',
          data_purge: 'done',
          purge_due_at: '2026-11-23T11:00:00Z',
          deadline_met: true,
        },
      });
    fakeApi(serving([gone('d8', 'unsupported'), gone('d9', 'failed')]));
    openApp(connectionsPath);

    const past = within((await screen.findByRole('heading', { name: 'Past connections' })).closest('section') as HTMLElement);
    expect(past.getAllByRole('row')).toHaveLength(3);
    expect(past.getByText('Data removed')).toBeInTheDocument();
    expect(past.getByText("Data removed. Remove Connect's access in the provider's settings.")).toBeInTheDocument();
    // With nothing live, the page still invites the first connection.
    expect(screen.getByRole('heading', { name: 'Connect the first account' })).toBeInTheDocument();
  });
});

describe('what a person may do with a connection', () => {
  it('queues a sync with the token and says so', async () => {
    const server = fakeApi(
      serving([connection()], {}, { [`POST ${one}/sync`]: json(202, { run_id: 'r1', kind: 'incremental', status: 'queued', stream: 'account' }) }),
    );
    const user = userEvent.setup();
    openApp(connectionsPath);

    await user.click((await card()).getByRole('button', { name: 'Sync now' }));

    expect(await screen.findByText('A sync was requested. New data appears here when it finishes.')).toBeInTheDocument();
    expect(server.sent(`POST ${one}/sync`)[0]?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
  });

  it('does not offer a second sync while one is under way', async () => {
    fakeApi(serving([connection()], { sync: { state: 'running', kind: 'incremental', reason: null, next_attempt_at: null } }));
    openApp(connectionsPath);
    const account = await card();
    await account.findByText('Reading now');
    expect(account.getByRole('button', { name: 'Sync now' })).toBeDisabled();
  });

  it('turns a refusal into a sentence', async () => {
    fakeApi(serving([connection()], {}, { [`POST ${one}/sync`]: refused(409, 'sync_in_progress') }));
    const user = userEvent.setup();
    openApp(connectionsPath);
    const account = await card();
    await user.click(account.getByRole('button', { name: 'Sync now' }));
    expect(await account.findByRole('alert')).toHaveTextContent('Another sync of this account is still running.');
  });

  it('disconnects only after the person has ticked that it cannot be undone', async () => {
    let listed = [connection()];
    const server = fakeApi(
      serving([], {}, {
        [`GET ${base}`]: () => json(200, listed),
        [`POST ${one}/disconnect`]: () => {
          listed = [];
          return json(202, connection({ status: 'disconnecting' }));
        },
      }),
    );
    const user = userEvent.setup();
    openApp(connectionsPath);

    await user.click((await card()).getByRole('button', { name: 'Disconnect' }));
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Disconnect Sample provider (@olive.thyme)?' }));
    await user.click(dialog.getByRole('button', { name: 'Disconnect' }));
    expect(await dialog.findByText('Tick the box to confirm.')).toBeInTheDocument();
    expect(dialog.getByRole('checkbox')).toHaveFocus();
    expect(server.sent(`POST ${one}/disconnect`)).toHaveLength(0);

    await user.click(dialog.getByRole('checkbox', { name: 'I understand that this cannot be undone' }));
    await user.click(dialog.getByRole('button', { name: 'Disconnect' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(server.sent(`POST ${one}/disconnect`)).toHaveLength(1);
    expect(await screen.findByRole('heading', { name: 'Connect the first account' })).toBeInTheDocument();
  });

  it('keeps the account when the person chooses to', async () => {
    const server = fakeApi(serving([connection()], {}, { [`POST ${one}/disconnect`]: empty() }));
    const user = userEvent.setup();
    openApp(connectionsPath);
    await user.click((await card()).getByRole('button', { name: 'Disconnect' }));
    await user.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Keep connected' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(server.sent(`POST ${one}/disconnect`)).toHaveLength(0);
  });

  it.each(['analyst', 'client_viewer'] as const)('lets a %s read the accounts and change nothing', async (role) => {
    const readOnly = connection({ actions: { reconnect: false, disconnect: false } });
    fakeApi(asRole(role, serving([readOnly])));
    openApp(connectionsPath);
    const account = await card();
    expect(await account.findByText('Fresh')).toBeInTheDocument();
    expect(account.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Connect account' })).not.toBeInTheDocument();
  });

  it('tells a person who cannot connect who can, when nothing is connected', async () => {
    fakeApi(asRole('analyst', serving([])));
    openApp(connectionsPath);
    expect(await screen.findByText('No account is connected for Olive & Thyme yet. An owner or admin of the agency can connect one.')).toBeInTheDocument();
  });
});

describe('connecting an account', () => {
  const connectRoute = `POST ${base}`;
  const openDialog = async (user: UserEvent) => {
    await user.click(await screen.findByRole('button', { name: 'Connect account' }));
    return within(await screen.findByRole('dialog', { name: 'Connect an account' }));
  };
  const answering = (address = 'https://provider.example/authorize?state=abc') => serving([], {}, { [connectRoute]: json(200, { authorization_url: address }) });

  it('offers the product\'s providers, and no stand-in in an ordinary build', async () => {
    fakeApi(answering());
    const user = userEvent.setup();
    openApp(connectionsPath);
    const dialog = await openDialog(user);
    expect(dialog.getAllByRole('radio').map((radio) => (radio as HTMLInputElement).value)).toEqual(['instagram', 'youtube', 'meta_ads']);
    expect(dialog.getByRole('radio', { name: /Instagram/ })).toBeChecked();
  });

  it('sends the provider alone when it needs nothing more, and leaves for the address the API gave', async () => {
    const server = fakeApi(answering());
    const user = userEvent.setup();
    openApp(connectionsPath);
    const dialog = await openDialog(user);
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));

    await waitFor(() => expect(goTo).toHaveBeenCalledWith('https://provider.example/authorize?state=abc'));
    const [request] = server.sent(connectRoute);
    expect(request?.body).toEqual({ provider: 'instagram' });
    expect(request?.headers.get('X-CSRF-Token')).toBe(session.csrf_token);
    expect(request?.credentials).toBe('include');
    // Only the two identifiers are remembered for the way back, for this tab.
    expect(window.sessionStorage.getItem('connect.pendingConnection')).toBe(JSON.stringify({ agencyId: agency.id, clientId: client.id }));
    expect(everythingStored()).not.toContain('state=abc');
  });

  it('asks for the number of the ad account, and sends it', async () => {
    const server = fakeApi(answering());
    const user = userEvent.setup();
    openApp(connectionsPath);
    const dialog = await openDialog(user);
    await user.click(dialog.getByRole('radio', { name: /Meta ads/ }));
    const field = dialog.getByLabelText('Ad account number');

    await enter(user, field, 'my account');
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    expect(await dialog.findByText('Enter the account number: digits only, with or without “act_”.')).toBeInTheDocument();
    expect(field).toHaveFocus();
    expect(server.sent(connectRoute)).toHaveLength(0);

    await user.clear(field);
    await enter(user, field, ' act_1234567890 ');
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    await waitFor(() => expect(server.sent(connectRoute)).toHaveLength(1));
    expect(server.sent(connectRoute)[0]?.body).toEqual({ provider: 'meta_ads', account: 'act_1234567890' });
  });

  it('asks for the account holder\'s approval where the provider needs it, and sends its version', async () => {
    const server = fakeApi(answering());
    const user = userEvent.setup();
    openApp(connectionsPath);
    const dialog = await openDialog(user);
    await user.click(dialog.getByRole('radio', { name: /YouTube/ }));
    const approval = dialog.getByRole('checkbox', { name: /approve the agency and the people it gives access to Olive & Thyme/ });
    expect(approval).not.toBeChecked();

    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    expect(await dialog.findByText('Tick the box to give this approval before you continue.')).toBeInTheDocument();
    expect(approval).toHaveFocus();
    expect(server.sent(connectRoute)).toHaveLength(0);

    await user.click(approval);
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    await waitFor(() => expect(server.sent(connectRoute)).toHaveLength(1));
    expect(server.sent(connectRoute)[0]?.body).toEqual({ provider: 'youtube', agent_approval: { approved: true, disclosure: 'dev-agent-approval-1' } });
  });

  it.each(['http://provider.example/authorize', 'javascript:alert(1)', '/somewhere'])('goes nowhere when the address is %s', async (address) => {
    fakeApi(answering(address));
    const user = userEvent.setup();
    openApp(connectionsPath);
    const dialog = await openDialog(user);
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    expect(await dialog.findByRole('alert')).toHaveTextContent('The connection could not be completed. Try again.');
    expect(goTo).not.toHaveBeenCalled();
    expect(pendingConnection.get()).toBeNull();
  });

  it.each([
    [404, 'provider_unavailable', 'This kind of account cannot be connected on this server yet.'],
    [503, 'connector_not_configured', 'This kind of account cannot be connected on this server yet.'],
    [403, 'access_denied', 'Only an owner or admin of the agency can do this.'],
    [422, 'invalid_account', 'The account number was not accepted. Check it and try again.'],
  ])('explains a refusal (%i %s) and stays', async (status, code, sentence) => {
    fakeApi(serving([], {}, { [connectRoute]: refused(status, code) }));
    const user = userEvent.setup();
    openApp(connectionsPath);
    const dialog = await openDialog(user);
    await user.click(dialog.getByRole('button', { name: 'Continue to the provider' }));
    expect(await dialog.findByRole('alert', undefined, { timeout: 15_000 })).toHaveTextContent(sentence);
    expect(goTo).not.toHaveBeenCalled();
  });
});

describe('coming back from a provider', () => {
  const started = () => pendingConnection.set({ agencyId: agency.id, clientId: client.id });

  it('returns to the client that was being connected and says the account is connected, once', async () => {
    started();
    fakeApi(serving([connection()]));
    openApp(`/connections/complete?result=connected&connection_id=${connection().id}`);

    expect(await screen.findByText('The account is connected.')).toBeInTheDocument();
    expect(screen.getByText('The first sync is running. Data appears here when it finishes.')).toBeInTheDocument();
    await waitFor(() => expect(window.location.pathname).toBe(connectionsPath));
    // The outcome leaves the address, so a reload or a shared link does not repeat it.
    await waitFor(() => expect(window.location.search).toBe(''));
    expect(pendingConnection.get()).toBeNull();
  });

  it('says a reconnected account is connected again', async () => {
    started();
    fakeApi(serving([connection()]));
    openApp(`/connections/complete?result=reconnected&connection_id=${connection().id}`);
    expect(await screen.findByText('The account is connected again.')).toBeInTheDocument();
  });

  it.each([
    ['connection_cancelled', 'The connection was cancelled at the provider.'],
    ['account_mismatch', 'You signed in with a different account. Reconnect with the account that was connected before.'],
    ['account_already_connected', 'This account is already connected to this client.'],
    ['connection_denied', 'This connection was started by another session. Start it again from here.'],
  ])('explains %s in the client\'s connections', async (code, sentence) => {
    started();
    fakeApi(serving([]));
    openApp(`/connections/complete?error=${code}`);
    expect(await screen.findByRole('alert')).toHaveTextContent(sentence);
    expect(window.location.pathname).toBe(connectionsPath);
  });

  it('reads nothing but the fixed outcomes from the address', async () => {
    started();
    fakeApi(serving([]));
    openApp('/connections/complete?error=%3Cimg%20src%3Dx%3E&result=owned&connection_id=not-an-id');
    await screen.findByRole('heading', { name: 'Connections', level: 1 });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/connected/)).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain('<img src=x>');
  });

  it('ignores an outcome it does not know when no connection was started in this tab', async () => {
    fakeApi(serving([]));
    openApp('/connections/complete?error=made_up&result=owned');
    expect(await screen.findByText('There is no connection to finish here.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('reads only the fixed outcomes from the address of the connections page itself', async () => {
    fakeApi(serving([]));
    openApp(`${connectionsPath}?failed=made_up&outcome=owned&connection=not-an-id`);
    await screen.findByRole('heading', { name: 'Connect the first account' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(/is connected/)).not.toBeInTheDocument();
  });

  it('says what happened and offers the clients when no connection was started in this tab', async () => {
    fakeApi(serving([]));
    openApp('/connections/complete?error=connection_cancelled');
    expect(await screen.findByRole('heading', { name: 'Back from the provider', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('The connection was cancelled at the provider.');
    expect(screen.getByRole('link', { name: 'Go to your clients' })).toBeInTheDocument();
  });

  it('ignores a record that does not hold two identifiers', async () => {
    window.sessionStorage.setItem('connect.pendingConnection', JSON.stringify({ agencyId: '../../account', clientId: client.id }));
    fakeApi(serving([]));
    openApp('/connections/complete?result=connected');
    expect(await screen.findByRole('heading', { name: 'Back from the provider', level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/connections/complete');
  });
});

describe('the connections of a client in the cache', () => {
  it('are keyed under the agency and the client', async () => {
    fakeApi(serving([connection()]));
    const { queryClient } = openApp(connectionsPath);
    await (await card()).findByText('Fresh');
    const keys = queryClient
      .getQueryCache()
      .findAll({ queryKey: clientKey(agency.id, client.id) })
      .map((query) => query.queryKey.slice(4).join('/'));
    expect(keys.sort()).toEqual(['connections', `connections/${connection().id}/coverage`, 'profile']);
  });
});
