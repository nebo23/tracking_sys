import type { ReportRange } from '@/api/reports';

/** The longest range a report accepts (016-A, "Parameters"). */
export const MAX_DAYS = 31;

/** The ranges a person can pick. Each ends on the last complete day. */
export const presets = ['last7', 'last28', 'last30', 'month'] as const;
export type Preset = (typeof presets)[number];
export const DEFAULT_PRESET: Preset = 'last30';

/** Days in the address: both are included, as a person reads a range. */
export interface DayRange {
  from: string;
  to: string;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** A real calendar date in the ISO form, or false. */
export function isDate(value: unknown): value is string {
  if (typeof value !== 'string' || !DATE.test(value)) return false;
  const moment = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(moment.getTime()) && moment.toISOString().slice(0, 10) === value;
}

export function addDays(date: string, days: number): string {
  const moment = new Date(`${date}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + days);
  return moment.toISOString().slice(0, 10);
}

/** The number of days of a range, both ends included. */
export function daysIn(range: DayRange): number {
  return Math.round((Date.parse(`${range.to}T00:00:00Z`) - Date.parse(`${range.from}T00:00:00Z`)) / 86_400_000) + 1;
}

/**
 * The last day that has ended in UTC: yesterday. Later days are still being collected, and only
 * a range of ended days can be compared (D10 of the 018 entry review). Sources whose day ends
 * later than UTC's mark their late values as provisional themselves.
 */
export function lastCompleteDay(now: Date = new Date()): string {
  return addDays(now.toISOString().slice(0, 10), -1);
}

export function presetRange(preset: Preset, now: Date = new Date()): DayRange {
  const to = lastCompleteDay(now);
  if (preset === 'month') return { from: `${to.slice(0, 8)}01`, to };
  const length = { last7: 7, last28: 28, last30: 30 }[preset];
  return { from: addDays(to, -(length - 1)), to };
}

/** The preset a range is, or null for a range of the person's own choosing. */
export function presetOf(range: DayRange, now: Date = new Date()): Preset | null {
  return presets.find((preset) => {
    const candidate = presetRange(preset, now);
    return candidate.from === range.from && candidate.to === range.to;
  }) ?? null;
}

/** Why a range of the person's own choosing cannot be asked for, or null when it can. */
export function rangeProblem(range: DayRange, now: Date = new Date()): 'order' | 'length' | 'future' | null {
  if (range.from > range.to) return 'order';
  if (daysIn(range) > MAX_DAYS) return 'length';
  if (range.to > lastCompleteDay(now)) return 'future';
  return null;
}

/**
 * The range an address asks for. A missing, malformed, reversed, too long or unfinished range
 * gives the default, so a shared address never asks the API for days that have not ended.
 */
export function rangeFromSearch(search: { from?: unknown; to?: unknown }, now: Date = new Date()): DayRange {
  if (isDate(search.from) && isDate(search.to)) {
    const range = { from: search.from, to: search.to };
    if (rangeProblem(range, now) === null) return range;
  }
  return presetRange(DEFAULT_PRESET, now);
}

/** The period of equal length that ends where a range starts, as the API compares (016-A). */
export function previousRange(range: ReportRange): ReportRange {
  const days = Math.round((Date.parse(`${range.end}T00:00:00Z`) - Date.parse(`${range.start}T00:00:00Z`)) / 86_400_000);
  return { start: addDays(range.start, -days), end: range.start };
}

/** The same days as the API reads them: `end` is the day after the last one. */
export function toReportRange(range: DayRange): ReportRange {
  return { start: range.from, end: addDays(range.to, 1) };
}
