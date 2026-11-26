import { queryOptions } from '@tanstack/react-query';

import { api, call, setCsrfToken } from './client';
import { isApiError } from './errors';
import type { components } from './schema';

export type Session = components['schemas']['SessionResponse'];
export type User = components['schemas']['UserResponse'];

export const sessionKey = ['session'] as const;

/** The signed-in session, or null when nobody is signed in. */
export async function fetchSession(): Promise<Session | null> {
  try {
    const session = await call(api.GET('/auth/me'), { asksAboutSession: true });
    setCsrfToken(session.csrf_token);
    return session;
  } catch (error) {
    if (isApiError(error) && error.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw error;
  }
}

export const sessionQuery = queryOptions({
  queryKey: sessionKey,
  queryFn: fetchSession,
  staleTime: 60_000,
});

export async function signIn(email: string, password: string): Promise<Session> {
  const session = await call(api.POST('/auth/login', { body: { email, password } }));
  setCsrfToken(session.csrf_token);
  return session;
}

async function ended(request: Promise<unknown>): Promise<void> {
  try {
    await request;
  } catch (error) {
    // A 401 means the session had already ended, which is what was asked for.
    if (!isApiError(error) || error.status !== 401) throw error;
  }
  setCsrfToken(null);
}

export const signOut = (): Promise<void> => ended(call(api.POST('/auth/logout'), { asksAboutSession: true }));

export const signOutEverywhere = (): Promise<void> => ended(call(api.POST('/auth/logout-all'), { asksAboutSession: true }));

export function register(displayName: string, email: string, password: string) {
  return call(api.POST('/auth/register', { body: { display_name: displayName, email, password } }));
}

export function verifyEmailCode(email: string, code: string) {
  return call(api.POST('/auth/verify-email-code', { body: { email, code } }));
}

export function resendVerification(email: string) {
  return call(api.POST('/auth/resend-verification', { body: { email } }));
}

export function forgotPassword(email: string) {
  return call(api.POST('/auth/forgot-password', { body: { email } }));
}

export function resetPassword(token: string, password: string) {
  return call(api.POST('/auth/reset-password', { body: { token, password } }));
}

// A wrong password answers 401 invalid_credentials, which is not the end of the session.
export function changePassword(currentPassword: string, newPassword: string) {
  return call(api.POST('/auth/change-password', { body: { current_password: currentPassword, new_password: newPassword } }));
}

/** An account without a password sends none; the API then asks for a recent Google sign-in. */
export function closeAccount(password: string) {
  return call(api.POST('/auth/close-account', { body: password === '' ? {} : { password } }));
}

export function linkGoogle() {
  return call(api.POST('/auth/google/link'));
}

export function acceptInvitation(token: string) {
  return call(api.POST('/invitations/accept', { body: { token } }));
}
