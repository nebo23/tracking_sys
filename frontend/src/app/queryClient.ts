import { QueryClient } from '@tanstack/react-query';

import { isApiError } from '@/api/errors';

/** A request is tried again only when it never reached the API or the API was unavailable. */
function worthRetrying(failures: number, error: unknown): boolean {
  if (failures >= 2) return false;
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
