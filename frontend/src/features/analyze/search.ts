import type { SpendLevel } from '@/api/reports';
import { isIdentifier } from '@/lib/identifier';

import { isDate } from './range';

/**
 * What an Analyze page keeps in its address, so a shared link opens the same view (section 4.4 of
 * the completion entry review). The router reads it without loading the pages themselves (D4).
 */
export interface AnalyzeSearch {
  from?: string;
  to?: string;
  compare?: boolean;
  connection?: string;
  metric?: string;
  level?: SpendLevel;
}

const levels: readonly SpendLevel[] = ['campaign', 'adset', 'ad'];

export function analyzeSearch(search: Record<string, unknown>): AnalyzeSearch {
  return {
    from: isDate(search.from) ? search.from : undefined,
    to: isDate(search.to) ? search.to : undefined,
    compare: search.compare === true || search.compare === 'true' ? true : undefined,
    connection: isIdentifier(search.connection) ? search.connection : undefined,
    metric: typeof search.metric === 'string' && /^[A-Za-z_]{1,64}$/.test(search.metric) ? search.metric : undefined,
    level: levels.find((level) => level === search.level),
  };
}

/** The tabs of the Attribution page (D6 of the completion entry review); the first is the default. */
export const attributionTabs = ['credit', 'funnel', 'roas'] as const;
export type AttributionTab = (typeof attributionTabs)[number];

export const attributionGroups = ['campaign', 'content', 'link', 'recipient'] as const;
export type AttributionGroupChoice = (typeof attributionGroups)[number];

/** The Attribution page also keeps its tab, model version and grouping in the address. */
export interface AttributionSearch extends AnalyzeSearch {
  tab?: AttributionTab;
  model?: string;
  group?: AttributionGroupChoice;
}

export function attributionSearch(search: Record<string, unknown>): AttributionSearch {
  return {
    ...analyzeSearch(search),
    tab: attributionTabs.find((tab) => tab !== 'credit' && tab === search.tab),
    model: isIdentifier(search.model) ? search.model : undefined,
    group: attributionGroups.find((group) => group !== 'campaign' && group === search.group),
  };
}
