import { screen, waitFor, within } from '@testing-library/react';
import userEvent, { type UserEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clientKey } from '@/api/clients';

import { enter, everythingStored } from '../support/actions';
import { agency, asRole, client, fakeApi, json, otherClient, refused, withClients } from '../support/api';
import { forgetEverything, openApp } from '../support/app';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-11-26T12:00:00Z') });
});
afterEach(() => {
  vi.useRealTimers();
  forgetEverything();
});

const base = `/agencies/${agency.id}/clients/${client.id}`;
const linksPath = `${base}/links`;
const stamp = { created_at: '2026-11-20T09:00:00Z', updated_at: '2026-11-20T09:00:00Z' };

const site = { id: 'e1111111-1111-4111-8111-111111111111', client_id: client.id, origin: 'https://shop.olive.example', query_names: ['lang'], status: 'active', ...stamp };
const campaign = { id: 'f1111111-1111-4111-8111-111111111111', client_id: client.id, public_code: 'ramadan-2026', label: 'Ramadan 2026', status: 'active', ...stamp };
const reference = {
  id: 'f2222222-2222-4222-8222-222222222222',
  client_id: client.id,
  external_code: '17890001',
  platform_label: 'Iftar menu carousel',
  status: 'active',
  ...stamp,
};
const template = {
  id: 'f3333333-3333-4333-8333-333333333333',
  client_id: client.id,
  name: 'Instagram, unpaid',
  parameters: { utm_medium: 'social', utm_source: 'instagram' },
  revision: 2,
  status: 'active',
  ...stamp,
};
const linkId = 'a1111111-1111-4111-8111-111111111111';
const link = (given: Record<string, unknown> = {}) => ({
  id: linkId,
  client_id: client.id,
  domain_id: null,
  slug: 'ramadan-reel',
  destination: 'https://shop.olive.example/ramadan-box',
  utm: { utm_id: 'ramadan-2026', utm_medium: 'social', utm_source: 'instagram' },
  target_url: `https://shop.olive.example/ramadan-box?utm_id=ramadan-2026&utm_medium=social&utm_source=instagram&ts_link=${linkId}`,
  campaign_id: campaign.id,
  content_reference_id: reference.id,
  template_id: template.id,
  template_revision: 2,
  status: 'active',
  expires_at: null,
  created_at: '2026-11-25T10:00:00Z',
  ...given,
});
const domain = (given: Record<string, unknown> = {}) => ({
  id: 'd9999999-9999-4999-8999-999999999999',
  client_id: client.id,
  hostname: 'go.olive.example',
  status: 'pending',
  challenge_generation: 0,
  challenge_expires_at: null,
  verified_at: null,
  verification_expires_at: null,
  certificate_expires_at: null,
  last_checked_at: null,
  failure_code: null,
  version: 1,
  created_at: '2026-11-21T09:00:00Z',
  ...given,
});

type Routes = Parameters<typeof fakeApi>[0];

const linking = (more: Routes = {}, links: unknown[] = [link()]): Routes => ({
  ...withClients([client, otherClient]),
  [`GET ${base}/managed-links`]: json(200, links),
  [`GET ${base}/link-campaigns`]: json(200, [campaign]),
  [`GET ${base}/link-content-references`]: json(200, [reference]),
  [`GET ${base}/link-utm-templates`]: json(200, [template]),
  [`GET ${base}/link-destination-origins`]: json(200, [site]),
  [`GET ${base}/link-domains`]: json(200, []),
  ...more,
});

const short = '127.0.0.1:8000/r/ramadan-reel';
const rowOf = async (text: string) => within((await screen.findByText(text, { selector: '.c-table__primary' })).closest('tr') as HTMLElement);
const menuOf = async (user: UserEvent, text: string, label = `Actions for ${text}`) => {
  await user.click((await rowOf(text)).getByRole('button', { name: label }));
  return within(await screen.findByRole('menu'));
};
const choose = async (user: UserEvent, field: RegExp, option: string, place: Pick<typeof screen, 'getByRole'> = screen) => {
  await user.click(place.getByRole('button', { name: field }));
  await user.click(await screen.findByRole('option', { name: new RegExp(option) }));
};

