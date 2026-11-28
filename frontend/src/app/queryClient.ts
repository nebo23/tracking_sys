import { QueryClient } from '@tanstack/react-query';

import { isApiError } from '@/api/errors';

// Answers of 503 that describe how the server is set up, not a passing problem: a feature that is
// switched off stays off, so asking again only delays the sentence that says so.
const settled = new Set(['collection_not_configured', 'payments_unavailable', 'integration_unavailable', 'whatsapp_unavailable', 'verification_unavailable']);

/** A request is tried again only when it never reached the API or the API was unavailable for a moment. */
export function worthRetrying(failures: number, error: unknown): boolean {
  if (failures >= 2) return false;
  if (isApiError(error) && settled.has(error.code)) return false;
  return !isApiError(error) || error.status === 0 || error.status >= 500;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: worthRetrying, staleTime: 30_000, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}
