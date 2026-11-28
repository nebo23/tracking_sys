import type { QueryClient } from '@tanstack/react-query';
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  notFound,
  Outlet,
  redirect,
  useRouter,
  type RouterHistory,
} from '@tanstack/react-router';
import { useEffect } from 'react';

import { agenciesQuery, type AgencyAccess } from '@/api/agencies';
import { clientQuery } from '@/api/clients';
import { isApiError } from '@/api/errors';
import { sessionQuery } from '@/api/session';
import { AcceptInvitationPage } from '@/features/auth/AcceptInvitationPage';
import { AuthLayout } from '@/features/auth/AuthLayout';
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage';
import { GoogleCompletePage } from '@/features/auth/GoogleCompletePage';
import { RegisterPage } from '@/features/auth/RegisterPage';
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage';
import { SignInPage } from '@/features/auth/SignInPage';
import { VerifyEmailPage } from '@/features/auth/VerifyEmailPage';
import { returnErrors, returnOutcomes, type ReturnError, type ReturnOutcome } from '@/features/connections/returnErrors';
import { integrationTabs, type IntegrationTabId } from '@/features/integrations/tabs';
import { linksTabs, type LinksTabId } from '@/features/links/tabs';
import { analyzeSearch } from '@/features/analyze/search';
import { isIdentifier } from '@/lib/identifier';
import { captureLinkToken, heldLinkToken } from '@/lib/linkToken';

import { agencyChoice, currentAccess, isManager } from './agency';
import { ErrorPage, LegalPage, NotFoundPage, PendingPage } from './pages';
import { signInNotices, type SignInNotice } from './sessionLifecycle';

// Every page after sign-in loads on its own (D4 of the completion entry review): the screens
// before it carry no workspace code, and only the pages that draw charts load the chart package.
const AccountPage = lazyRouteComponent(() => import('@/features/account/AccountPage'), 'AccountPage');
const AuditPage = lazyRouteComponent(() => import('@/features/audit/AuditPage'), 'AuditPage');
const ClientsPage = lazyRouteComponent(() => import('@/features/clients/ClientsPage'), 'ClientsPage');
const ClosingPage = lazyRouteComponent(() => import('@/features/agency/ClosingPage'), 'ClosingPage');
const ConnectionCompletePage = lazyRouteComponent(() => import('@/features/connections/ConnectionCompletePage'), 'ConnectionCompletePage');
const ConnectionsPage = lazyRouteComponent(() => import('@/features/connections/ConnectionsPage'), 'ConnectionsPage');
const IntegrationsPage = lazyRouteComponent(() => import('@/features/integrations/IntegrationsPage'), 'IntegrationsPage');
const KeysPage = lazyRouteComponent(() => import('@/features/keys/KeysPage'), 'KeysPage');
const LinksPage = lazyRouteComponent(() => import('@/features/links/LinksPage'), 'LinksPage');
const Shell = lazyRouteComponent(() => import('./shell/Shell'), 'Shell');
const TeamPage = lazyRouteComponent(() => import('@/features/team/TeamPage'), 'TeamPage');
const TrackingPage = lazyRouteComponent(() => import('@/features/tracking/TrackingPage'), 'TrackingPage');
const WelcomePage = lazyRouteComponent(() => import('@/features/agency/WelcomePage'), 'WelcomePage');
const OverviewPage = lazyRouteComponent(() => import('@/features/analyze/OverviewPage'), 'OverviewPage');
const ContentPage = lazyRouteComponent(() => import('@/features/analyze/ContentPage'), 'ContentPage');
const RevenuePage = lazyRouteComponent(() => import('@/features/analyze/RevenuePage'), 'RevenuePage');
const AdSpendPage = lazyRouteComponent(() => import('@/features/analyze/AdSpendPage'), 'AdSpendPage');

interface RouterContext {
  queryClient: QueryClient;
}

type Search = Record<string, unknown>;

