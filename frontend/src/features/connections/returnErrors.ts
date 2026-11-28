import type { MessageId } from '@/i18n';

// The fixed outcomes with which the API sends the browser back from a provider when the
// connection was not made (docs/engineering/connectors.md, "Flow"). Nothing else is read from
// that address.
export const returnErrors = [
  'connection_failed',
  'connection_cancelled',
  'connection_denied',
  'connection_changed',
  'account_mismatch',
  'account_already_connected',
  'account_unavailable',
  'scopes_missing',
  'provider_unavailable',
  'connector_not_configured',
  'plan_limit_reached',
] as const;

export type ReturnError = (typeof returnErrors)[number];

/** What the API reports when the provider agreed: a new connection, or an existing one working again. */
export const returnOutcomes = ['connected', 'reconnected'] as const;

export type ReturnOutcome = (typeof returnOutcomes)[number];

export const returnErrorMessage: Record<ReturnError, MessageId> = {
  connection_failed: 'connections.error.connection_failed',
  connection_cancelled: 'connections.error.connection_cancelled',
  connection_denied: 'connections.error.connection_denied',
  connection_changed: 'connections.error.connection_changed',
  account_mismatch: 'connections.error.account_mismatch',
  account_already_connected: 'connections.error.account_already_connected',
  account_unavailable: 'connections.error.account_unavailable',
  scopes_missing: 'connections.error.scopes_missing',
  provider_unavailable: 'connections.error.provider_unavailable',
  connector_not_configured: 'connections.error.provider_unavailable',
  plan_limit_reached: 'connections.error.plan_limit_reached',
};
