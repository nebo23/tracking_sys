import type { StreamCoverage } from '@/api/connections';
import type { MessageId } from '@/i18n';

const DAY = 24 * 60 * 60 * 1000;

/** Where a stream's stored range lies inside the history the provider offers, in percent of that window. */
export function coverageBar(stream: StreamCoverage, now: number): { start: number; size: number } | null {
  if (!stream.covered_from || !stream.complete_through) return null;
  const from = new Date(stream.covered_from).getTime();
  const through = new Date(stream.complete_through).getTime();
  const windowStart = Math.min(from, now - Math.max(1, stream.history_limit_days) * DAY);
  const span = now - windowStart;
  if (span <= 0 || through < from) return null;
  const clamp = (value: number) => Math.min(100, Math.max(0, value));
  const start = clamp(((from - windowStart) / span) * 100);
  const end = clamp(((through - windowStart) / span) * 100);
  // A range of a single day still shows as a sliver.
  return { start: Math.min(start, 98), size: Math.max(2, end - start) };
}

// The streams the adapters declare (backend/app/connectors). An unknown stream keeps its own name.
const streamNames: Partial<Record<string, MessageId>> = {
  account: 'connections.stream.account',
  media: 'connections.stream.media',
  stories: 'connections.stream.stories',
  channel: 'connections.stream.channel',
  channel_daily: 'connections.stream.channel_daily',
  videos: 'connections.stream.videos',
  video_totals: 'connections.stream.video_totals',
  ad_objects: 'connections.stream.ad_objects',
  ad_daily: 'connections.stream.ad_daily',
  // The stand-in provider's one stream.
  objects: 'connections.stream.objects',
};

export const streamName = (stream: string): MessageId | null => streamNames[stream] ?? null;

// A provider with several daily limits names each one (specification 011: the two YouTube APIs).
const allowanceNames: Partial<Record<string, MessageId>> = {
  youtube_data: 'connections.allowance.youtube_data',
  youtube_analytics: 'connections.allowance.youtube_analytics',
};

export const allowanceName = (bucket: string): MessageId | null => allowanceNames[bucket] ?? null;

// Why the latest run waits or failed (the run's error kind). Anything else gets the general sentence.
const runReasons: Partial<Record<string, MessageId>> = {
  rate_limited: 'connections.run.reason.rate_limited',
  retryable: 'connections.run.reason.retryable',
  budget_exhausted: 'connections.run.reason.budget_exhausted',
  forbidden: 'connections.run.reason.forbidden',
  unauthorized: 'connections.run.reason.unauthorized',
  permanent: 'connections.run.reason.permanent',
  client_rejected: 'connections.run.reason.permanent',
};

export const runReason = (reason: string | null): MessageId | null => (reason ? (runReasons[reason] ?? null) : null);

// Why a connection stopped working or is being removed (the connection's status reason).
const statusReasons: Partial<Record<string, MessageId>> = {
  credential_expired: 'connections.reason.credential_expired',
  provider_revoked: 'connections.reason.provider_revoked',
  user_requested: 'connections.reason.user_requested',
  deauthorized: 'connections.reason.deauthorized',
  deletion_requested: 'connections.reason.deletion_requested',
  authorization_lost: 'connections.reason.authorization_lost',
  operator_purged: 'connections.reason.operator_purged',
};

export const statusReason = (reason: string | null, fallback: MessageId): MessageId => (reason ? (statusReasons[reason] ?? fallback) : fallback);