/** After a move to another page, focus goes to its heading so the new page is announced. */
function Root() {
  const router = useRouter();
  useEffect(
    () =>
      router.subscribe('onRendered', ({ fromLocation, pathChanged }) => {
        if (fromLocation && pathChanged) {
          document.querySelector<HTMLElement>('h1[tabindex="-1"]')?.focus({ preventScroll: true });
        }
      }),
    [router],
  );
  return <Outlet />;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({ component: Root });

const loadSession = (queryClient: QueryClient) => queryClient.ensureQueryData(sessionQuery);

/** The place to return to after signing in: a path of this application, never a fragment. */
function place(location: { pathname: string; searchStr: string }): { next?: string } {
  const here = location.pathname + location.searchStr;
  return here === '/' ? {} : { next: here };
}

// ------------------------------------------------- Before the workspace --
const entryRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'entry',
  component: () => (
    <AuthLayout>
      <Outlet />
    </AuthLayout>
  ),
});

/** A person who is already signed in has no use for these screens. */
async function leaveIfSignedIn({ context }: { context: RouterContext }): Promise<void> {
  if (await loadSession(context.queryClient)) throw redirect({ to: '/' });
}

const signInRoute = createRoute({
  getParentRoute: () => entryRoute,
  path: '/sign-in',
  validateSearch: (search: Search): { next?: string; notice?: SignInNotice } => ({
    next: typeof search.next === 'string' ? search.next : undefined,
    notice: signInNotices.find((notice) => notice === search.notice),
  }),
  beforeLoad: leaveIfSignedIn,
  component: SignInPage,
});

const registerRoute = createRoute({
  getParentRoute: () => entryRoute,
  path: '/register',
  beforeLoad: leaveIfSignedIn,
  component: RegisterPage,
});

const verifyEmailRoute = createRoute({
  getParentRoute: () => entryRoute,
  path: '/verify-email',
  beforeLoad: leaveIfSignedIn,
  component: VerifyEmailPage,
});

const forgotPasswordRoute = createRoute({
  getParentRoute: () => entryRoute,
  path: '/forgot-password',
  beforeLoad: leaveIfSignedIn,
  component: ForgotPasswordPage,
});

// The two routes that mail links open. Their token leaves the address bar before anything else.
const resetPasswordRoute = createRoute({
  getParentRoute: () => entryRoute,
  path: '/auth/reset-password',
  beforeLoad: () => captureLinkToken(),
  component: ResetPasswordPage,
});

const acceptInvitationRoute = createRoute({
  getParentRoute: () => entryRoute,
  path: '/auth/accept-invitation',
  beforeLoad: async ({ context }) => {
    captureLinkToken();
    await loadSession(context.queryClient);
  },
  component: AcceptInvitationPage,
});

const googleCompleteRoute = createRoute({
  getParentRoute: () => entryRoute,
  path: '/auth/google/complete',
  validateSearch: (search: Search): { result?: 'signed_in' | 'linked'; error?: string } => ({
    result: search.result === 'signed_in' || search.result === 'linked' ? search.result : undefined,
    error: typeof search.error === 'string' && /^[a-z_]{1,64}$/.test(search.error) ? search.error : undefined,
  }),
  beforeLoad: async ({ context, search }) => {
    // The session cookie was set by the API on the way back from Google; this reads who it is.
    const session = await context.queryClient.fetchQuery({ ...sessionQuery, staleTime: 0 });
    // The terms changed while the person was away: the sign-in page explains it (A03).
    if (search.error === 'agreement_required' && !session) {
      throw redirect({ to: '/sign-in', search: { notice: 'termsChanged' } });
    }
    if (search.error || !session) return;
    if (search.result === 'linked') throw redirect({ to: '/account', search: { notice: 'googleLinked' } });
    throw redirect({ to: '/' });
  },
  component: GoogleCompletePage,
});

const welcomeRoute = createRoute({
  getParentRoute: () => entryRoute,
  path: '/welcome',
  beforeLoad: async ({ context }) => {
    if (!(await loadSession(context.queryClient))) throw redirect({ to: '/sign-in', search: { next: '/welcome' } });
    // An invitation opened in this visit comes before creating an agency of one's own.
    if (heldLinkToken('invitation')) throw redirect({ to: '/auth/accept-invitation' });
    const agencies = await context.queryClient.ensureQueryData(agenciesQuery);
    if (agencies.length > 0) throw redirect({ to: '/' });
  },
  component: WelcomePage,
});

// -------------------------------------------------------- The workspace --
const workspaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'workspace',
  beforeLoad: async ({ context, location }) => {
    if (!(await loadSession(context.queryClient))) throw redirect({ to: '/sign-in', search: place(location) });
    // The shell names the agency a person works in. A person without one still reaches their account.
    await context.queryClient.ensureQueryData(agenciesQuery);
  },
  component: Shell,
});

