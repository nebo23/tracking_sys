import { useMutation, useQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { FormattedMessage, useIntl, type IntlShape } from 'react-intl';

import { connectionsQuery, type Connection } from '@/api/connections';
import { describeError, isApiError, type ErrorMessage } from '@/api/errors';
import { reportCsv, type Amount, type ReportFamily, type ReportScope } from '@/api/reports';
import { InlineSelect } from '@/components/Choice';
import { Icon } from '@/components/Icon';
import { ErrorNotice, Notice } from '@/components/Notice';
import { PageHeading } from '@/components/PageHeading';

import { daysIn, endsToday, isDate, presetOf, presetRange, presets, rangeFromSearch, rangeProblem, toReportRange, type DayRange, type Preset } from './range';
import type { AnalyzeSearch } from './search';

// ------------------------------------------------------------------ The address --

export { analyzeSearch, type AnalyzeSearch } from './search';

export interface AnalyzeState {
  range: DayRange;
  scope: ReportScope;
}

/** The days and the comparison of a page, from its address and the person's client. */
export function reportScope(agencyId: string, clientId: string, search: AnalyzeSearch, now: Date = new Date()): AnalyzeState {
  const range = rangeFromSearch(search, now);
  return { range, scope: { agencyId, clientId, range: toReportRange(range), compare: search.compare === true } };
}

// ------------------------------------------------------------------- Connections --

const socialProviders = new Set(['instagram', 'youtube', 'synthetic_instagram', 'synthetic_youtube']);
const spendProviders = new Set(['meta_ads', 'synthetic_meta_ads']);

const readable = (connection: Connection) => connection.status === 'active' || connection.status === 'reconnect_required';

/** The client's social accounts that a report can read: Instagram and YouTube. */
export function useSocialConnections(agencyId: string, clientId: string) {
  return useQuery({
    ...connectionsQuery(agencyId, clientId),
    select: (connections) => connections.filter((connection) => socialProviders.has(connection.provider) && readable(connection)),
  });
}

/** The client's advertising accounts whose spend a report can read. */
export function useSpendConnections(agencyId: string, clientId: string) {
  return useQuery({
    ...connectionsQuery(agencyId, clientId),
    select: (connections) => connections.filter((connection) => spendProviders.has(connection.provider) && readable(connection)),
  });
}

/** The connection the address names when it is one of these, otherwise the first. */
export function chosenConnection(connections: readonly Connection[] | undefined, chosen: string | undefined): Connection | undefined {
  return connections?.find((connection) => connection.id === chosen) ?? connections?.[0];
}

/** A connection as a person knows it: its provider and the account's own label. */
export function accountName(connection: Connection, intl: IntlShape): string {
  const provider = intl.formatMessage({ id: `provider.${connection.provider}` as never });
  const account = connection.account?.label ?? connection.account?.external_account_id;
  return account ? `${provider} (${account})` : provider;
}

// -------------------------------------------------------------------------- Money --

/**
 * An amount as the API states it: its decimal text in its currency, formatted, never recomputed
 * through a floating-point number (016-A, "Answer").
 */
export function money(intl: IntlShape, amount: Amount | null | undefined, currency: string, exponent: number): string {
  if (!amount) return '';
  try {
    const format = new Intl.NumberFormat(intl.locale, {
      style: 'currency',
      currency,
      minimumFractionDigits: exponent,
      maximumFractionDigits: exponent,
      numberingSystem: 'latn',
    });
    // Intl formats a decimal string exactly; the type definitions only name numbers.
    return format.format(amount.decimal as unknown as number);
  } catch {
    return `${amount.decimal} ${currency}`;
  }
}

/** A percentage the API computed, with its sign. */
export function percent(intl: IntlShape, text: string | null | undefined): string | null {
  if (text === null || text === undefined) return null;
  const value = Number(text);
  if (!Number.isFinite(value)) return null;
  return intl.formatNumber(value / 100, { style: 'percent', maximumFractionDigits: 2, signDisplay: 'exceptZero' });
}

// --------------------------------------------------------------- Financial access --

/**
 * Revenue and spend need financial access (016-A). The interface cannot know a member's financial
 * flag before asking, so a refusal of a financial report is said in words and no amount is shown.
 */
export const financeRefused = (error: unknown): boolean => isApiError(error) && error.status === 403;

export function FinanceNotice() {
  return (
    <Notice tone="info">
      <FormattedMessage id="analyze.finance.refused" />
    </Notice>
  );
}

// ----------------------------------------------------------------- The page head --

interface AnalyzeHeadProps {
  title: ReactNode;
  lead: ReactNode;
  range: DayRange;
  compare: boolean;
  /** False where the page has no comparison, as for a content cohort. */
  comparable?: boolean;
  onRange: (range: DayRange) => void;
  onCompare: (compare: boolean) => void;
  csv?: { scope: ReportScope; family: ReportFamily; parameters: Record<string, string>; name: string } | null;
  children?: ReactNode;
}

/** The head of an Analyze page: its title, the days it covers, the comparison and the CSV. */
export function AnalyzeHead({ title, lead, range, compare, comparable = true, onRange, onCompare, csv, children }: AnalyzeHeadProps) {
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const download = useMutation({
    mutationFn: async () => {
      if (!csv) return;
      saveFile(await reportCsv(csv.scope, csv.family, csv.parameters), csv.name);
    },
    onMutate: () => setProblem(null),
    onError: (error) => setProblem(describeError(error)),
  });

  return (
    <>
      <div className="c-pagehead">
        <div>
          <PageHeading>{title}</PageHeading>
          <p className="c-pagehead__lead">{lead}</p>
        </div>
        <div className="l-cluster">
          {children}
          <RangeChoice range={range} onChange={onRange} />
          {comparable ? (
            <label className="c-choice">
              <input className="c-switch" type="checkbox" checked={compare} onChange={(event) => onCompare(event.target.checked)} />
              <span>
                <FormattedMessage id="analyze.compare" />
              </span>
            </label>
          ) : null}
          {csv ? (
            <button type="button" className="c-btn c-btn--secondary" disabled={download.isPending} onClick={() => download.mutate()}>
              <Icon name="download" size="sm" />
              <FormattedMessage id="analyze.csv" />
            </button>
          ) : null}
        </div>
      </div>
      <ErrorNotice message={problem} />
      {endsToday(range) ? (
        <Notice tone="info">
          <FormattedMessage id="analyze.range.todayNotice" />
        </Notice>
      ) : null}
    </>
  );
}

/** Hands a file to the person's browser to keep. */
export function saveFile(file: Blob, name: string): void {
  const address = URL.createObjectURL(file);
  const anchor = document.createElement('a');
  anchor.href = address;
  anchor.download = name;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(address);
}

type RangeOption = Preset | 'custom';

/** The days of a page: a range that ends on the last complete day, or one of the person's own. */
export function RangeChoice({ range, onChange }: { range: DayRange; onChange: (range: DayRange) => void }) {
  const intl = useIntl();
  const preset = presetOf(range);
  const [custom, setCustom] = useState(preset === null);
  const [draft, setDraft] = useState<DayRange>(range);
  const problem = rangeProblem(draft);
  const options = [...presets, 'custom' as const].map((value) => ({
    value,
    label: intl.formatMessage({ id: `analyze.range.${value}` }),
  }));
  const choose = (value: RangeOption) => {
    if (value === 'custom') {
      setDraft(range);
      setCustom(true);
      return;
    }
    setCustom(false);
    onChange(presetRange(value));
  };
  const days = intl.formatDateTimeRange(new Date(`${range.from}T00:00:00Z`), new Date(`${range.to}T00:00:00Z`), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });

  return (
    <div className="a-range l-cluster">
      <InlineSelect<RangeOption> label={intl.formatMessage({ id: 'analyze.range.label' })} value={custom ? 'custom' : (preset ?? 'custom')} onChange={choose} options={options} />
      <span className="u-secondary u-num">{days}</span>
      {custom ? (
        <form
          className="l-cluster"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (problem === null) onChange(draft);
          }}
        >
          <label className="a-range__field">
            <span className="u-sr">
              <FormattedMessage id="analyze.range.from" />
            </span>
            <input
              className="c-input"
              type="date"
              value={draft.from}
              max={draft.to}
              onChange={(event) => setDraft((current) => ({ ...current, from: event.target.value }))}
              aria-invalid={problem !== null || undefined}
            />
          </label>
          <label className="a-range__field">
            <span className="u-sr">
              <FormattedMessage id="analyze.range.to" />
            </span>
            <input
              className="c-input"
              type="date"
              value={draft.to}
              min={draft.from}
              onChange={(event) => setDraft((current) => ({ ...current, to: event.target.value }))}
              aria-invalid={problem !== null || undefined}
            />
          </label>
          <button type="submit" className="c-btn c-btn--secondary c-btn--sm" disabled={problem !== null}>
            <FormattedMessage id="analyze.range.apply" />
          </button>
          {problem && isDate(draft.from) && isDate(draft.to) ? (
            <span className="c-field__error" role="status">
              <FormattedMessage id={`analyze.range.problem.${problem}`} values={{ days: daysIn(draft) }} />
            </span>
          ) : null}
        </form>
      ) : null}
    </div>
  );
}
