import type { QueryClient } from '@tanstack/react-query';
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
  useRouter,
  type RouterHistory,
} from '@tanstack/react-router';
import { useEffect } from 'react';

import { agenciesQuery } from '@/api/agencies';
import { sessionQuery } from '@/api/session';
import { AccountPage } from '@/features/account/AccountPage';
import { HomePage } from '@/features/agency/HomePage';
import { WelcomePage } from '@/features/agency/WelcomePage';
import { AcceptInvitationPage } from '@/features/auth/AcceptInvitationPage';
import { AuthLayout } from '@/features/auth/AuthLayout';
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage';
import { GoogleCompletePage } from '@/features/auth/GoogleCompletePage';
import { RegisterPage } from '@/features/auth/RegisterPage';
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage';
import { SignInPage } from '@/features/auth/SignInPage';
import { VerifyEmailPage } from '@/features/auth/VerifyEmailPage';
import { captureLinkToken, heldLinkToken } from '@/lib/linkToken';

import { ErrorPage, LegalPage, NotFoundPage, PendingPage } from './pages';
import { signInNotices, type SignInNotice } from './sessionLifecycle';
import { Shell } from './shell/Shell';

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
    const agencies = await context.queryClient.ensureQueryData(agenciesQuery);
    if (agencies.length === 0) throw redirect({ to: '/welcome' });
  },
  component: Shell,
});

const homeRoute = createRoute({
  getParentRoute: () => workspaceRoute,
  path: '/',
  component: HomePage,
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
  workspaceRoute.addChildren([homeRoute, accountRoute]),
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
