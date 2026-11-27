import type { FormField } from '@/api/tracking';
import type { MessageId } from '@/i18n';

// The rules of the API for event collection (backend/app/collection/contract.py and
// services/collection.py), checked before a request is sent. The API checks them again.

export const SOURCE_NAME_MAX = 100;
export const ORIGINS_MAX = 10;
export const ORIGIN_MAX = 200;
export const FORM_FIELDS_MAX = 32;
export const FIELD_NAME_MAX = 100;
export const FIELD_LABEL_MAX = 200;
export const OPTION_MAX = 100;
export const OPTIONS_MAX = 100;
/** The longest range the daily counters are read for (31 days, both ends included). */
export const DIAGNOSTIC_DAYS_MAX = 31;

/** The version of the tracker package whose files a website serves (packages/tracker-js). */
export const TRACKER_VERSION = '0.6.0';

const FORM_KEY = /^[a-z0-9_-]{1,100}$/;
const FIELD_NAME = /^[A-Za-z0-9_.-]{1,100}$/;

export const fieldClasses = ['form.option', 'form.code', 'form.quantity'] as const;
export type FieldClass = (typeof fieldClasses)[number];

export function sourceNameError(value: string): MessageId | null {
  const name = value.trim();
  if (name === '') return 'field.error.required';
  return name.length > SOURCE_NAME_MAX ? 'links.rule.labelLong' : null;
}

/** The sites typed into one field, one per line or separated by commas or spaces. */
export const splitOrigins = (text: string): string[] =>
  text
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter(Boolean);

/**
 * The exact origins a browser source accepts, as a browser sends them in its Origin header:
 * lowercase, without a default port and without a path. The API compares them character for
 * character, so a site typed with a slash or capitals is written the way the browser sends it.
 */
