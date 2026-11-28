import { useQuery } from '@tanstack/react-query';
import { useIntl } from 'react-intl';

import { modelVersionsQuery, type ReportFamily } from '@/api/reports';
import { previousRange } from '@/features/analyze/range';
import type { MessageId } from '@/i18n';

import { lastDay } from './rules';

type Parameters = Readonly<Record<string, unknown>>;

const text = (parameters: Parameters, key: string): string | undefined => {
  const value = parameters[key];
  return typeof value === 'string' ? value : undefined;
};

/** A report and its main choice in words, such as "Ad spend by campaign" (the API's defaults apply). */
export function reportNameId(family: ReportFamily, parameters: Parameters): MessageId {
  switch (family) {
    case 'social':
      return text(parameters, 'view') === 'content_cohort' ? 'reports.name.social.content_cohort' : 'reports.name.social.daily';
    case 'spend':
      return `reports.name.spend.${text(parameters, 'level') ?? 'ad'}` as MessageId;
    case 'revenue':
      return 'reports.name.revenue';
    case 'attribution':
      return text(parameters, 'view') === 'models'
        ? 'reports.name.attribution.models'
        : (`reports.name.attribution.${text(parameters, 'group_by') ?? 'campaign'}` as MessageId);
    case 'funnel':
      return `reports.name.funnel.${text(parameters, 'group_by') ?? 'campaign'}` as MessageId;
    case 'roas':
      return `reports.name.roas.${text(parameters, 'level') ?? 'ad'}` as MessageId;
  }
}

/** Days written as a range, the last day included: `end` is the day after the period. */
export function usePeriodText(): (start: string, end: string) => string {
  const intl = useIntl();
  return (start, end) =>
    intl.formatDateTimeRange(new Date(`${start}T00:00:00Z`), new Date(`${lastDay(end)}T00:00:00Z`), {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    });
}

/** The days a comparison reads: the same number of days just before. */
export const previousPeriod = (start: string, end: string) => previousRange({ start, end });

/** The name of the model version a report names, from the client's versions the page already read. */
export function useModelLabel(agencyId: string, clientId: string, modelVersion: unknown): string | null {
  const intl = useIntl();
  const models = useQuery({ ...modelVersionsQuery(agencyId, clientId), enabled: typeof modelVersion === 'string' });
  if (typeof modelVersion !== 'string') return null;
  const version = models.data?.versions.find((item) => item.id === modelVersion);
  return version ? intl.formatMessage({ id: `attribution.model.${version.model}` }) : null;
}
