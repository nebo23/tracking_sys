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
  // 017-A: the plan, the operator's suspension and the closure of the agency.
  'agency.plan_assigned': action('audit.action.agency.plan_assigned'),
  'agency.suspended': action('audit.action.agency.suspended'),
  'agency.reactivated': action('audit.action.agency.reactivated'),
  'agency.closure_requested': action('audit.action.agency.closure_requested'),
  'agency.closure_cancelled': action('audit.action.agency.closure_cancelled'),
  // Platform rows without an agency; the agency's audit log never lists them.
  'plan.created': action('audit.action.plan.created'),
  'plan.default_set': action('audit.action.plan.default_set'),
  // 016-C: retained exports, scheduled reports and the branding profile.
  'report_export.created': action('audit.action.report_export.created'),
  'report_export.revoked': action('audit.action.report_export.revoked'),
  'report_schedule.created': action('audit.action.report_schedule.created'),
  'report_schedule.updated': action('audit.action.report_schedule.updated'),
  'report_schedule.deleted': action('audit.action.report_schedule.deleted'),
  'branding.updated': action('audit.action.branding.updated'),
  // 017-B and 017-C: the copy of the agency's data while it closes, and its subscription.
  'agency.export_requested': action('audit.action.agency.export_requested'),
  'agency.export_revoked': action('audit.action.agency.export_revoked'),
  'billing.checkout_created': action('audit.action.billing.checkout_created'),
  'billing.plan_change_requested': action('audit.action.billing.plan_change_requested'),
  'billing.cancel_scheduled': action('audit.action.billing.cancel_scheduled'),
  'billing.cancel_removed': action('audit.action.billing.cancel_removed'),
  'billing.reconciled': action('audit.action.billing.reconciled'),
  'billing.granted': action('audit.action.billing.granted'),
  'billing.grant_ended': action('audit.action.billing.grant_ended'),
  'billing.trial_extended': action('audit.action.billing.trial_extended'),
  // Platform rows without an agency (017-C prices); the agency's audit log never lists them.
  'billing_price.registered': action('audit.action.billing_price.registered'),
  'billing_price.retired': action('audit.action.billing_price.retired'),
};

/** The sentence of an action code, or null for a code this interface does not know yet. */
export const auditAction = (code: string): AuditAction | null => actions[code] ?? null;

export const knownAuditActions = (): string[] => Object.keys(actions);
