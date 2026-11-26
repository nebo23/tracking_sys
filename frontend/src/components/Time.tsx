import { FormattedDate, useIntl } from 'react-intl';

// A day with its month as a word, so that it reads the same way in both directions:
// "Nov 26, 2026" and "26 نوفمبر 2026". A day written in digits alone is ambiguous beside Arabic text.
export const dayFormat = { day: 'numeric', month: 'short', year: 'numeric' } as const;

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

type Unit = 'second' | 'minute' | 'hour' | 'day' | 'month' | 'year';

/** The largest unit in which a span of time is at least one, as a person would say it. */
export function relativeParts(from: number, to: number): { value: number; unit: Unit } {
  const seconds = Math.round((to - from) / 1000);
  const span = Math.abs(seconds);
  if (span < MINUTE) return { value: 0, unit: 'second' };
  if (span < HOUR) return { value: Math.trunc(seconds / MINUTE), unit: 'minute' };
  if (span < DAY) return { value: Math.trunc(seconds / HOUR), unit: 'hour' };
  if (span < 30 * DAY) return { value: Math.trunc(seconds / DAY), unit: 'day' };
  if (span < 365 * DAY) return { value: Math.trunc(seconds / (30 * DAY)), unit: 'month' };
  return { value: Math.trunc(seconds / (365 * DAY)), unit: 'year' };
}

/** A moment said as its distance from now ("3 hours ago"), with the exact time for whoever asks. */
export function RelativeTime({ value }: { value: string }) {
  const intl = useIntl();
  const moment = new Date(value);
  const { value: amount, unit } = relativeParts(Date.now(), moment.getTime());
  const exact = intl.formatDate(moment, { ...dayFormat, hour: 'numeric', minute: '2-digit' });
  return (
    <time dateTime={value} title={exact}>
      {intl.formatRelativeTime(amount, unit, { numeric: 'auto' })}
    </time>
  );
}

/** A day, written out in the language of the interface. */
export function Day({ value }: { value: string }) {
  return (
    <time dateTime={value} className="a-nowrap">
      <FormattedDate value={value} {...dayFormat} />
    </time>
  );
}

/** A day and the time of day. */
export function Moment({ value }: { value: string }) {
  return (
    <time dateTime={value} className="a-nowrap">
      <FormattedDate value={value} {...dayFormat} hour="numeric" minute="2-digit" />
    </time>
  );
}
