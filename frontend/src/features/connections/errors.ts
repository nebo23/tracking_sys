import type { MessageId } from '@/i18n';

// The sentences for the refusals of the connection operations (docs/engineering/connectors.md).
// A unit test compares these codes with the ones the API can raise.
export const connectionErrors: Partial<Record<string, MessageId>> = {
  provider_unavailable: 'connections.error.provider_unavailable',
  connector_not_configured: 'connections.error.provider_unavailable',
  agent_approval_required: 'connections.error.agent_approval_required',
  invalid_account: 'connections.error.invalid_account',
  account_unavailable: 'connections.error.account_unavailable',
  account_mismatch: 'connections.error.account_mismatch',
  account_already_connected: 'connections.error.account_already_connected',
  connection_failed: 'connections.error.connection_failed',
  connection_denied: 'connections.error.connection_denied',
  connection_changed: 'connections.error.connection_changed',
  connection_not_active: 'connections.error.connection_not_active',
  reconnect_not_available: 'connections.error.reconnect_not_available',
  scopes_missing: 'connections.error.scopes_missing',
  sync_in_progress: 'connections.error.sync_in_progress',
  sync_required: 'connections.error.sync_required',
  invalid_stream: 'connections.error.sync_failed',
  invalid_backfill: 'connections.error.sync_failed',
  // In these operations a refusal means the role, and a conflict means the state moved on.
  access_denied: 'connections.error.access_denied',
};
