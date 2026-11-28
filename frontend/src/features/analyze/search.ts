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
