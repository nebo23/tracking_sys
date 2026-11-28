import type { ReportExport, ReportSchedule } from '@/api/reportDelivery';
import type { ReportFamily } from '@/api/reports';
import type { Member } from '@/api/team';
import type { MessageId } from '@/i18n';

// The rules of retained exports and scheduled reports (016-C), as the API applies them. Unit
// tests read the same numbers and codes in backend/app/services/report_exports.py,
// report_schedules.py and reporting.py.

/** Unexpired exports a client may keep (EXPORT_LIMIT). */
export const EXPORT_LIMIT = 50;
/** Active schedules of a client (ACTIVE_LIMIT). */
export const SCHEDULE_LIMIT = 10;
/** Recipients of one schedule (RECIPIENT_LIMIT). */
export const RECIPIENT_LIMIT = 20;
/** Characters of a schedule's name. */
export const NAME_LIMIT = 100;

export const families = ['social', 'spend', 'revenue', 'attribution', 'roas', 'funnel'] as const satisfies readonly ReportFamily[];

/** The permission each report needs (PERMISSIONS); the others need client access only. */
const financeFamilies = new Set<ReportFamily>(['spend', 'revenue', 'roas']);
/** Families whose sale values need financial access on top of client access (FINANCE_SPLIT). */
export const saleValueFamilies = new Set<ReportFamily>(['attribution', 'funnel']);
/** Families read from one connected account. */
export const connectionFamilies = new Set<ReportFamily>(['social', 'spend', 'roas']);

/** Whether a report needs financial access: by its family, or because it holds sale values. */
export function needsFinance(family: ReportFamily, saleValues: boolean): boolean {
  return financeFamilies.has(family) || (saleValueFamilies.has(family) && saleValues);
}

/**
 * Whether a member may receive a schedule of this report: the API refuses anyone else
 * (invalid_recipient). Owners and admins read every client; others need a grant of the client,
 * with financial access when the report needs it.
 */
export function mayReceive(member: Member, clientId: string, family: ReportFamily, saleValues: boolean): boolean {
  if (member.status !== 'active' || member.account !== 'active') return false;
  if (member.role === 'owner' || member.role === 'admin') return true;
  const grant = member.clients.find((item) => item.client_id === clientId);
  if (!grant) return false;
  return !needsFinance(family, saleValues) || grant.can_view_financials;
}

/** Why an export is no longer available, each in words (revoked_reason, or expiry). */
export const goneReasons = {
  manual: 'reports.gone.manual',
  erasure: 'reports.gone.erasure',
  disconnection: 'reports.gone.disconnection',
  connection_purged: 'reports.gone.connection_purged',
  client_archived: 'reports.gone.client_archived',
  expired: 'reports.gone.expired',
} as const satisfies Record<NonNullable<ReportExport['revoked_reason']> | 'expired', MessageId>;

export const pauseReasons = {
  manual: 'reports.pause.manual',
  owner_access_lost: 'reports.pause.owner_access_lost',
  repeated_failures: 'reports.pause.repeated_failures',
} as const satisfies Record<NonNullable<ReportSchedule['pause_reason']>, MessageId>;

/** The closed codes of a failed run (RUN_ERRORS, and build_failed for anything else). */
export const runErrors = {
  report_changed: 'reports.run.report_changed',
  report_too_large: 'reports.run.report_too_large',
  source_unavailable: 'reports.run.source_unavailable',
  source_not_ready: 'reports.run.source_not_ready',
  not_configured: 'reports.run.not_configured',
  export_limit_reached: 'reports.run.export_limit_reached',
  export_refused: 'reports.run.export_refused',
  build_failed: 'reports.run.build_failed',
} as const satisfies Record<string, MessageId>;

export const runError = (code: string | null): MessageId => runErrors[(code ?? 'build_failed') as keyof typeof runErrors] ?? runErrors.build_failed;

/** The state of an export as the list shows it. */
export function exportGone(item: ReportExport): keyof typeof goneReasons | null {
  if (item.status === 'expired') return 'expired';
  if (item.status === 'revoked') return item.revoked_reason ?? 'manual';
  return null;
}

/** Whole days until an export is deleted, never below zero. */
export function daysLeft(expiresAt: string, now: Date = new Date()): number {
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now.getTime()) / 86_400_000));
}

/** How many exports the client keeps now: those that are ready and unexpired count toward the limit. */
export const keptExports = (items: readonly ReportExport[]): number => items.filter((item) => item.status === 'ready').length;

/** The last day of a period: `end` is the first day after it. */
export function lastDay(end: string): string {
  const day = new Date(`${end}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

export const cadences = ['daily', 'weekly', 'monthly'] as const;
export type Cadence = (typeof cadences)[number];

/** What a run reports, by cadence (D8): the day before, the 7 days before, or the previous month. */
export const cadencePeriods = {
  daily: 'reports.cadence.daily.period',
  weekly: 'reports.cadence.weekly.period',
  monthly: 'reports.cadence.monthly.period',
} as const satisfies Record<Cadence, MessageId>;

/** The name of a schedule: 1 to 100 characters without control characters, as the API checks. */
export function scheduleNameProblem(value: string): 'required' | 'too_long' | 'invalid' | null {
  const trimmed = value.trim();
  if (trimmed === '') return 'required';
  if ([...trimmed].length > NAME_LIMIT) return 'too_long';
  for (const character of trimmed) {
    const code = character.codePointAt(0) ?? 0;
    if (code < 0x20 || code === 0x7f) return 'invalid';
  }
  return null;
}

/** The time zone of this browser, which a new schedule starts with. */
export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** The time zones a schedule can name (IANA), with UTC and the browser's own always among them. */
export function timeZones(): string[] {
  const listed = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
  return [...new Set(['UTC', browserZone(), ...listed])];
}
