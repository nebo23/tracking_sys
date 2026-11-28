import { readFileSync } from 'node:fs';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { agenciesKey } from '@/api/agencies';
import { ErrorNotice } from '@/components/Notice';
import { checkLogo, displayNameProblem, isAccentColor, MAX_LOGO_BYTES, MAX_LOGO_PIXELS, MIN_LOGO_BYTES } from '@/features/settings/logo';
import { limitState } from '@/features/settings/PlanTab';
import { maySeeSettings, settingsTabsFor } from '@/features/settings/tabs';

import { agency, asRole, empty, fakeApi, json, refused, signedIn } from '../support/api';
import { forgetEverything, openApp, renderWithMessages } from '../support/app';
import { inRepository } from '../support/files';

afterEach(forgetEverything);

const settings = `/agencies/${agency.id}/settings`;
const at = `GET /agencies/${agency.id}`;

/** A PNG of the given size: the signature and an IHDR chunk, padded to the smallest valid length. */
function png(width: number, height: number, bytes = 120): File {
  const data = new Uint8Array(bytes);
  data.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], 0);
  data.set([0, 0, 0, 13, 0x49, 0x48, 0x44, 0x52], 8);
  new DataView(data.buffer).setUint32(16, width);
  new DataView(data.buffer).setUint32(20, height);
  return new File([data], 'logo.png', { type: 'image/png' });
}

const plan = {
  agency_id: agency.id,
  plan: { key: 'development', name: 'Development', assigned_at: '2026-11-01T00:00:00Z' },
  limits: [
    { limit: 'clients', value: 5, used: 2, state: 'within' },
    { limit: 'seats', value: 10, used: 4, state: 'within' },
    { limit: 'connections', value: 10, used: 0, state: 'within' },
    { limit: 'managed_links', value: 500, used: 500, state: 'at_limit' },
  ],
  tracked_events: { period_start: '2026-11-01T00:00:00Z', period_end: '2026-12-01T00:00:00Z', count: 86240, count_capped: false, allowance: 100000, state: 'within' },
  as_of: '2026-11-28T09:40:00Z',
};
const branding = { agency_id: agency.id, configured: false, display_name: null, accent_color: null, logo: null, updated_at: null };
const saved = { ...branding, configured: true, display_name: 'Lumen', accent_color: '#0E7C7B', updated_at: '2026-11-28T10:00:00Z' };
type Routes = Parameters<typeof fakeApi>[0];
const world = (routes: Routes = {}): Routes => ({
  ...signedIn(),
  [`${at}/plan`]: json(200, plan),
  [`${at}/branding`]: json(200, branding),
  [`${at}/clients`]: json(200, []),
  ...routes,
});

