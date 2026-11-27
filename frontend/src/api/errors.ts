import type { MessageId } from '@/i18n';

/** An error answer of the API, or a request that never reached it (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** Seconds from Retry-After, when the browser is allowed to read that header. */
  readonly retryAfterSeconds: number | null;

  constructor(status: number, code: string, retryAfterSeconds: number | null = null) {
    super(code);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;

export interface ErrorMessage {
  id: MessageId;
  values?: Record<string, string | number>;
}

// Every error code of the authentication guide has one sentence. A screen may replace a code
// with a sentence that fits its context, such as "The current password is not correct."
const byCode: Record<string, MessageId> = {
  network_error: 'error.network',
  authentication_required: 'error.authentication_required',
  invalid_credentials: 'signIn.error.credentials',
  email_verification_required: 'signIn.error.unverified',
  invalid_or_expired_code: 'verify.error.code',
  invalid_or_expired_token: 'reset.error.token',
  reauthentication_required: 'account.close.error.reauth',
  origin_not_allowed: 'error.session_check',
  csrf_failed: 'error.session_check',
  access_denied: 'error.access_denied',
  not_found: 'error.not_found',
  state_conflict: 'error.state_conflict',
  rate_limited: 'error.rate_limited',
  validation_failed: 'error.validation_failed',
  request_too_large: 'error.request_too_large',
  temporarily_unavailable: 'error.temporarily_unavailable',
  // 017-A: a sign-in or registration without the current agreement versions.
  agreement_required: 'agreement.changed.title',
  // Google sign-in. The same codes arrive in the address of the completion page.
  google_link_required: 'google.error.google_link_required',
  google_email_not_verified: 'google.error.google_email_not_verified',
  google_sign_in_cancelled: 'google.error.google_sign_in_cancelled',
  google_identity_in_use: 'google.error.google_identity_in_use',
  google_already_linked: 'google.error.google_already_linked',
  google_sign_in_failed: 'google.error.other',
  google_sign_in_conflict: 'google.error.other',
  google_unavailable: 'google.error.other',
};

export function describeError(error: unknown, overrides: Partial<Record<string, MessageId>> = {}): ErrorMessage {
  if (!isApiError(error)) return { id: 'error.unknown' };
  const override = overrides[error.code];
  if (override) return { id: override };
  if (error.code === 'rate_limited' && error.retryAfterSeconds !== null) {
    return { id: 'error.rate_limitedSeconds', values: { seconds: error.retryAfterSeconds } };
  }
  return { id: byCode[error.code] ?? 'error.unknown' };
}