// The start address leads to the clients of the agency the person last worked in.
const homeRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: '/',
  beforeLoad: async ({ context }) => {
    const agencies = await context.queryClient.ensureQueryData(agenciesQuery);
    const access = currentAccess(agencies, agencyChoice.get());
    if (!access) throw redirect({ to: '/welcome' });
    throw redirect({ to: '/agencies/$agencyId/clients', params: { agencyId: access.agency_id }, replace: true });
  },
});

// ------------------------------------------------------------ An agency --
/** The person's access to the agency an address names, read again once in case it is new. */
async function accessTo(queryClient: QueryClient, agencyId: string): Promise<AgencyAccess | undefined> {
  const find = (agencies: readonly AgencyAccess[]) => agencies.find((agency) => agency.agency_id === agencyId);
  const known = find(await queryClient.ensureQueryData(agenciesQuery));
  if (known || !isIdentifier(agencyId)) return known;
  return find(await queryClient.fetchQuery({ ...agenciesQuery, staleTime: 0 }));
}

const agencyRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: '/agencies/$agencyId',
  beforeLoad: async ({ context, params, location }) => {
    const access = await accessTo(context.queryClient, params.agencyId);
    // The agency a person opens is the one the start address leads to next time.
    if (access && agencyChoice.get() !== access.agency_id) agencyChoice.set(access.agency_id);
    // A closing agency (017-A) has one page: the API refuses every other route of it.
    if (access?.status === 'closing' && location.pathname !== `/agencies/${params.agencyId}/closing`) {
      throw redirect({ to: '/agencies/$agencyId/closing', params, replace: true });
    }
    return { access };
  },
  // An address is not permission: an agency the person does not belong to does not exist for them.
  loader: ({ context }) => {
    if (!context.access) throw notFound();
  },
});

const agencyIndexRoute = createRoute({
  getParentRoute: () => agencyRoute,
  path: '/',
  beforeLoad: ({ params }) => {
    throw redirect({ to: '/agencies/$agencyId/clients', params, replace: true });
  },
});

const clientsRoute = createRoute({
  getParentRoute: () => agencyRoute,
  path: 'clients',
  component: ClientsPage,
});

// Screen B15: the page of an agency that is closing. An agency that is not closing has none.
const closingRoute = createRoute({
  getParentRoute: () => agencyRoute,
  path: 'closing',
  beforeLoad: ({ context, params }) => {
    if (context.access?.status !== 'closing') throw redirect({ to: '/agencies/$agencyId/clients', params, replace: true });
  },
  component: ClosingPage,
});

/** The pages of the people who manage the agency. For anyone else they do not exist. */
function managersOnly({ context }: { context: { access?: AgencyAccess } }): void {
  if (!isManager(context.access?.role)) throw notFound();
}

const teamRoute = createRoute({
  getParentRoute: () => agencyRoute,
  path: 'team',
  loader: managersOnly,
  component: TeamPage,
});

const keysRoute = createRoute({
  getParentRoute: () => agencyRoute,
  path: 'keys',
  loader: managersOnly,
  component: KeysPage,
});

const auditRoute = createRoute({
  getParentRoute: () => agencyRoute,
  path: 'audit',
  loader: managersOnly,
  component: AuditPage,
});

// ------------------------------------------------------------- A client --
const clientRoute = createRoute({
  getParentRoute: () => agencyRoute,
  path: 'clients/$clientId',
  // The API decides whether the person may read this client. A refusal, an unknown client and an
  // address that is not an identifier all look the same: the page does not exist.
  loader: async ({ context, params }) => {
    if (!context.access || !isIdentifier(params.clientId)) throw notFound();
    try {
      await context.queryClient.ensureQueryData(clientQuery(params.agencyId, params.clientId));
    } catch (error) {
      if (isApiError(error) && [403, 404, 422].includes(error.status)) throw notFound();
      throw error;
    }
  },
});

// The first page of a client is its overview (C01), and Analyze holds content, revenue and
// ad spend (018-C). Each keeps its range, comparison, account, metric and level in the address.
const clientIndexRoute = createRoute({
  getParentRoute: () => clientRoute,
  path: '/',
  validateSearch: analyzeSearch,
  component: OverviewPage,
});

