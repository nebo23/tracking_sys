import type { MessageId } from '@/i18n';

const planLimits = ['clients', 'seats', 'connections', 'managed_links'] as const;

/** The limit that a 409 plan_limit_reached names: which one, its value and its use (017-A). */
export interface PlanLimit {
  limit: (typeof planLimits)[number];
  value: number;
  used: number;
}

/** The limit in an error body, when the API named one completely; otherwise null. */
export function planLimitOf(body: unknown): PlanLimit | null {
  if (typeof body !== 'object' || body === null) return null;
  const { limit, value, used } = body as Record<string, unknown>;
  const known = planLimits.find((name) => name === limit);
  if (!known || typeof value !== 'number' || typeof used !== 'number') return null;
  return { limit: known, value, used };
}

/** An error answer of the API, or a request that never reached it (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** Seconds from Retry-After, when the browser is allowed to read that header. */
  readonly retryAfterSeconds: number | null;
  /** The limit of a plan_limit_reached answer, when the API named it. */
  readonly planLimit: PlanLimit | null;

  constructor(status: number, code: string, retryAfterSeconds: number | null = null, planLimit: PlanLimit | null = null) {
    super(code);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
    this.planLimit = planLimit;
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
  // A plan limit of specification 017-A (D-092), answered on creations and reactivations once it merges.
  plan_limit_reached: 'error.plan_limit_reached',
  // Event collection (specification 004): the server has no keyrings for it.
  collection_not_configured: 'tracking.error.notConfigured',
  // Integrations (specifications 014 and 015) that the server has switched off.
  payments_unavailable: 'integrations.error.payments_unavailable',
  integration_unavailable: 'integrations.error.integration_unavailable',
  whatsapp_unavailable: 'integrations.error.whatsapp_unavailable',
  // 016-A and 016-B: the stored facts changed between the pages of one report, or one currency
  // has two numbers of decimals in a client's records.
  report_changed: 'analyze.error.report_changed',
  currency_exponent_conflict: 'analyze.error.currency_exponent_conflict',
  // Bounds of a report that no retry changes (the bounds table of docs/engineering/reporting.md).
  report_requires_ledger_upgrade: 'analyze.error.report_requires_ledger_upgrade',
  report_too_large: 'analyze.error.report_too_large',
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
  // A named plan limit says more than any screen's own sentence for the code.
  if (error.code === 'plan_limit_reached' && error.planLimit) {
    const { limit, value, used } = error.planLimit;
    return { id: `error.plan_limit_reached.${limit}`, values: { value, used } };
  }
  const override = overrides[error.code];
  if (override) return { id: override };
  if (error.code === 'rate_limited' && error.retryAfterSeconds !== null) {
    return { id: 'error.rate_limitedSeconds', values: { seconds: error.retryAfterSeconds } };
  }
  return { id: byCode[error.code] ?? 'error.unknown' };
}
