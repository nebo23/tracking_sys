import type { MessageId } from '@/i18n';

/** What an audit event names, besides its client: a member, an invitation, a key, a client, or nothing more. */
export type AuditSubject = 'member' | 'invitation' | 'key' | 'client' | 'none';

interface AuditAction {
  message: MessageId;
  subject: AuditSubject;
}

const action = (message: MessageId, subject: AuditSubject = 'none'): AuditAction => ({ message, subject });

// The action codes the API writes to the audit log (backend/app/services). A unit test reads the
// API source and fails when a code has no sentence here.
const actions: Record<string, AuditAction> = {
  'agency.created': action('audit.action.agency.created'),
  'agency.updated': action('audit.action.agency.updated'),
  'client.created': action('audit.action.client.created', 'client'),
  'client.updated': action('audit.action.client.updated', 'client'),
  'membership.created': action('audit.action.membership.created', 'member'),
  'membership.updated': action('audit.action.membership.updated', 'member'),
  'grant.created': action('audit.action.grant.created', 'member'),
  'grant.updated': action('audit.action.grant.updated', 'member'),
  'grant.revoked': action('audit.action.grant.revoked', 'member'),
  'invitation.created': action('audit.action.invitation.created', 'invitation'),
  'invitation.revoked': action('audit.action.invitation.revoked', 'invitation'),
  'invitation.accepted': action('audit.action.invitation.accepted'),
  'credential.created': action('audit.action.credential.created', 'key'),
  'credential.revoked': action('audit.action.credential.revoked', 'key'),
  'connector.connected': action('audit.action.connector.connected'),
  'connector.reconnected': action('audit.action.connector.reconnected'),
  'connector.disconnect_requested': action('audit.action.connector.disconnect_requested'),
  'source.created': action('audit.action.source.created'),
  'source.updated': action('audit.action.source.updated'),
  'source.secret_rotated': action('audit.action.source.secret_rotated'),
  'form.updated': action('audit.action.form.updated'),
  'deletion.requested': action('audit.action.deletion.requested'),
  'link.created': action('audit.action.link.created'),
  'link.updated': action('audit.action.link.updated'),
  'campaign.created': action('audit.action.campaign.created'),
  'campaign.updated': action('audit.action.campaign.updated'),
  'content.created': action('audit.action.content.created'),
  'content.updated': action('audit.action.content.updated'),
  'template.created': action('audit.action.template.created'),
  'template.updated': action('audit.action.template.updated'),
  'origin.created': action('audit.action.origin.created'),
  'origin.updated': action('audit.action.origin.updated'),
  'domain.created': action('audit.action.domain.created'),
  'domain.updated': action('audit.action.domain.updated'),
  'domain.challenge_issued': action('audit.action.domain.challenge_issued'),
  'domain.checked': action('audit.action.domain.checked'),
  'payment_source.created': action('audit.action.payment_source.created'),
  'payment_source.updated': action('audit.action.payment_source.updated'),
  'payment_source.secret_replaced': action('audit.action.payment_source.secret_replaced'),
  'integration.created': action('audit.action.integration.created'),
  'integration.updated': action('audit.action.integration.updated'),
  'integration.secret_replaced': action('audit.action.integration.secret_replaced'),
  'whatsapp_number.created': action('audit.action.whatsapp_number.created'),
  'whatsapp_number.updated': action('audit.action.whatsapp_number.updated'),
  'crm_rule.created': action('audit.action.crm_rule.created'),
  'crm_rule.updated': action('audit.action.crm_rule.updated'),
  'destination.created': action('audit.action.destination.created'),
  'destination.updated': action('audit.action.destination.updated'),
  'delivery.requeued': action('audit.action.delivery.requeued'),
  'delivery.dismissed': action('audit.action.delivery.dismissed'),
  'revenue.declared': action('audit.action.revenue.declared'),
  'revenue_import.committed': action('audit.action.revenue_import.committed'),
  'revenue.reconciliation_reviewed': action('audit.action.revenue.reconciliation_reviewed'),
  'revenue.association_detached': action('audit.action.revenue.association_detached'),
  'identity.merged': action('audit.action.identity.merged'),
  'identity.unmerged': action('audit.action.identity.unmerged'),
  'identity.erased': action('audit.action.identity.erased'),
  'identity.erasure_resolved': action('audit.action.identity.erasure_resolved'),
  'attribution.model_created': action('audit.action.attribution.model_created'),
  'attribution.model_default_set': action('audit.action.attribution.model_default_set'),
  'attribution.model_retired': action('audit.action.attribution.model_retired'),
};

/** The sentence of an action code, or null for a code this interface does not know yet. */
export const auditAction = (code: string): AuditAction | null => actions[code] ?? null;

export const knownAuditActions = (): string[] => Object.keys(actions);
