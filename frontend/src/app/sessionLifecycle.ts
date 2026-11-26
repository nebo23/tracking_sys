import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useRouter, type AnyRouter } from '@tanstack/react-router';
import { useCallback } from 'react';

import { setCsrfToken, setUnauthorizedListener } from '@/api/client';
import { fetchSession, sessionKey, type Session } from '@/api/session';

import { agencyChoice } from './agency';

export const signInNotices = ['expired', 'passwordChanged', 'reset', 'verified', 'closed', 'signedOut'] as const;
export type SignInNotice = (typeof signInNotices)[number];

const notSession = { predicate: (query: { queryKey: readonly unknown[] }) => query.queryKey[0] !== sessionKey[0] };

/** Starts from an empty cache, so nothing an earlier visitor loaded can be shown to this one. */
export function beginSession(queryClient: QueryClient, session: Session): void {
  queryClient.removeQueries(notSession);
  queryClient.setQueryData(sessionKey, session);
}

interface EndOptions {
  /** Return to the current page after the next sign-in. */
  keepPlace?: boolean;
}

/** Forgets everything that belonged to the session and shows the sign-in screen. */
export async function endSession(
  queryClient: QueryClient,
  router: AnyRouter,
  notice: SignInNotice,
  { keepPlace = false }: EndOptions = {},
): Promise<void> {
  const { pathname, searchStr } = router.state.location;
  setCsrfToken(null);
  agencyChoice.set(null);
  await queryClient.cancelQueries();
  // The guard of the sign-in route reads this, so it is set before the navigation.
  queryClient.setQueryData(sessionKey, null);
  const next = keepPlace && pathname !== '/' ? pathname + searchStr : undefined;
  await router.navigate({ to: '/sign-in', search: { notice, next } });
  queryClient.removeQueries(notSession);
}

let checking = false;

/** Called after a 401: asks the API whether the session is gone, and if so ends it here too. */
export async function confirmSessionEnded(queryClient: QueryClient, router: AnyRouter): Promise<void> {
  if (checking || queryClient.getQueryData(sessionKey) === null) return;
  checking = true;
  try {
    const session = await fetchSession();
    if (session === null) await endSession(queryClient, router, 'expired', { keepPlace: true });
    else queryClient.setQueryData(sessionKey, session);
  } catch {
    // The API could not be reached. The screen that made the request reports that.
  } finally {
    checking = false;
  }
}

/** From here on, a 401 that may mean the session ended is checked and, if so, acted on. */
export function watchSession(queryClient: QueryClient, router: AnyRouter): void {
  setUnauthorizedListener(() => void confirmSessionEnded(queryClient, router));
}

export function useEndSession(): (notice: SignInNotice) => Promise<void> {
  const queryClient = useQueryClient();
  const router = useRouter();
  return useCallback((notice: SignInNotice) => endSession(queryClient, router, notice), [queryClient, router]);
}