describe('the links of a client', () => {
  it('lists each link by its short address, with its campaign, content and end', async () => {
    fakeApi(linking());
    openApp(linksPath);

    const row = await rowOf(short);
    expect(row.getByText('shop.olive.example/ramadan-box')).toBeInTheDocument();
    expect(row.getByText('Ramadan 2026')).toBeInTheDocument();
    expect(row.getByText('Iftar menu carousel')).toBeInTheDocument();
    expect(row.getByText('Nov 25, 2026')).toBeInTheDocument();
    expect(row.getByText('Never')).toBeInTheDocument();
    expect(screen.getByText('1 of 1 active link')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Links', level: 1 })).toBeInTheDocument();
  });

  it('keeps paused and expired links apart from the active ones', async () => {
    fakeApi(
      linking({}, [
        link(),
        link({ id: 'a2222222-2222-4222-8222-222222222222', slug: 'paused-one', status: 'disabled' }),
        link({ id: 'a3333333-3333-4333-8333-333333333333', slug: 'ended-one', expires_at: '2026-11-26T11:00:00Z' }),
      ]),
    );
    const user = userEvent.setup();
    openApp(linksPath);

    await rowOf(short);
    expect(screen.queryByText('127.0.0.1:8000/r/paused-one')).not.toBeInTheDocument();
    const states = within(screen.getByRole('group', { name: 'State' }));
    await user.click(states.getByRole('button', { name: 'Paused' }));
    expect((await rowOf('127.0.0.1:8000/r/paused-one')).getByText('Paused')).toBeInTheDocument();
    expect(screen.queryByText(short)).not.toBeInTheDocument();
    await user.click(states.getByRole('button', { name: 'Expired' }));
    expect((await rowOf('127.0.0.1:8000/r/ended-one')).getByText('Expired')).toBeInTheDocument();
  });

  it('finds links by campaign and by what is typed', async () => {
    fakeApi(linking({}, [link(), link({ id: 'a2222222-2222-4222-8222-222222222222', slug: 'catering', campaign_id: null, content_reference_id: null })]));
    const user = userEvent.setup();
    openApp(linksPath);

    await rowOf(short);
    expect((await rowOf('127.0.0.1:8000/r/catering')).getByText('No campaign')).toBeInTheDocument();
    await choose(user, /Campaign/, 'Ramadan 2026');
    await waitFor(() => expect(screen.queryByText('127.0.0.1:8000/r/catering')).not.toBeInTheDocument());
    await choose(user, /Campaign/, 'All campaigns');
    await enter(user, screen.getByRole('searchbox', { name: 'Search by address, campaign or content' }), 'carousel');
    await waitFor(() => expect(screen.queryByText('127.0.0.1:8000/r/catering')).not.toBeInTheDocument());
    expect(screen.getByText(short)).toBeInTheDocument();
  });

  it('copies the short address and the address visitors arrive at', async () => {
    fakeApi(linking());
    const user = userEvent.setup();
    openApp(linksPath);

    await user.click((await menuOf(user, short)).getByRole('menuitem', { name: 'Copy short address' }));
    expect(await navigator.clipboard.readText()).toBe(`http://${short}`);
    expect(await screen.findByText('Short address copied.')).toBeInTheDocument();
    await user.click((await menuOf(user, short)).getByRole('menuitem', { name: 'Copy the address visitors arrive at' }));
    expect(await navigator.clipboard.readText()).toBe(link().target_url);
  });

  it('pauses a link after asking, and resumes it in one step', async () => {
    let current = link();
    const server = fakeApi(
      linking({
        [`GET ${base}/managed-links`]: () => json(200, [current]),
        [`PATCH ${base}/managed-links/${linkId}`]: (sent) => {
          current = { ...current, ...(sent.body as object) };
          return json(200, current);
        },
      }),
    );
    const user = userEvent.setup();
    openApp(linksPath);

    await user.click((await menuOf(user, short)).getByRole('menuitem', { name: 'Pause link' }));
    const dialog = within(await screen.findByRole('alertdialog', { name: 'Pause this link?' }));
    expect(dialog.getByText(/Visitors who open 127\.0\.0\.1:8000\/r\/ramadan-reel are told/)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Pause link' }));
    await waitFor(() => expect(server.sent(`PATCH ${base}/managed-links/${linkId}`)[0]?.body).toEqual({ status: 'disabled' }));

    await user.click(within(screen.getByRole('group', { name: 'State' })).getByRole('button', { name: 'Paused' }));
    await user.click((await menuOf(user, short)).getByRole('menuitem', { name: 'Resume' }));
    await waitFor(() => expect(server.sent(`PATCH ${base}/managed-links/${linkId}`)[1]?.body).toEqual({ status: 'active' }));
  });

  it('shows a reader the links and the ways to copy them, and nothing that changes them', async () => {
    const server = fakeApi(asRole('analyst', linking()));
    const user = userEvent.setup();
    openApp(linksPath);

    const menu = await menuOf(user, short);
    expect(menu.getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Copy short address', 'Copy the address visitors arrive at']);
    expect(screen.queryByRole('button', { name: 'Create link' })).not.toBeInTheDocument();
    // The sites are read only for the panel that creates a link.
    expect(server.sent(`GET ${base}/link-destination-origins`)).toHaveLength(0);
  });

  it('remembers the tab in the address', async () => {
    fakeApi(linking());
    const user = userEvent.setup();
    const { router } = openApp(`${linksPath}?tab=campaigns`);

    expect(await screen.findByRole('tab', { name: 'Campaigns', selected: true })).toBeInTheDocument();
    expect(await rowOf('Ramadan 2026')).toBeTruthy();
    await user.click(screen.getByRole('tab', { name: 'Destination sites' }));
    await waitFor(() => expect(router.state.location.search).toEqual({ tab: 'sites' }));
    await user.click(screen.getByRole('tab', { name: 'Links' }));
    await waitFor(() => expect(router.state.location.search).toEqual({}));
  });

  it('forgets the links of a client once the person leaves it', async () => {
    fakeApi(linking());
    const { queryClient, router } = openApp(linksPath);
    await rowOf(short);
    expect(queryClient.getQueryData(clientKey(agency.id, client.id, 'links', 'links'))).toBeDefined();
    await router.navigate({ to: '/agencies/$agencyId/clients', params: { agencyId: agency.id } });
    await waitFor(() => expect(queryClient.getQueryData(clientKey(agency.id, client.id, 'links', 'links'))).toBeUndefined());
  });
});

describe('a new link', () => {
  const open = async (user: UserEvent) => {
    await user.click(await screen.findByRole('button', { name: 'Create link' }));
    return within(await screen.findByRole('form', { name: 'New link' }));
  };

  it('is sent with what the person chose and shows the address the API issued', async () => {
    const issued = link({ id: 'a4444444-4444-4444-8444-444444444444', slug: 'iftar', campaign_id: campaign.id, content_reference_id: null, template_id: null });
    const server = fakeApi(linking({ [`POST ${base}/managed-links`]: json(201, issued) }));
    const user = userEvent.setup();
    openApp(linksPath);

    const panel = await open(user);
    await enter(user, panel.getByLabelText('Destination'), 'https://shop.olive.example/iftar?lang=ar');
    await enter(user, panel.getByLabelText('Short path'), 'Iftar');
    expect(panel.getByText('The short address: 127.0.0.1:8000/r/iftar')).toBeInTheDocument();
    await choose(user, /Campaign/, 'Ramadan 2026', panel);
    await user.click(panel.getByRole('button', { name: 'Create link' }));

    await waitFor(() => expect(server.sent(`POST ${base}/managed-links`)).toHaveLength(1));
    expect(server.sent(`POST ${base}/managed-links`)[0]?.body).toEqual({
      slug: 'iftar',
      destination: 'https://shop.olive.example/iftar?lang=ar',
      domain_id: null,
      campaign_id: campaign.id,
      content_reference_id: null,
      template_id: null,
      expires_at: null,
    });
    const done = within(await screen.findByRole('region', { name: 'Link created' }));
    expect(done.getByRole('textbox', { name: 'Short address' })).toHaveValue('http://127.0.0.1:8000/r/iftar');
    expect(done.getByRole('textbox', { name: 'Address visitors arrive at' })).toHaveValue(issued.target_url);
    expect(done.getByRole('button', { name: 'Copy Short address' })).toBeInTheDocument();
  });

  it('keeps showing what it issued when the first link of the client joins the list', async () => {
    const issued = link({ id: 'a5555555-5555-4555-8555-555555555555', slug: 'first-link' });
    let links: unknown[] = [];
    fakeApi(
      linking({
        [`GET ${base}/managed-links`]: () => json(200, links),
        [`POST ${base}/managed-links`]: () => {
          links = [issued];
          return json(201, issued);
        },
      }),
    );
    const user = userEvent.setup();
    openApp(linksPath);

    await user.click(await screen.findByRole('button', { name: 'Create link' }));
    const panel = within(await screen.findByRole('form', { name: 'New link' }));
    await enter(user, panel.getByLabelText('Destination'), 'https://shop.olive.example/ramadan-box');
    await enter(user, panel.getByLabelText('Short path'), 'first-link');
    await user.click(panel.getByRole('button', { name: 'Create link' }));
    const done = within(await screen.findByRole('region', { name: 'Link created' }));
    expect(await screen.findByText('127.0.0.1:8000/r/first-link', { selector: '.c-table__primary' })).toBeInTheDocument();
    expect(done.getByRole('textbox', { name: 'Address visitors arrive at' })).toHaveValue(issued.target_url);
  });

  it.each([
    ['https://other.example/page', 'ramadan-two', "The address must be on one of this client's destination sites."],
    ['http://shop.olive.example/page', 'ramadan-two', "The address must be on one of this client's destination sites."],
    ['https://shop.olive.example/page#top', 'ramadan-two', 'Enter a full web address without spaces'],
    ['https://shop.olive.example/a/../b', 'ramadan-two', 'Enter a full web address without spaces'],
    ['https://shop.olive.example/page?ref=story', 'ramadan-two', 'Only UTM values and the names the site keeps may follow ?'],
    ['https://shop.olive.example/page?utm_source=a b', 'ramadan-two', 'Enter a full web address without spaces'],
    ['https://shop.olive.example/page?ts_link=x', 'ramadan-two', 'After ?, write each value as name=value'],
    ['https://shop.olive.example/page', 'api', 'This word is kept for Connect itself.'],
    ['https://shop.olive.example/page', '-dash', 'Use 3 to 64 lowercase letters, digits and hyphens'],
  ])('is not sent when %s with the path %s breaks a rule of the API', async (destination, slug, sentence) => {
    const server = fakeApi(linking());
    const user = userEvent.setup();
    openApp(linksPath);

    const panel = await open(user);
    await enter(user, panel.getByLabelText('Destination'), destination);
    await enter(user, panel.getByLabelText('Short path'), slug);
    await user.click(panel.getByRole('button', { name: 'Create link' }));
    expect(await panel.findByText(new RegExp(sentence.replace(/[.?*+^$()[\]\\]/g, '\\$&')))).toBeInTheDocument();
    expect(server.sent(`POST ${base}/managed-links`)).toHaveLength(0);
  });

  it('says when its short address is taken', async () => {
    fakeApi(linking({ [`POST ${base}/managed-links`]: refused(409, 'state_conflict') }));
    const user = userEvent.setup();
    openApp(linksPath);

    const panel = await open(user);
    await enter(user, panel.getByLabelText('Destination'), 'https://shop.olive.example/page');
    await enter(user, panel.getByLabelText('Short path'), 'ramadan-reel');
    await user.click(panel.getByRole('button', { name: 'Create link' }));
    expect(await panel.findByText('This short address is taken. Choose another path.')).toBeInTheDocument();
  });

  it('carries its own UTM values only when they follow the rule', async () => {
    const server = fakeApi(linking({ [`POST ${base}/managed-links`]: json(201, link()) }));
    const user = userEvent.setup();
    openApp(linksPath);

    const panel = await open(user);
    await enter(user, panel.getByLabelText('Destination'), 'https://shop.olive.example/page');
    await enter(user, panel.getByLabelText('Short path'), 'story-one');
    await user.click(panel.getByRole('button', { name: 'UTM values of this link' }));
    await enter(user, panel.getByLabelText('utm_content'), 'story 1');
    await user.click(panel.getByRole('button', { name: 'Create link' }));
    expect(await panel.findByText('Use up to 64 letters, digits, dots, hyphens and underscores.')).toBeInTheDocument();
    expect(server.sent(`POST ${base}/managed-links`)).toHaveLength(0);

    await user.clear(panel.getByLabelText('utm_content'));
    await enter(user, panel.getByLabelText('utm_content'), 'story-1');
    await user.click(panel.getByRole('button', { name: 'Create link' }));
    await waitFor(() => expect(server.sent(`POST ${base}/managed-links`)).toHaveLength(1));
    expect(server.sent(`POST ${base}/managed-links`)[0]?.body).toMatchObject({ utm: { utm_content: 'story-1' } });
  });

  it('asks for a destination site first when the client has none, and leads there', async () => {
    fakeApi(linking({ [`GET ${base}/link-destination-origins`]: json(200, []) }, []));
    const user = userEvent.setup();
    const { router } = openApp(linksPath);

    await user.click(await screen.findByRole('button', { name: 'Create link' }));
    expect(await screen.findByText('No destination site yet')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Go to destination sites' }));
    await waitFor(() => expect(router.state.location.search).toEqual({ tab: 'sites' }));
  });
});

describe('the settings of links', () => {
  it('creates a campaign with its code, and says when the code exists', async () => {
    const server = fakeApi(linking({ [`POST ${base}/link-campaigns`]: refused(409, 'state_conflict') }));
    const user = userEvent.setup();
    openApp(`${linksPath}?tab=campaigns`);

    await user.click(await screen.findByRole('button', { name: 'New campaign' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'New campaign' }));
    await enter(user, dialog.getByLabelText('Code'), 'ramadan 2026');
    await enter(user, dialog.getByLabelText('Name'), 'Ramadan again');
    await user.click(dialog.getByRole('button', { name: 'Create campaign' }));
    expect(await dialog.findByText('Use up to 64 letters, digits, dots, hyphens and underscores.')).toBeInTheDocument();
    expect(server.sent(`POST ${base}/link-campaigns`)).toHaveLength(0);

    await user.clear(dialog.getByLabelText('Code'));
    await enter(user, dialog.getByLabelText('Code'), 'ramadan-2026');
    await user.click(dialog.getByRole('button', { name: 'Create campaign' }));
    expect(await dialog.findByText('A campaign with this code already exists.')).toBeInTheDocument();
    expect(server.sent(`POST ${base}/link-campaigns`)[0]?.body).toEqual({ public_code: 'ramadan-2026', label: 'Ramadan again' });
  });

  it('adds a destination site by its exact address, with the names it keeps', async () => {
    const server = fakeApi(linking({ [`POST ${base}/link-destination-origins`]: json(201, site) }));
    const user = userEvent.setup();
    openApp(`${linksPath}?tab=sites`);

    await user.click(await screen.findByRole('button', { name: 'New site' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'New site' }));
    await enter(user, dialog.getByLabelText('Site'), 'http://cedar.example');
    await user.click(dialog.getByRole('button', { name: 'Add site' }));
    expect(await dialog.findByText('The site must use https.')).toBeInTheDocument();

    await user.clear(dialog.getByLabelText('Site'));
    await enter(user, dialog.getByLabelText('Site'), 'https://Shop.Cedar.Example/');
    await enter(user, dialog.getByLabelText('Query names to keep'), 'lang, session_id');
    await user.click(dialog.getByRole('button', { name: 'Add site' }));
    expect(await dialog.findByText(/A name that could carry a password/)).toBeInTheDocument();

    await user.clear(dialog.getByLabelText('Query names to keep'));
    await enter(user, dialog.getByLabelText('Query names to keep'), 'lang, ref');
    await user.click(dialog.getByRole('button', { name: 'Add site' }));
    await waitFor(() => expect(server.sent(`POST ${base}/link-destination-origins`)).toHaveLength(1));
    expect(server.sent(`POST ${base}/link-destination-origins`)[0]?.body).toEqual({ origin: 'https://shop.cedar.example', query_names: ['lang', 'ref'] });
  });

  it('turns a site off only after saying that its links stop', async () => {
    const server = fakeApi(linking({ [`PATCH ${base}/link-destination-origins/${site.id}`]: json(200, { ...site, status: 'disabled' }) }));
    const user = userEvent.setup();
    openApp(`${linksPath}?tab=sites`);

    await user.click((await menuOf(user, 'shop.olive.example')).getByRole('menuitem', { name: 'Turn off' }));
    const dialog = within(await screen.findByRole('alertdialog'));
    expect(dialog.getByText(/The links that lead to this site stop working/)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Turn off' }));
    await waitFor(() => expect(server.sent(`PATCH ${base}/link-destination-origins/${site.id}`)[0]?.body).toEqual({ status: 'disabled' }));
  });

  it('changes the values of a template, which raises its version', async () => {
    const server = fakeApi(linking({ [`PATCH ${base}/link-utm-templates/${template.id}`]: json(200, { ...template, revision: 3 }) }));
    const user = userEvent.setup();
    openApp(`${linksPath}?tab=templates`);

    const row = await rowOf('Instagram, unpaid');
    expect(row.getByText('Version 2')).toBeInTheDocument();
    expect(row.getByText('utm_source=instagram')).toBeInTheDocument();
    await user.click((await menuOf(user, 'Instagram, unpaid')).getByRole('menuitem', { name: 'Change values' }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.clear(dialog.getByLabelText('utm_medium'));
    await enter(user, dialog.getByLabelText('utm_campaign'), 'iftar');
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(server.sent(`PATCH ${base}/link-utm-templates/${template.id}`)).toHaveLength(1));
    expect(server.sent(`PATCH ${base}/link-utm-templates/${template.id}`)[0]?.body).toEqual({ parameters: { utm_source: 'instagram', utm_campaign: 'iftar' } });
  });
});

describe('a custom domain', () => {
  it('shows its DNS record once, and keeps the value nowhere', async () => {
    const recordValue = 'tracking-verification=synthetic-record-value-shown-once';
    let current = domain();
    const challenged = () => {
      current = domain({ challenge_generation: 1, challenge_expires_at: '2026-11-27T12:00:00Z' });
      return json(201, { domain: current, record_type: 'TXT', record_name: '_tracking-verification.go.olive.example', record_value: recordValue, expires_at: current.challenge_expires_at, cname_target: null });
    };
    fakeApi(
      linking({
        [`GET ${base}/link-domains`]: () => json(200, [current]),
        [`POST ${base}/link-domains/${current.id}/challenge`]: challenged,
        [`POST ${base}/link-domains/${current.id}/verify`]: refused(503, 'verification_unavailable'),
      }),
    );
    const user = userEvent.setup();
    const { queryClient } = openApp(`${linksPath}?tab=domains`);

    expect((await rowOf('go.olive.example')).getByText('Not verified')).toBeInTheDocument();
    await user.click((await menuOf(user, 'go.olive.example')).getByRole('menuitem', { name: 'Get the DNS record' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'DNS record for go.olive.example' }));
    expect(dialog.getByRole('textbox', { name: 'Record value' })).toHaveValue(recordValue);
    expect(dialog.getByRole('textbox', { name: 'TXT record name' })).toHaveValue('_tracking-verification.go.olive.example');
    await user.click(dialog.getByRole('button', { name: 'I have copied it' }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain(recordValue);
    const cached = JSON.stringify(queryClient.getQueryCache().getAll().map((query) => query.state.data)) + JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => mutation.state.data));
    expect(cached).not.toContain(recordValue);
    expect(everythingStored()).not.toContain(recordValue);

    expect((await rowOf('go.olive.example')).getByText('Waiting for DNS')).toBeInTheDocument();
    await user.click((await menuOf(user, 'go.olive.example')).getByRole('menuitem', { name: 'Check now' }));
    expect(await screen.findByText('Domain checks are not available on this server, so the domain cannot be verified here.')).toBeInTheDocument();
  });

  it.each([
    [{ status: 'verified', verification_expires_at: '2026-11-27T09:00:00Z', challenge_expires_at: '2026-11-26T09:00:00Z' }, 'Verified'],
    [{ status: 'verified', verification_expires_at: '2026-11-26T09:00:00Z', challenge_expires_at: '2026-11-25T09:00:00Z' }, 'Check again'],
    [{ status: 'pending', challenge_expires_at: '2026-11-26T09:00:00Z' }, 'Record expired'],
    [{ status: 'pending', challenge_expires_at: '2026-11-27T09:00:00Z', failure_code: 'ownership_missing', last_checked_at: '2026-11-26T10:00:00Z' }, 'Check failed'],
    [{ status: 'disabled' }, 'Turned off'],
  ])('reads %o as %s', async (given, word) => {
    fakeApi(linking({ [`GET ${base}/link-domains`]: json(200, [domain(given)]) }));
    openApp(`${linksPath}?tab=domains`);
    const row = await rowOf('go.olive.example');
    expect(row.getByText(word)).toBeInTheDocument();
    if (word === 'Check failed') expect(row.getByText(/The TXT record was not found/)).toBeInTheDocument();
  });

  it('says why a check failed', async () => {
    const waiting = domain({ challenge_generation: 1, challenge_expires_at: '2026-11-27T09:00:00Z' });
    fakeApi(
      linking({
        [`GET ${base}/link-domains`]: json(200, [waiting]),
        [`POST ${base}/link-domains/${waiting.id}/verify`]: json(200, { outcome: 'failed', domain: { ...waiting, failure_code: 'routing_mismatch' } }),
      }),
    );
    const user = userEvent.setup();
    openApp(`${linksPath}?tab=domains`);
    await user.click((await menuOf(user, 'go.olive.example')).getByRole('menuitem', { name: 'Check now' }));
    expect(await screen.findByText('go.olive.example could not be verified')).toBeInTheDocument();
    expect(screen.getByText('The domain does not point to Connect yet. Check its CNAME record.')).toBeInTheDocument();
  });
});
