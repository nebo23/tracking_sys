import { queryOptions, type QueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { isApiError } from './errors';
import type { components } from './schema';

export type AgreementVersions = components['schemas']['AgreementVersions'];
/** The versions a person accepts by ticking the agreement box: the ones the API names as current. */
export type AcceptedAgreements = components['schemas']['AgreementAcceptance'];

export const agreementsKey = ['agreements'] as const;

/** The current Terms of Service and Privacy Policy versions (017-A). */
export const agreementsQuery = queryOptions({
  queryKey: agreementsKey,
  queryFn: () => call(api.GET('/auth/agreements')),
  staleTime: 5 * 60_000,
});

/**
 * The versions to send with a sign-in or a registration, read again once they are out of date.
 * Like the request it belongs to, a failed read is not tried again: the person sees why at once.
 */
export async function currentAgreements(queryClient: QueryClient): Promise<AcceptedAgreements> {
  const { terms, privacy } = await queryClient.fetchQuery({ ...agreementsQuery, retry: false });
  return { terms, privacy };
}

/** The API refused the versions it was sent: they changed while the page was open. */
export function isAgreementRequired(error: unknown): boolean {
  return isApiError(error) && error.code === 'agreement_required';
}

/** Drops the cached versions, so that the next attempt reads the new ones. */
export function forgetAgreements(queryClient: QueryClient): void {
  queryClient.removeQueries({ queryKey: agreementsKey });
}

/** The address that starts Google sign-in with the accepted versions (GET /auth/google/start). */
export function googleStartAddress(apiOrigin: string, accepted: AcceptedAgreements): string {
  const query = new URLSearchParams({ terms: accepted.terms, privacy: accepted.privacy });
  return `${apiOrigin}/auth/google/start?${query.toString()}`;
}
