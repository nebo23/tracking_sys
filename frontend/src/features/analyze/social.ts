import type { SocialComparison, SocialReport, SocialRow, SocialTotal } from '@/api/reports';
import type { SeriesPoint } from '@/components/charts/SeriesChart';

import { addDays } from './range';

/** The daily stream of a social report: Instagram's account days or YouTube's channel days. */
export const dailyStreams = new Set(['account', 'channel_daily']);

/** The metrics of the daily stream that the report can total, in the API's order. */
export function dailyMetrics(report: SocialReport): string[] {
  const seen: string[] = [];
  for (const total of report.totals) {
    if (total.period === 'current' && dailyStreams.has(total.stream) && !seen.includes(total.metric)) seen.push(total.metric);
  }
  return seen;
}

export function totalOf(report: SocialReport, metric: string, period: 'current' | 'previous' = 'current'): SocialTotal | undefined {
  return report.totals.find((total) => total.period === period && total.metric === metric && dailyStreams.has(total.stream));
}

export function comparisonOf(report: SocialReport, metric: string): SocialComparison | undefined {
  return report.comparison?.find((item) => item.metric === metric && dailyStreams.has(item.stream));
}

/**
 * The days of one metric as a series. A day without an available value is a gap, never a zero:
 * its state goes to the table instead (D7 of the 018 entry review). A report holds the rows of its
 * own days only, so the previous period comes from its own report; its days line up with this
 * period's by their position.
 */
export function dailySeries(
  report: SocialReport,
  metric: string,
  gapWords: (row: SocialRow | undefined) => string,
  previous?: SocialReport,
): SeriesPoint[] {
  const rowsOf = (source: SocialReport) =>
    new Map(source.rows.filter((row) => row.metric === metric && dailyStreams.has(row.stream) && row.date).map((row) => [row.date as string, row]));
  const valueOf = (row: SocialRow | undefined) => (row && row.availability === 'available' && typeof row.value === 'number' ? row.value : null);
  const current = rowsOf(report);
  const before = previous ? rowsOf(previous) : null;
  const points: SeriesPoint[] = [];
  for (let day = 0; day < report.period.days; day += 1) {
    const date = addDays(report.period.start, day);
    const row = current.get(date);
    const point: SeriesPoint = { date, current: valueOf(row) };
    if (point.current === null) point.gap = gapWords(row);
    if (previous && before) {
      const previousDate = addDays(previous.period.start, day);
      point.previousDate = previousDate;
      point.previous = valueOf(before.get(previousDate));
    }
    points.push(point);
  }
  return points;
}

/** One published item of a content cohort with its lifetime values, per metric. */
export interface ContentItem {
  id: string;
  stream: string;
  productType: string | null;
  publishedDate: string | null;
  values: Map<string, SocialRow>;
}

export function contentItems(report: SocialReport): ContentItem[] {
  const items = new Map<string, ContentItem>();
  for (const row of report.rows) {
    if (!row.content_id) continue;
    const key = `${row.stream}:${row.content_id}`;
    let item = items.get(key);
    if (!item) {
      item = { id: row.content_id, stream: row.stream, productType: row.product_type ?? null, publishedDate: row.published_date ?? null, values: new Map() };
      items.set(key, item);
    }
    item.values.set(row.metric, row);
  }
  return [...items.values()].sort((a, b) => (b.publishedDate ?? '').localeCompare(a.publishedDate ?? '') || a.id.localeCompare(b.id));
}

/** The metrics a content cohort shows as columns: those of its totals, at most four. */
export function cohortMetrics(report: SocialReport): string[] {
  const order = ['views', 'reach', 'total_interactions', 'likes', 'comments', 'shares', 'engagedViews', 'estimatedMinutesWatched'];
  const present = new Set(report.totals.map((total) => total.metric));
  return order.filter((metric) => present.has(metric)).slice(0, 4);
}
