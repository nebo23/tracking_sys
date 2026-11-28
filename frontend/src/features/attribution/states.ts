import type { MessageId } from '@/i18n';

import type { ExactShare } from '@/api/reports';

// The closed codes of the 016-B reports (backend/app/reporting/credit.py, funnel.py and roas.py,
// and the shared freshness of the attribution store). A unit test reads them there and fails when
// one has no sentence here, or when this list names one the API never sends.

/** Why credit, a reconciliation or a whole report has no value yet, or why its values may be behind. */
export const attributionReasons = {
  attribution_not_ready: 'attribution.reason.attribution_not_ready',
  attribution_behind: 'attribution.reason.attribution_behind',
  attribution_rebuilding: 'attribution.reason.attribution_rebuilding',
  attribution_failed: 'attribution.reason.attribution_failed',
  unexplained_difference: 'attribution.reason.unexplained_difference',
  ledger_unavailable: 'attribution.reason.ledger_unavailable',
} as const satisfies Record<string, MessageId>;

/** Why a return on ad spend or a cost per lead is not worked out. */
export const roasReasons = {
  zero_spend: 'attribution.roas.reason.zero_spend',
  zero_leads: 'attribution.roas.reason.zero_leads',
  currency_mismatch: 'attribution.roas.reason.currency_mismatch',
} as const satisfies Record<string, MessageId>;

/** The state of the attribution store that a banner names; caught up needs none. */
export const freshnessBanners = {
  behind: 'attribution.freshness.behind',
  rebuilding: 'attribution.freshness.rebuilding',
  failed: 'attribution.freshness.failed',
} as const satisfies Record<string, MessageId>;

export function attributionReason(code: string | null | undefined): MessageId {
  return code && Object.hasOwn(attributionReasons, code) ? attributionReasons[code as keyof typeof attributionReasons] : 'attribution.reason.other';
}

export function roasReason(code: string | null | undefined): MessageId {
  return code && Object.hasOwn(roasReasons, code) ? roasReasons[code as keyof typeof roasReasons] : 'attribution.roas.reason.other';
}

/**
 * A share of credit as the API states it, exactly: under Linear a sale can be shared, so counts
 * have decimals. The decimal text is formatted, never recomputed from the fraction.
 */
export function shareText(locale: string, share: ExactShare | null | undefined): string | null {
  if (!share) return null;
  try {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 2, numberingSystem: 'latn' }).format(share.decimal as unknown as number);
  } catch {
    return share.decimal;
  }
}