const contentRoute = createRoute({
  getParentRoute: () => clientRoute,
  path: 'content',
  validateSearch: analyzeSearch,
  component: ContentPage,
});

const revenueRoute = createRoute({
  getParentRoute: () => clientRoute,
  path: 'revenue',
  validateSearch: analyzeSearch,
  component: RevenuePage,
});

const adSpendRoute = createRoute({
  getParentRoute: () => clientRoute,
  path: 'ad-spend',
  validateSearch: analyzeSearch,
  component: AdSpendPage,
});

const connectionsRoute = createRoute({
  getParentRoute: () => clientRoute,
  path: 'connections',
  validateSearch: (search: Search): { outcome?: ReturnOutcome; connection?: string; failed?: ReturnError } => ({
    outcome: returnOutcomes.find((outcome) => outcome === search.outcome),
    connection: isIdentifier(search.connection) ? search.connection : undefined,
    failed: returnErrors.find((code) => code === search.failed),
  }),
  component: ConnectionsPage,
});

// What a client collects (018-D): its links, its website tracking and its integrations.
const linksRoute = createRoute({
  getParentRoute: () => clientRoute,
  path: 'links',
  validateSearch: (search: Search): { tab?: LinksTabId } => ({
    tab: linksTabs.find((tab) => tab !== 'links' && tab === search.tab),
  }),
  component: LinksPage,
});

const trackingRoute = createRoute({
  getParentRoute: () => clientRoute,
  path: 'tracking',
  component: TrackingPage,
});

const integrationsRoute = createRoute({
  getParentRoute: () => clientRoute,
  path: 'integrations',
  // The tab, and the outcome of a dataset connection when the person returns from Meta.
  validateSearch: (search: Search): { tab?: IntegrationTabId; outcome?: ReturnOutcome; connection?: string; failed?: ReturnError } => ({
    tab: integrationTabs.find((tab) => tab === search.tab),
    outcome: returnOutcomes.find((outcome) => outcome === search.outcome),
    connection: isIdentifier(search.connection) ? search.connection : undefined,
    failed: returnErrors.find((code) => code === search.failed),
  }),
  component: IntegrationsPage,
});

// Where the API sends the browser after a provider. The address carries the outcome only.
const connectionCompleteRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: '/connections/complete',
  validateSearch: (search: Search): { result?: ReturnOutcome; connection_id?: string; error?: ReturnError } => ({
    result: returnOutcomes.find((outcome) => outcome === search.result),
    connection_id: isIdentifier(search.connection_id) ? search.connection_id : undefined,
    error: returnErrors.find((code) => code === search.error),
  }),
  component: ConnectionCompletePage,
});

const accountRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: '/account',
  validateSearch: (search: Search): { notice?: 'googleLinked' } => ({
    notice: search.notice === 'googleLinked' ? 'googleLinked' : undefined,
  }),
  component: AccountPage,
});

// ---------------------------------------------------------- Legal texts --
const termsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/terms',
  component: () => <LegalPage title="legal.terms.title" />,
});

const privacyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/privacy',
  component: () => <LegalPage title="legal.privacy.title" />,
});

const routeTree = rootRoute.addChildren([
  entryRoute.addChildren([
    signInRoute,
    registerRoute,
    verifyEmailRoute,
    forgotPasswordRoute,
    resetPasswordRoute,
    acceptInvitationRoute,
    googleCompleteRoute,
    welcomeRoute,
  ]),
  workspaceRoute.addChildren([
    homeRoute,
    accountRoute,
    connectionCompleteRoute,
    agencyRoute.addChildren([
      agencyIndexRoute,
      clientsRoute,
      closingRoute,
      teamRoute,
      keysRoute,
      auditRoute,
      clientRoute.addChildren([
        clientIndexRoute,
        contentRoute,
        revenueRoute,
        adSpendRoute,
        linksRoute,
        trackingRoute,
        integrationsRoute,
        connectionsRoute,
      ]),
    ]),
  ]),
  termsRoute,
  privacyRoute,
]);

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    context: { queryClient },
    defaultPendingComponent: PendingPage,
    defaultErrorComponent: ErrorPage,
    defaultNotFoundComponent: NotFoundPage,
    scrollRestoration: true,
  });
}

export type AppRouter = ReturnType<typeof createAppRouter>;

declare module '@tanstack/react-router' {
  interface Register {
    router: AppRouter;
  }
}