describe('the rules of Agency settings', () => {
  it('check a logo as the API does, with the same bounds', async () => {
    const delivery = readFileSync(inRepository('backend', 'app', 'models', 'report_delivery.py'), 'utf8');
    const check = readFileSync(inRepository('backend', 'app', 'services', 'branding.py'), 'utf8');
    expect(delivery).toContain(`MAX_LOGO_BYTES = ${MAX_LOGO_BYTES / 1024} * 1024`);
    expect(check).toContain(`MIN_PNG_BYTES = ${MIN_LOGO_BYTES}`);
    expect(check).toContain(`MAX_DIMENSION = ${MAX_LOGO_PIXELS}`);

    expect(await checkLogo(png(512, 256))).toEqual({ problem: null, width: 512, height: 256 });
    expect((await checkLogo(png(1025, 10))).problem).toBe('too_big');
    expect((await checkLogo(png(10, 1025))).problem).toBe('too_big');
    expect((await checkLogo(png(10, 10, MAX_LOGO_BYTES + 1))).problem).toBe('too_large');
    expect((await checkLogo(png(10, 10, MIN_LOGO_BYTES - 1))).problem).toBe('too_small');
    expect((await checkLogo(new File(['<svg xmlns="http://www.w3.org/2000/svg"/>'], 'logo.svg', { type: 'image/svg+xml' }))).problem).toBe('not_png');
    // A file that only claims to be a PNG.
    expect((await checkLogo(new File([new Uint8Array(200)], 'fake.png', { type: 'image/png' }))).problem).toBe('not_png');
    // A PNG whose signature is wrong, and one whose first chunk is not IHDR.
    const forged = new Uint8Array(await png(10, 10).arrayBuffer());
    forged[1] = 0x51;
    expect((await checkLogo(new File([forged], 'forged.png', { type: 'image/png' }))).problem).toBe('not_png');
    const headless = new Uint8Array(await png(10, 10).arrayBuffer());
    headless.set([0x49, 0x44, 0x41, 0x54], 12);
    expect((await checkLogo(new File([headless], 'headless.png', { type: 'image/png' }))).problem).toBe('not_png');
  });

  it('check the display name and the color as the API does', () => {
    const check = readFileSync(inRepository('backend', 'app', 'services', 'branding.py'), 'utf8');
    expect(check).toContain('if not 1 <= len(value) <= 100 or any(ord(char) < 32 or ord(char) == 127 for char in value):');
    expect(check).toContain('COLOR = re.compile(r"#[0-9A-Fa-f]{6}")');

    expect(displayNameProblem('  Lumen  ')).toBeNull();
    expect(displayNameProblem('   ')).toBe('required');
    expect(displayNameProblem('a'.repeat(100))).toBeNull();
    expect(displayNameProblem('a'.repeat(101))).toBe('too_long');
    // Characters are counted as the API counts them, not as UTF-16 units.
    expect(displayNameProblem('\u{1F31F}'.repeat(100))).toBeNull();
    expect(displayNameProblem('Lumen\u0007Studio')).toBe('invalid');
    expect(displayNameProblem('Lumen\u007FStudio')).toBe('invalid');

    expect(isAccentColor('#0E7C7B')).toBe(true);
    expect(isAccentColor('#0e7c7b')).toBe(true);
    for (const value of ['0E7C7B', '#0E7C7', '#0E7C7BB', '#GGGGGG', ' #0E7C7B']) expect(isAccentColor(value), value).toBe(false);
  });

  it('show settings to every member but a client viewer, and closing to Owners only', () => {
    expect(maySeeSettings('client_viewer')).toBe(false);
    expect(settingsTabsFor('owner')).toEqual(['plan', 'branding', 'closure']);
    for (const role of ['admin', 'analyst'] as const) {
      expect(maySeeSettings(role)).toBe(true);
      expect(settingsTabsFor(role)).toEqual(['plan', 'branding']);
    }
  });

  it('know every state of a limit and of the tracked events that the API sends', () => {
    const schemas = readFileSync(inRepository('backend', 'app', 'api', 'schemas.py'), 'utf8');
    expect(schemas).toContain('state: Literal["within", "at_limit", "unlimited"]');
    expect(schemas).toContain('state: Literal["within", "over_allowance", "unlimited"]');
    const states = ['within', 'at_limit', 'unlimited', 'over_allowance'] as const;
    expect(new Set(states.map((state) => limitState(state).label)).size).toBe(states.length);
    expect(limitState('within').tone).toBe('success');
    expect(limitState('at_limit').tone).toBe('warning');
    expect(limitState('over_allowance').tone).toBe('warning');
    expect(limitState('unlimited').tone).toBe('neutral');
  });

  it('name only refusals the closure routes send', () => {
    const source = readFileSync(inRepository('backend', 'app', 'api', 'plans.py'), 'utf8') + readFileSync(inRepository('backend', 'app', 'services', 'agency_closure.py'), 'utf8');
    for (const code of ['confirmation_mismatch', 'closure_in_progress', 'closure_not_open', 'grace_period_ended']) expect(source, code).toContain(`"${code}"`);
  });
});

