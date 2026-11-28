import type { ErrorMessage } from '@/api/errors';
import { goTo, isSecureAddress } from '@/lib/browser';

import { pendingConnection, type PendingConnection } from './pendingConnection';

/**
 * Follows the address the API handed over for an authorization, remembering which client the
 * person was connecting. Anything that is not an https address is refused: the API answers with
 * the provider's own address, and the application goes nowhere else.
 */
export function leaveForProvider(address: string, scope: PendingConnection): ErrorMessage | null {
  if (!isSecureAddress(address)) return { id: 'connections.error.connection_failed' };
  pendingConnection.set(scope);
  goTo(address);
  return null;
}
