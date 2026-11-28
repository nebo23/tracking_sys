import type { ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import type { AttributionReport, ModelVersion } from '@/api/reports';
import { InlineSelect } from '@/components/Choice';
import { Notice } from '@/components/Notice';
import { RelativeTime } from '@/components/Time';

import { NoValue } from '../analyze/parts';
import type { AttributionGroupChoice } from '../analyze/search';
import { money } from '../analyze/shared';
import { attributionReason, freshnessBanners } from './states';

/** The active versions of a client's models, its default first (D6: "the client's default first"). */
export function orderedVersions(versions: readonly ModelVersion[] | undefined): ModelVersion[] {
  return [...(versions ?? [])].filter((version) => version.status === 'active').sort((a, b) => Number(b.is_default) - Number(a.is_default));
}

export function useModelName(): (version: Pick<ModelVersion, 'model'>) => string {
  const intl = useIntl();
  return (version) => intl.formatMessage({ id: `attribution.model.${version.model}` });
}

/** The model a report is read under, chosen from the client's active versions. */
export function ModelChoice({ versions, chosen, onChange }: { versions: ModelVersion[]; chosen: ModelVersion | undefined; onChange: (id: string) => void }) {
  const intl = useIntl();
  const name = useModelName();
  const fallback = versions.find((version) => version.is_default);
  if (!chosen) return null;
  return (
    <div className="l-cluster a-models">
      <InlineSelect
        label={intl.formatMessage({ id: 'attribution.model.label' })}
        value={chosen.id}
        onChange={onChange}
        options={versions.map((version) => ({
          value: version.id,
          label: name(version),
          hint: intl.formatMessage({ id: 'attribution.model.window' }, { days: version.window_days }),
        }))}
      />
      <span className="u-secondary">
        <FormattedMessage
          id="attribution.model.lead"
          values={{ days: chosen.window_days, model: fallback ? name(fallback) : name(chosen) }}
        />
      </span>
    </div>
  );
}

type Freshness = Pick<AttributionReport, 'attribution' | 'values'>;

/**
 * What stands between the stored credit and the conversions: a calculation that has not run yet,
 * is behind, is being rebuilt or failed. Values from a published generation stay readable.
 */
export function FreshnessNotice({ report }: { report: Freshness }) {
  const state = report.attribution.state;
  if (report.values.state === 'not_ready') {
    return (
      <Notice tone="info">
        <FormattedMessage id={attributionReason(report.values.reason)} />
      </Notice>
    );
  }
  if (state === 'caught_up') return null;
  return (
    <Notice
      tone={state === 'failed' ? 'danger' : 'warning'}
      action={
        report.attribution.published_at ? (
          <span className="u-secondary">
            <FormattedMessage id="attribution.freshness.published" values={{ when: <RelativeTime value={report.attribution.published_at} /> }} />
          </span>
        ) : undefined
      }
    >
      <FormattedMessage id={freshnessBanners[state]} />
    </Notice>
  );
}

/** Each currency's amount on its own line; amounts in different currencies are never added. */
export function Amounts({ items }: { items: ReadonlyArray<{ currency: string; exponent: number; amount: { minor: number; decimal: string } | null | undefined }> }) {
  const intl = useIntl();
  if (items.length === 0) return <NoValue>{intl.formatMessage({ id: 'attribution.none' })}</NoValue>;
  return (
    <>
      {items.map((item) => (
        <span key={item.currency} className="a-stat__line u-num">
          {money(intl, item.amount, item.currency, item.exponent)}
        </span>
      ))}
    </>
  );
}

/** The words for a value hidden for want of financial access. */
export function NeedsFinance() {
  const intl = useIntl();
  return <NoValue>{intl.formatMessage({ id: 'analyze.finance.short' })}</NoValue>;
}

/** A group of credit as a person knows it: its campaign, content or link, or direct and unknown. */
export function GroupName({
  recipient,
  groupRef,
  registered,
  group,
}: {
  recipient: 'campaign' | 'direct' | 'unknown';
  groupRef: string | null;
  registered: boolean | null;
  group: AttributionGroupChoice;
}): ReactNode {
  if (recipient !== 'campaign') {
    return (
      <>
        <span className="c-table__primary">
          <FormattedMessage id={`attribution.recipient.${recipient}`} />
        </span>
        <span className="c-table__sub">
          <FormattedMessage id={`attribution.recipient.${recipient}.lead`} />
        </span>
      </>
    );
  }
  return (
    <>
      <span className="c-table__primary u-ltr">{groupRef ?? <FormattedMessage id="attribution.group.noReference" />}</span>
      <span className="c-table__sub">
        <FormattedMessage id={registered ? `attribution.group.registered.${group}` : `attribution.group.unregistered.${group}`} />
      </span>
    </>
  );
}
