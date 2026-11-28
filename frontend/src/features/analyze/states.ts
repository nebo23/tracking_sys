import type { MessageId } from '@/i18n';

// The data-state rule (D7 of the 018 entry review): a figure that is missing, unsupported,
// partial, stale or provisional is named as such, never shown as a number it is not. These are
// the closed codes of the 016-A reports (backend/app/reporting/); a unit test reads them there
// and fails when one has no sentence here, or when this list names one the API never sends.

/** Why one value is not there: the availability of a cell and its stored reason. */
export const valueReasons = {
  // missing
  not_returned: 'analyze.reason.not_returned',
  below_threshold: 'analyze.reason.below_threshold',
  no_record: 'analyze.reason.no_record',
  invalid_value: 'analyze.reason.invalid_value',
  conflicting_records: 'analyze.reason.conflicting_records',
  // unsupported
  product_type: 'analyze.reason.product_type',
  product_type_unknown: 'analyze.reason.product_type_unknown',
  // not_synced
  outside_coverage: 'analyze.reason.outside_coverage',
} as const satisfies Record<string, MessageId>;

/** Why a total is a labeled subtotal (partial) or has no value at all (unavailable). */
export const totalReasons = {
  sync_in_progress: 'analyze.reason.sync_in_progress',
  incomplete_days: 'analyze.reason.incomplete_days',
  coverage_incomplete: 'analyze.reason.coverage_incomplete',
  incomplete_contents: 'analyze.reason.incomplete_contents',
  product_type_unknown: 'analyze.reason.product_type_unknown',
  inventory_unproven: 'analyze.reason.inventory_unproven',
  refused_facts: 'analyze.reason.refused_facts',
  time_zone_changed: 'analyze.reason.time_zone_changed',
  definition_changed: 'analyze.reason.definition_changed',
  non_additive: 'analyze.reason.non_additive',
  missing: 'analyze.reason.missing',
  not_synced: 'analyze.reason.not_synced',
  unsupported: 'analyze.reason.unsupported',
  no_content: 'analyze.reason.no_content',
  no_spend_facts: 'analyze.reason.no_spend_facts',
} as const satisfies Record<string, MessageId>;

/** Why two periods are not compared. */
export const comparisonReasons = {
  definition_changed: 'analyze.compare.definition_changed',
  non_additive: 'analyze.compare.non_additive',
  unavailable: 'analyze.compare.unavailable',
  sync_in_progress: 'analyze.compare.sync_in_progress',
  partial: 'analyze.compare.partial',
  provisional: 'analyze.compare.provisional',
  stale: 'analyze.compare.stale',
  zero_baseline: 'analyze.compare.zero_baseline',
} as const satisfies Record<string, MessageId>;

/** How recent a stream's data is, against its family's window. */
export const freshnessStates = {
  fresh: 'analyze.freshness.fresh',
  stale: 'analyze.freshness.stale',
  never_synced: 'analyze.freshness.never_synced',
} as const satisfies Record<string, MessageId>;

/** What each social stream holds, as the Sources card names it (backend/app/reporting/catalog.py). */
export const streamNames = {
  account: 'analyze.stream.account',
  media: 'analyze.stream.media',
  stories: 'analyze.stream.stories',
  channel: 'analyze.stream.channel',
  channel_daily: 'analyze.stream.channel_daily',
  videos: 'analyze.stream.videos',
  video_totals: 'analyze.stream.video_totals',
} as const satisfies Record<string, MessageId>;

export type Availability = 'available' | 'missing' | 'unsupported' | 'not_synced';

const availabilityWords: Record<Availability, MessageId> = {
  available: 'analyze.availability.available',
  missing: 'analyze.availability.missing',
  unsupported: 'analyze.availability.unsupported',
  not_synced: 'analyze.availability.not_synced',
};

const lookup = (table: Record<string, MessageId>, code: string | null | undefined): MessageId | null =>
  code && Object.hasOwn(table, code) ? (table[code] ?? null) : null;

/** The words for a value that is not available: its state, and its reason when the API names one. */
export function valueState(availability: Availability, reason: string | null | undefined): { state: MessageId; reason: MessageId | null } {
  return { state: availabilityWords[availability], reason: lookup(valueReasons, reason) };
}

/** The sentence for a total's reason; an unknown code is named as a general gap, never hidden. */
export function totalReason(reason: string | null | undefined): MessageId {
  return lookup(totalReasons, reason) ?? 'analyze.reason.other';
}

export function comparisonReason(reason: string | null | undefined): MessageId {
  return lookup(comparisonReasons, reason) ?? 'analyze.compare.other';
}

/** The sentence for a stream, or null for one this interface does not know yet: never the API's name. */
export function streamName(stream: string | null | undefined): MessageId | null {
  return lookup(streamNames, stream);
}

export function freshnessState(state: string | null | undefined): MessageId {
  return lookup(freshnessStates, state) ?? 'analyze.freshness.never_synced';
}