export function exactOrigins(texts: readonly string[]): { origins: string[]; error: MessageId | null } {
  if (texts.length === 0) return { origins: [], error: 'tracking.rule.originsNone' };
  if (texts.length > ORIGINS_MAX) return { origins: [], error: 'tracking.rule.originsMany' };
  const origins: string[] = [];
  for (const text of texts) {
    const bare = text.replace(/\/$/, '');
    let parsed: URL;
    try {
      parsed = new URL(bare);
    } catch {
      return { origins: [], error: 'tracking.rule.origin' };
    }
    const plain = /^https?:\/\/[^/?#@*\s]+$/i.test(bare);
    if (!plain || !['http:', 'https:'].includes(parsed.protocol) || parsed.origin.length > ORIGIN_MAX) {
      return { origins: [], error: 'tracking.rule.origin' };
    }
    origins.push(parsed.origin);
  }
  if (new Set(origins).size !== origins.length) return { origins: [], error: 'tracking.rule.originsTwice' };
  return { origins, error: null };
}

/**
 * The SHA-256 digest of the consent notice the website shows, as 64 lowercase hexadecimal
 * characters. It is calculated here from the text exactly as given; only the digest is sent.
 */
export async function noticeDigest(text: string): Promise<string> {
  const bytes = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function formKeyError(value: string): MessageId | null {
  if (value === '') return 'field.error.required';
  return FORM_KEY.test(value) ? null : 'tracking.rule.formKey';
}

export interface FieldDraft {
  name: string;
  label: string;
  dataClass: FieldClass;
  /** The choices of an option field, one per line or separated by commas. */
  options: string;
}

export const splitOptions = (text: string): string[] =>
  text
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);

export interface FieldErrors {
  name?: MessageId | null;
  label?: MessageId | null;
  options?: MessageId | null;
}

/** Checks the fields of a form as the API does, and returns what it would store. */
export function formFields(drafts: readonly FieldDraft[]): { fields: FormField[]; errors: FieldErrors[]; error: MessageId | null } {
  const errors: FieldErrors[] = drafts.map(() => ({}));
  if (drafts.length === 0) return { fields: [], errors, error: 'tracking.rule.fieldsNone' };
  if (drafts.length > FORM_FIELDS_MAX) return { fields: [], errors, error: 'tracking.rule.fieldsMany' };
  const names = drafts.map((draft) => draft.name.trim());
  const fields = drafts.map((draft, index): FormField => {
    const name = names[index] ?? '';
    const found: FieldErrors = errors[index] ?? {};
    if (name === '') found.name = 'field.error.required';
    else if (!FIELD_NAME.test(name)) found.name = 'tracking.rule.fieldName';
    else if (names.indexOf(name) !== index) found.name = 'tracking.rule.fieldNameTwice';
    if (draft.label.trim().length > FIELD_LABEL_MAX) found.label = 'links.rule.labelLong';
    const options = draft.dataClass === 'form.option' ? splitOptions(draft.options) : [];
    if (draft.dataClass === 'form.option') {
      if (options.length === 0) found.options = 'tracking.rule.optionsNone';
      else if (options.length > OPTIONS_MAX || options.some((option) => option.length > OPTION_MAX)) found.options = 'tracking.rule.optionsLong';
      else if (new Set(options).size !== options.length) found.options = 'tracking.rule.optionsTwice';
    }
    // The type and autocomplete of the control are left as the API's defaults: the tracker reads the
    // real ones from the page and refuses the kinds it never collects (minimize.js).
    return { name, input_type: 'text', autocomplete: '', label: draft.label.trim(), data_class: draft.dataClass, options };
  });
  const invalid = errors.some((item) => Object.values(item).some(Boolean));
  return { fields: invalid ? [] : fields, errors, error: null };
}

/** The drafts of the fields of a registered form, to change them. */
export const draftsOf = (fields: readonly FormField[]): FieldDraft[] =>
  fields.map((field) => ({
    name: field.name,
    label: field.label ?? '',
    dataClass: fieldClasses.find((item) => item === field.data_class) ?? 'form.code',
    options: (field.options ?? []).join('\n'),
  }));

/** A day as the API writes it (YYYY-MM-DD), in UTC like the counters. */
const isoDay = (moment: Date): string => moment.toISOString().slice(0, 10);

/** The last days up to today, both ends included. */
export function lastDays(days: number, now: number): { start: string; end: string } {
  const length = Math.min(Math.max(1, days), DIAGNOSTIC_DAYS_MAX);
  const end = new Date(now);
  const start = new Date(now - (length - 1) * 24 * 60 * 60 * 1000);
  return { start: isoDay(start), end: isoDay(end) };
}

export const channels = ['browser', 'server', 'webhook', 'consent', 'erasure', 'identity'] as const;
export const outcomes = ['accepted', 'duplicate', 'conflict', 'upgraded', 'rejected', 'suppressed', 'minimized'] as const;

/** The reasons that have a sentence. Any other reason is shown in the API's own word. */
export const knownReasons = [
  'new',
  'identical',
  'changed_content',
  'trusted_copy',
  'unknown_link',
  'subject_deleted',
  'consent_unknown',
  'consent_denied',
  'consent_withdrawn',
  'consent_expired',
  'nothing_granted',
  'unknown_form',
  'unknown_field',
  'signature_invalid',
  'signature_expired',
  'occurred_at_out_of_range',
  'invalid_payload',
  'sensitive_query_value',
] as const;

export function reasonMessage(reason: string): MessageId | null {
  const known = knownReasons.find((item) => item === reason);
  return known ? `tracking.reason.${known}` : null;
}

export function channelMessage(channel: string): MessageId | null {
  const known = channels.find((item) => item === channel);
  return known ? `tracking.channel.${known}` : null;
}

export function outcomeMessage(outcome: string): MessageId | null {
  const known = outcomes.find((item) => item === outcome);
  return known ? `tracking.outcome.${known}` : null;
}

/** How the outcomes add up in the summary: what was kept, refused, held back for consent, or trimmed. */
export function summarize(rows: ReadonlyArray<{ outcome: string; count: number }>): Record<'kept' | 'refused' | 'withoutConsent' | 'trimmed', number> {
  const total = { kept: 0, refused: 0, withoutConsent: 0, trimmed: 0 };
  for (const row of rows) {
    if (row.outcome === 'accepted' || row.outcome === 'upgraded') total.kept += row.count;
    else if (row.outcome === 'rejected' || row.outcome === 'conflict') total.refused += row.count;
    else if (row.outcome === 'suppressed') total.withoutConsent += row.count;
    else if (row.outcome === 'minimized') total.trimmed += row.count;
  }
  return total;
}

/** The code a website installs for a browser source. Nothing in it is secret. */
export function installCode(collector: string, publicKey: string): string {
  return [
    `import { createTracker } from "/assets/tracker-${TRACKER_VERSION}/tracker.js";`,
    '',
    'const tracker = createTracker({',
    `  collector: "${collector}",`,
    `  publicKey: "${publicKey}",`,
    '});',
  ].join('\n');
}

export const erasureStates = [
  'received',
  'verifying',
  'accepted',
  'rejected',
  'paused_for_clarification',
  'on_hold',
  'in_progress',
  'completed',
  'partially_completed',
  'verified',
] as const;
export const requesterKinds = ['client_admin', 'agency_admin', 'provider_callback', 'platform_operator', 'consent_withdrawal', 'data_subject'] as const;
export const erasureTargets = ['collected_events', 'collection_subjects', 'consent_records', 'event_diagnostics', 'booking_links'] as const;

export const SUBJECT_TOKEN = /^sbj_[A-Za-z0-9_-]{43}$/;
export const EVENT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
