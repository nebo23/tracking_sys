import type { ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { Badge } from '@/components/Badge';
import { Icon } from '@/components/Icon';
import { RelativeTime } from '@/components/Time';
import type { MessageId } from '@/i18n';
import { cx } from '@/lib/cx';

import { comparisonReason, freshnessState, totalReason } from './states';

// The metrics of the 016-A catalog (backend/app/reporting/catalog.py), named for people. A unit
// test compares this list with the catalog; a metric without a name is shown by its API name.
export const metricNames = [
  'views',
  'total_interactions',
  'likes',
  'comments',
  'shares',
  'saves',
  'saved',
  'replies',
  'profile_links_taps',
  'reach',
  'accounts_engaged',
  'profile_visits',
  'follows',
  'navigation',
  'ig_reels_video_view_total_time',
  'ig_reels_avg_watch_time',
  'reels_skip_rate',
  'engagedViews',
  'estimatedMinutesWatched',
  'dislikes',
  'subscribersGained',
  'subscribersLost',
  'videosAddedToPlaylists',
  'videosRemovedFromPlaylists',
  'averageViewDuration',
  'averageViewPercentage',
] as const;

export function useMetricName(): (metric: string) => string {
  const intl = useIntl();
  return (metric) =>
    (metricNames as readonly string[]).includes(metric) ? intl.formatMessage({ id: `analyze.metric.${metric}` as MessageId }) : metric;
}

/** A count as the reports state it: whole numbers with the separators of the language. */
export function useCount(): (value: number) => string {
  const intl = useIntl();
  return (value) => intl.formatNumber(value, { maximumFractionDigits: 2 });
}

interface StatProps {
  label: ReactNode;
  /** A state beside the label, such as stale or partial. */
  badge?: ReactNode;
  value: ReactNode;
  rows?: ReactNode;
  meta: ReactNode;
}

/** One key figure (C01): its label, its value or why there is none, and where it comes from. */
export function Stat({ label, badge, value, rows, meta }: StatProps) {
  return (
    <article className="c-card c-stat">
      <p className="c-stat__label">
        {label} {badge}
      </p>
      <div className="c-stat__value">{value}</div>
      {rows}
      <p className="c-stat__meta">{meta}</p>
    </article>
  );
}

/** A total's status, when it is not simply complete: a labeled subtotal or no value, with the reason. */
export function TotalState({ status, reason }: { status: string; reason: string | null | undefined }) {
  if (status === 'complete') return null;
  return (
    <span className="a-state">
      <Badge tone={status === 'partial' ? 'warning' : 'neutral'} icon={status === 'partial' ? 'circle-dashed' : 'circle-slash'}>
        <FormattedMessage id={status === 'partial' ? 'analyze.status.partial' : 'analyze.status.unavailable'} />
      </Badge>{' '}
      <span className="u-secondary">
        <FormattedMessage id={totalReason(reason)} />
      </span>
    </span>
  );
}

export function ProvisionalBadge() {
  return (
    <Badge tone="info" icon="hourglass">
      <FormattedMessage id="analyze.provisional" />
    </Badge>
  );
}

/** How recent a source's data is; stale and never-synced sources are said so. */
export function FreshnessBadge({ state }: { state: string | null | undefined }) {
  const tone = state === 'fresh' ? 'success' : state === 'stale' ? 'warning' : 'neutral';
  const icon = state === 'fresh' ? 'circle-check' : state === 'stale' ? 'clock' : 'circle-dashed';
  return (
    <Badge tone={tone} icon={icon}>
      <FormattedMessage id={freshnessState(state)} />
    </Badge>
  );
}

interface ChangeProps {
  comparable: boolean;
  percent: string | null;
  /** The difference as a number, to tell a rise from a fall. */
  difference: number | null;
  reason: string | null | undefined;
  /** Whether a rise is good news (views, revenue) or neither (spend). */
  rising?: 'good' | 'neutral';
}

/** The change against the previous period, or why the two periods are not compared. */
export function Change({ comparable, percent, difference, reason, rising = 'good' }: ChangeProps) {
  if (!comparable || percent === null) {
    return (
      <p className="c-stat__row u-secondary">
        <FormattedMessage id={comparable ? 'analyze.compare.zero_baseline' : comparisonReason(reason)} />
      </p>
    );
  }
  const up = (difference ?? 0) > 0;
  const down = (difference ?? 0) < 0;
  const tone = rising === 'neutral' || (!up && !down) ? null : up ? 'good' : 'bad';
  return (
    <p className="c-stat__row">
      <span className={cx('c-delta', tone && `c-delta--${tone}`)}>
        {up || down ? <Icon name={up ? 'arrow-up-right' : 'arrow-down-right'} size="sm" /> : null}
        <span className="u-num">{percent}</span>
      </span>
      <span>
        <FormattedMessage id="analyze.compare.against" />
      </span>
    </p>
  );
}

/** Where a figure comes from: the source, its day, and its last synchronization. */
export function SourceMeta({ source, dayZone, synced }: { source: ReactNode; dayZone: string | null | undefined; synced?: string | null }) {
  return (
    <span className="a-source">
      <span>{source}</span>
      {dayZone ? (
        <span>
          <FormattedMessage id="analyze.dayZone" values={{ zone: dayZone }} />
        </span>
      ) : null}
      {synced ? (
        <span>
          <FormattedMessage id="analyze.synced" values={{ when: <RelativeTime value={synced} /> }} />
        </span>
      ) : synced === null ? (
        <span>
          <FormattedMessage id="analyze.neverSynced" />
        </span>
      ) : null}
    </span>
  );
}

/** A value that cannot be shown as a number, said in words instead. */
export function NoValue({ children }: { children: ReactNode }) {
  return <span className="a-novalue">{children}</span>;
}

export function Card({ title, subtitle, actions, children, footer, flush = false }: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  flush?: boolean;
}) {
  return (
    <article className="c-card">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title">{title}</h2>
          {subtitle ? <p className="c-card__subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="l-cluster">{actions}</div> : null}
      </div>
      <div className={cx('c-card__body', flush ? 'c-card__body--flush' : 'l-stack')}>{children}</div>
      {footer ? <div className="c-card__footer">{footer}</div> : null}
    </article>
  );
}