/** A plan-limit sentence on a page of the agency, for a person with the given role. */
function limitNotice(role: 'owner' | 'admin' | 'analyst' | 'client_viewer') {
  const queryClient = new QueryClient();
  queryClient.setQueryData(agenciesKey, [{ agency_id: agency.id, role, status: 'active' }]);
  const root = createRootRoute();
  const page = createRoute({
    getParentRoute: () => root,
    path: '/agencies/$agencyId/page',
    component: () => <ErrorNotice message={{ id: 'error.plan_limit_reached.seats', values: { value: 10, used: 10 } }} />,
  });
  const router = createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: [`/agencies/${agency.id}/page`] }) });
  renderWithMessages(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('the sentence of a plan limit', () => {
  it.each(['owner', 'admin'] as const)('links an %s to Plan and usage', async (role) => {
    limitNotice(role);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent("The agency's plan allows 10 seats");
    expect(within(alert).getByRole('link', { name: 'See Plan and usage' })).toHaveAttribute('href', settings);
  });

  it.each(['analyst', 'client_viewer'] as const)('gives an %s no link', async (role) => {
    limitNotice(role);
    expect(await screen.findByRole('alert')).toHaveTextContent("The agency's plan allows 10 seats");
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});

describe('Agency settings', () => {
  it('shows each limit of the plan with its use and its state, and the month of tracked events', async () => {
    fakeApi(world());
    openApp(settings);
    const links = (await screen.findByText('Managed links')).closest('tr') as HTMLElement;
    expect(links).toHaveTextContent('500 of 500');
    expect(within(links).getByText('At the limit')).toBeInTheDocument();
    // The share of each limit, and of the allowance, as a meter.
    expect(within(links).getByRole('img', { name: '100%' })).toBeInTheDocument();
    expect(within(screen.getByRole('row', { name: /^Clients/ })).getByRole('img', { name: '40%' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '86%' })).toBeInTheDocument();
    expect(screen.getByText('86,240')).toBeInTheDocument();
    expect(screen.getByText('of 100,000')).toBeInTheDocument();
  });

  it('lets an analyst read the plan and the branding, but neither edit it nor close the agency', async () => {
    fakeApi(asRole('analyst', world()));
    const user = userEvent.setup();
    openApp(settings);
    await screen.findByText('Managed links');
    expect(screen.queryByRole('tab', { name: 'Close the agency' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Branding' }));
    expect(await screen.findByText('Owners and admins change these; you can read them.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save the profile' })).not.toBeInTheDocument();
  });

  it('does not exist for a client viewer', async () => {
    fakeApi(asRole('client_viewer', world()));
    openApp(settings);
    expect(await screen.findByRole('heading', { name: 'Page not found', level: 1 })).toBeInTheDocument();
  });

  it('saves the branding profile, refuses an SVG before sending it, and uploads a PNG as its raw body', async () => {
    let profile: typeof branding | typeof saved = branding;
    const server = fakeApi(
      world({
        [`${at}/branding`]: () => json(200, profile),
        [`PUT /agencies/${agency.id}/branding`]: () => {
          profile = saved;
          return json(200, saved);
        },
        [`PUT /agencies/${agency.id}/branding/logo`]: json(200, saved),
      }),
    );
    // The picker accepts PNG files only; a person can still choose any file, as here.
    const user = userEvent.setup({ applyAccept: false });
    openApp(`${settings}?tab=branding`);
    // The API keeps a logo only with a saved profile.
    expect(await screen.findByText('Save the display name and the color first; then you can add a logo.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Upload a PNG logo')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Display name'), 'Lumen');
    await user.click(screen.getByRole('button', { name: 'Save the profile' }));
    await waitFor(() => expect(server.sent(`PUT /agencies/${agency.id}/branding`)[0]?.body).toEqual({ display_name: 'Lumen', accent_color: '#0E7C7B' }));
    // The profile is read again, and the page still says it was saved.
    await waitFor(() => expect(server.sent(`GET /agencies/${agency.id}/branding`)).toHaveLength(2));
    expect(await screen.findByText('The branding profile is saved.')).toBeInTheDocument();

    const picker = await screen.findByLabelText('Upload a PNG logo');
    await user.upload(picker, new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' }));
    expect(await screen.findByText('Choose a PNG file. SVG and other kinds of file are refused.')).toBeInTheDocument();
    expect(server.sent(`PUT /agencies/${agency.id}/branding/logo`)).toHaveLength(0);

    await user.upload(picker, png(256, 256));
    await waitFor(() => expect(server.sent(`PUT /agencies/${agency.id}/branding/logo`)).toHaveLength(1));
    expect(server.sent(`PUT /agencies/${agency.id}/branding/logo`)[0]?.headers.get('Content-Type')).toBe('image/png');
  });

  it('says when the API refuses the profile', async () => {
    fakeApi(world({ [`PUT /agencies/${agency.id}/branding`]: refused(422, 'invalid_branding') }));
    const user = userEvent.setup();
    openApp(`${settings}?tab=branding`);
    await user.type(await screen.findByLabelText('Display name'), 'Lumen');
    await user.click(screen.getByRole('button', { name: 'Save the profile' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The name or the color was refused.');
  });

  it('names the plan limit that stopped a new client, with a link to the plan', async () => {
    const limit = { error: 'plan_limit_reached', limit: 'clients', value: 5, used: 5 };
    fakeApi({ ...signedIn(), [`POST /agencies/${agency.id}/clients`]: json(409, limit) });
    const user = userEvent.setup();
    openApp('/');
    await user.click(await screen.findByRole('button', { name: 'Add client' }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.type(dialog.getByLabelText('Client name'), 'Olive and Thyme');
    await user.click(dialog.getByRole('button', { name: 'Add client' }));
    const alert = await dialog.findByRole('alert');
    expect(alert).toHaveTextContent("The agency's plan allows 5 clients, and 5 are in use, so no more can be added.");
    expect(within(alert).getByRole('link', { name: 'See Plan and usage' })).toHaveAttribute('href', settings);
  });

  it('previews the logo the API keeps, and draws none once it is removed', async () => {
    const withLogo = { ...saved, logo: { width: 48, height: 32, byte_size: 120 } };
    const revoked: string[] = [];
    // The test environment has no object addresses; these stand in for the browser's.
    Object.assign(URL, { createObjectURL: () => 'blob:logo-48', revokeObjectURL: (url: string) => void revoked.push(url) });
    try {
      let profile: typeof saved | typeof withLogo = withLogo;
      fakeApi(
        world({
          [`${at}/branding`]: () => json(200, profile),
          [`${at}/branding/logo`]: new Response(new Uint8Array([0x89, 0x50, 0x4e, 0x47]), { headers: { 'Content-Type': 'image/png' } }),
          [`DELETE /agencies/${agency.id}/branding/logo`]: () => {
            profile = { ...saved, updated_at: '2026-11-28T11:00:00Z' };
            return json(200, profile);
          },
        }),
      );
      const user = userEvent.setup();
      openApp(`${settings}?tab=branding`);
      expect(await screen.findByText('A PNG of 48 by 32 pixels, 1 KiB.')).toBeInTheDocument();
      await waitFor(() => expect(document.querySelector('.a-brand-preview__logo')).toHaveAttribute('src', 'blob:logo-48'));

      await user.click(screen.getByRole('button', { name: 'Remove the logo' }));
      expect(await screen.findByText('No logo yet.')).toBeInTheDocument();
      expect(document.querySelector('.a-brand-preview__logo')).toBeNull();
      expect(revoked).toContain('blob:logo-48');
    } finally {
      Reflect.deleteProperty(URL, 'createObjectURL');
      Reflect.deleteProperty(URL, 'revokeObjectURL');
    }
  });

  it('says why the API refused a logo', async () => {
    fakeApi(world({ [`${at}/branding`]: json(200, saved), [`PUT /agencies/${agency.id}/branding/logo`]: refused(422, 'invalid_png') }));
    const user = userEvent.setup();
    openApp(`${settings}?tab=branding`);
    await user.upload(await screen.findByLabelText('Upload a PNG logo'), png(64, 64));
    expect(await screen.findByText('This PNG file is damaged and cannot be used.')).toBeInTheDocument();
  });
});

describe('closing the agency', () => {
  const closing = { agency_id: agency.id, agency_status: 'closing', closure: { id: 'z1', requested_at: '2026-11-28T10:00:00Z', closes_at: '2026-12-28T10:00:00Z', requested_by_membership_id: 'm1' } };

  it('asks for the exact name before sending, and says when the password is wrong', async () => {
    const server = fakeApi(world({ [`POST /agencies/${agency.id}/closure`]: refused(401, 'invalid_credentials') }));
    const user = userEvent.setup();
    openApp(`${settings}?tab=closure`);
    await user.click(await screen.findByRole('button', { name: `Close ${agency.name}` }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.type(dialog.getByLabelText("Type the agency's name"), 'lumen studio');
    await user.click(dialog.getByRole('button', { name: 'Close the agency' }));
    expect(await dialog.findByText("Type the agency's name exactly as it is written.")).toBeInTheDocument();
    expect(server.sent(`POST /agencies/${agency.id}/closure`)).toHaveLength(0);

    await user.clear(dialog.getByLabelText("Type the agency's name"));
    await user.type(dialog.getByLabelText("Type the agency's name"), agency.name);
    await user.type(dialog.getByLabelText('Your password'), 'not the password');
    await user.click(dialog.getByRole('button', { name: 'Close the agency' }));
    expect(await dialog.findByText('The password is not correct.')).toBeInTheDocument();
    expect(server.sent(`POST /agencies/${agency.id}/closure`)[0]?.body).toEqual({ confirm_name: agency.name, password: 'not the password' });
  });

  it('sends no password for an account without one, and asks for a fresh Google sign-in when the API wants it', async () => {
    const server = fakeApi(world({ [`POST /agencies/${agency.id}/closure`]: refused(403, 'reauthentication_required') }));
    const user = userEvent.setup();
    openApp(`${settings}?tab=closure`);
    await user.click(await screen.findByRole('button', { name: `Close ${agency.name}` }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.type(dialog.getByLabelText("Type the agency's name"), agency.name);
    await user.click(dialog.getByRole('button', { name: 'Close the agency' }));
    expect(await dialog.findByText('Sign in with Google again, then close the agency within a few minutes.')).toBeInTheDocument();
    expect(server.sent(`POST /agencies/${agency.id}/closure`)[0]?.body).toEqual({ confirm_name: agency.name });
  });

  it('says when the agency is already closing', async () => {
    fakeApi(world({ [`POST /agencies/${agency.id}/closure`]: refused(409, 'closure_in_progress') }));
    const user = userEvent.setup();
    openApp(`${settings}?tab=closure`);
    await user.click(await screen.findByRole('button', { name: `Close ${agency.name}` }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.type(dialog.getByLabelText("Type the agency's name"), agency.name);
    await user.type(dialog.getByLabelText('Your password'), 'correct horse battery staple');
    await user.click(dialog.getByRole('button', { name: 'Close the agency' }));
    expect(await dialog.findByText('The agency is already closing.')).toBeInTheDocument();
  });

  it('opens the closing page once the agency is closing, and keeps it on request', async () => {
    const server = fakeApi(world({ [`POST /agencies/${agency.id}/closure`]: json(201, closing), [`GET /agencies/${agency.id}/closure`]: json(200, closing) }));
    const user = userEvent.setup();
    openApp(`${settings}?tab=closure`);
    await user.click(await screen.findByRole('button', { name: `Close ${agency.name}` }));
    const dialog = within(await screen.findByRole('alertdialog'));
    await user.type(dialog.getByLabelText("Type the agency's name"), agency.name);
    await user.type(dialog.getByLabelText('Your password'), 'correct horse battery staple');
    server.routes['GET /agencies'] = json(200, [{ agency_id: agency.id, role: 'owner', status: 'closing' }]);
    await user.click(dialog.getByRole('button', { name: 'Close the agency' }));

    await waitFor(() => expect(window.location.pathname).toBe(`/agencies/${agency.id}/closing`));
    expect(await screen.findByText(/The agency closes for good on/)).toBeInTheDocument();
    server.routes[`DELETE /agencies/${agency.id}/closure`] = empty();
    server.routes['GET /agencies'] = json(200, [{ agency_id: agency.id, role: 'owner', status: 'active' }]);
    await user.click(screen.getByRole('button', { name: 'Keep the agency' }));
    await waitFor(() => expect(window.location.pathname).toBe(`/agencies/${agency.id}/clients`));
    expect(server.sent(`DELETE /agencies/${agency.id}/closure`)).toHaveLength(1);
  });

  it('draws the closing page without the agency\'s navigation and asks nothing the API refuses (R018-04)', async () => {
    const server = fakeApi(
      world({
        'GET /agencies': json(200, [{ agency_id: agency.id, role: 'owner', status: 'closing' }]),
        [`GET /agencies/${agency.id}/closure`]: json(200, closing),
        [`GET /agencies/${agency.id}`]: json(200, agency),
      }),
    );
    openApp(`/agencies/${agency.id}/team`);
    await waitFor(() => expect(window.location.pathname).toBe(`/agencies/${agency.id}/closing`));
    expect(await screen.findByRole('button', { name: 'Keep the agency' })).toBeInTheDocument();
    for (const name of ['Clients', 'Team and access', 'API keys', 'Audit log', 'Agency settings']) {
      expect(screen.queryByRole('link', { name })).not.toBeInTheDocument();
    }
    expect(server.sent(`GET /agencies/${agency.id}`)).toHaveLength(0);
    expect(server.sent(`GET /agencies/${agency.id}/clients`)).toHaveLength(0);
  });

  it('says when the closure is no longer open', async () => {
    fakeApi(
      world({
        'GET /agencies': json(200, [{ agency_id: agency.id, role: 'owner', status: 'closing' }]),
        [`GET /agencies/${agency.id}/closure`]: json(200, closing),
        [`DELETE /agencies/${agency.id}/closure`]: refused(409, 'closure_not_open'),
      }),
    );
    const user = userEvent.setup();
    openApp(`/agencies/${agency.id}/closing`);
    await user.click(await screen.findByRole('button', { name: 'Keep the agency' }));
    expect(await screen.findByText('The agency is not closing any more.')).toBeInTheDocument();
  });

  it('says when the grace period has ended', async () => {
    fakeApi(
      world({
        'GET /agencies': json(200, [{ agency_id: agency.id, role: 'owner', status: 'closing' }]),
        [`GET /agencies/${agency.id}/closure`]: json(200, closing),
        [`DELETE /agencies/${agency.id}/closure`]: refused(409, 'grace_period_ended'),
      }),
    );
    const user = userEvent.setup();
    openApp(`/agencies/${agency.id}/closing`);
    await user.click(await screen.findByRole('button', { name: 'Keep the agency' }));
    expect(await screen.findByText('The 30 days have ended: the agency is closed for good.')).toBeInTheDocument();
  });
});
