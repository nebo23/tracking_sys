import { useMutation } from '@tanstack/react-query';

import { describeError, type ErrorMessage } from '@/api/errors';
import { signOut, signOutEverywhere } from '@/api/session';

import { useEndSession } from './sessionLifecycle';

/** Ends this session, or every session of the account, then shows the sign-in screen. */
export function useSignOut(onProblem: (message: ErrorMessage) => void) {
  const end = useEndSession();
  return useMutation({
    mutationFn: (everywhere: boolean) => (everywhere ? signOutEverywhere() : signOut()),
    onSuccess: () => end('signedOut'),
    onError: (error) => onProblem(describeError(error)),
  });
}
