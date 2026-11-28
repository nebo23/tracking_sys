import { readFileSync } from 'node:fs';

import { QueryClient } from '@tanstack/react-query';
import { createIntl } from 'react-intl';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { clientKey } from '@/api/clients';
import { reportCsv, reportKey, socialReportQuery, spendNamesQuery, spendReportQuery, revenueReportQuery, type ReportScope } from '@/api/reports';
import { namedRows } from '@/features/analyze/AdSpendPage';
import { metricNames } from '@/features/analyze/parts';
import { addDays, lastCompleteDay, presetRange, previousRange, rangeFromSearch, rangeProblem, toReportRange } from '@/features/analyze/range';
import { moneyParts } from '@/features/analyze/shared';
import { comparisonReasons, freshnessStates, streamNames, totalReasons, valueReasons } from '@/features/analyze/states';
import { messages } from '@/i18n';

import { fakeApi, json } from '../support/api';
import { inRepository } from '../support/files';

const reporting = (file: string) => readFileSync(inRepository('backend', 'app', 'reporting', file), 'utf8');
const now = new Date('2026-11-28T09:30:00Z');

describe('a money figure', () => {
  it('writes its currency once, as the unit, in the order of each language', () => {
    const amount = { minor: 524370, decimal: '5243.70' };
    const english = createIntl({ locale: 'en', messages: messages.en });
    expect(moneyParts(english, amount, 'EGP', 2)).toEqual({ unit: 'EGP', amount: '5,243.70', unitFirst: true });
    expect(moneyParts(english, { minor: -1250, decimal: '-12.50' }, 'EGP', 2)).toEqual({ unit: 'EGP', amount: '-12.50', unitFirst: true });
    // In Arabic the amount comes first and the pound follows, without the marks that order mixed text.
    expect(moneyParts(createIntl({ locale: 'ar', messages: messages.ar }), amount, 'EGP', 2)).toEqual({ unit: '\u062c.\u0645.', amount: '5,243.70', unitFirst: false });
  });
});

describe('the days of a report', () => {
  it('end on the last complete day, yesterday in UTC, whichever preset is chosen', () => {
    expect(lastCompleteDay(now)).toBe('2026-11-27');
    expect(presetRange('last7', now)).toEqual({ from: '2026-11-21', to: '2026-11-27' });
    expect(presetRange('last30', now)).toEqual({ from: '2026-10-29', to: '2026-11-27' });
    expect(presetRange('month', now)).toEqual({ from: '2026-11-01', to: '2026-11-27' });
    // Just after midnight in UTC, the day that has just ended is the last complete one.
    expect(lastCompleteDay(new Date('2026-12-01T00:00:01Z'))).toBe('2026-11-30');
  });

  it('come from the address only when they are real, in order, at most 31 days and ended', () => {
    const fallback = presetRange('last30', now);
    expect(rangeFromSearch({ from: '2026-11-01', to: '2026-11-15' }, now)).toEqual({ from: '2026-11-01', to: '2026-11-15' });
    expect(rangeFromSearch({ from: '2026-11-15', to: '2026-11-01' }, now)).toEqual(fallback);
    expect(rangeFromSearch({ from: '2026-10-01', to: '2026-11-15' }, now)).toEqual(fallback);
    // Today may be asked for explicitly; a day that has not begun may not.
    expect(rangeFromSearch({ from: '2026-11-20', to: '2026-11-28' }, now)).toEqual({ from: '2026-11-20', to: '2026-11-28' });
    expect(rangeFromSearch({ from: '2026-11-20', to: '2026-11-29' }, now)).toEqual(fallback);
    expect(rangeFromSearch({ from: '2026-02-30', to: '2026-03-02' }, now)).toEqual(fallback);
    expect(rangeFromSearch({ from: 'yesterday' }, now)).toEqual(fallback);
    expect(rangeProblem({ from: '2026-10-28', to: '2026-11-27' }, now)).toBeNull();
    expect(rangeProblem({ from: '2026-10-27', to: '2026-11-27' }, now)).toBe('length');
    expect(rangeProblem({ from: '2026-11-27', to: '2026-11-28' }, now)).toBeNull();
    expect(rangeProblem({ from: '2026-11-27', to: '2026-11-29' }, now)).toBe('future');
    expect(presetRange('today', now)).toEqual({ from: '2026-10-30', to: '2026-11-28' });
  });

  it('are asked for as the API reads them, with the end excluded, and compare with the period before', () => {
    expect(toReportRange({ from: '2026-11-01', to: '2026-11-30' })).toEqual({ start: '2026-11-01', end: '2026-12-01' });
    expect(previousRange({ start: '2026-11-01', end: '2026-12-01' })).toEqual({ start: '2026-10-02', end: '2026-11-01' });
    expect(addDays('2026-03-29', 1)).toBe('2026-03-30');
  });
});

describe('the states of the reports', () => {
  /** The reason codes the reporting package sets, read from its source (backend/app/reporting/). */
  function backendReasons(): Set<string> {
    const found = new Set<string>();
    for (const file of ['social.py', 'spend.py', 'common.py']) {
      const source = reporting(file);
      for (const match of source.matchAll(/status, reason = "(?:complete|partial|unavailable)", "([a-z_]+)"/g)) found.add(match[1] as string);
      for (const match of source.matchAll(/reason(?:\s*=|\s*:)\s*"([a-z_]+)"/g)) found.add(match[1] as string);
      for (const match of source.matchAll(/return "([a-z_]+)"/g)) found.add(match[1] as string);
      for (const match of source.matchAll(/\(\s*"(?:partial|unavailable)"\s*,\s*"([a-z_]+)"\s*\)/g)) found.add(match[1] as string);
    }
    return found;
  }

  const known = new Set([...Object.keys(valueReasons), ...Object.keys(totalReasons), ...Object.keys(comparisonReasons), ...Object.keys(freshnessStates)]);
  // Words the scan also finds that are states, not reasons: they have words of their own.
  const states = new Set(['complete', 'partial', 'unavailable', 'available', 'missing', 'unsupported', 'not_synced', 'fresh', 'idle']);

  it('have a sentence for every reason the API sets, so a new code fails this test', () => {
    const reasons = [...backendReasons()].filter((code) => !states.has(code) || code === 'not_synced' || code === 'missing' || code === 'unsupported');
    expect(reasons.length).toBeGreaterThanOrEqual(15);
    expect(reasons.filter((code) => !known.has(code))).toEqual([]);
  });

  it('name no reason the API never sends', () => {
    const sources = ['social.py', 'spend.py', 'common.py', 'revenue.py'].map(reporting).join('\n');
    const stored = readFileSync(inRepository('backend', 'app', 'connectors', 'contracts.py'), 'utf8');
    const invented = [...known].filter((code) => !sources.includes(`"${code}"`) && !stored.includes(`"${code}"`));
    // Stored by the adapters or derived by the store, and named in the reporting guide.
    const documented = readFileSync(inRepository('docs', 'engineering', 'reporting.md'), 'utf8');
    expect(invented.filter((code) => !documented.includes(`\`${code}\``))).toEqual([]);
  });

  it('say every reason in both languages', () => {
    const ids = [...Object.values(valueReasons), ...Object.values(totalReasons), ...Object.values(comparisonReasons), ...Object.values(freshnessStates)];
    for (const id of ids) {
      expect(messages.en[id], id).toMatch(/\S/);
      expect(messages.ar[id], id).toMatch(/\S/);
    }
  });

  it('name every stream of the catalog in a sentence in both languages, never by its code', () => {
    const catalog = reporting('catalog.py');
    const streams = new Set<string>();
    for (const match of catalog.matchAll(/(?:daily_stream|publication_stream)="([a-z_]+)"/g)) streams.add(match[1] as string);
    for (const match of catalog.matchAll(/content_streams=(\(([^)]*)\))/g)) for (const name of (match[2] ?? '').matchAll(/"([a-z_]+)"/g)) streams.add(name[1] as string);
    for (const match of catalog.matchAll(/stream_delay_hours=MappingProxyType\(\s*\{([^}]*)\}/g)) for (const name of (match[1] ?? '').matchAll(/"([a-z_]+)"\s*:/g)) streams.add(name[1] as string);
    expect(streams.size).toBeGreaterThanOrEqual(7);
    expect(new Set(Object.keys(streamNames))).toEqual(streams);
    for (const id of Object.values(streamNames)) {
      expect(messages.en[id], id).toMatch(/\S/);
      expect(messages.ar[id], id).toMatch(/\S/);
    }
  });

  it('name every metric of the catalog that a report can show', () => {
    const catalog = reporting('catalog.py');
    const named = new Set<string>(metricNames);
    const excluded = new Set(['follows_and_unfollows', 'subscriberCount', 'viewCount', 'videoCount', 'likeCount', 'commentCount']);
    const metrics = new Set([...catalog.matchAll(/^\s+\("([A-Za-z_]+)",/gm)].map((match) => match[1] as string));
    expect(metrics.size).toBeGreaterThan(25);
    expect([...metrics].filter((metric) => !excluded.has(metric) && !named.has(metric))).toEqual([]);
    // What is left out is left out by the catalog too: an unreviewed or snapshot metric.
    for (const metric of excluded) {
      if (!metrics.has(metric)) continue;
      expect(catalog).toMatch(new RegExp(`\\("${metric}",[^\\n]*\\b(?:U|S)\\)`));
    }
    for (const metric of metricNames) expect(messages.ar[`analyze.metric.${metric}`], metric).toMatch(/\S/);
  });
});

describe('the report requests', () => {
  const scope: ReportScope = { agencyId: 'a1', clientId: 'c1', range: { start: '2026-11-01', end: '2026-11-08' }, compare: true };
  afterEach(() => vi.unstubAllGlobals());

  it('are kept under the agency and the client, so leaving the client drops them all', () => {
    for (const query of [socialReportQuery(scope, 'k1', 'daily'), spendReportQuery(scope, 'k2', 'ad'), revenueReportQuery(scope), spendNamesQuery(scope, 'k2', 'ad')]) {
      expect(query.queryKey.slice(0, 4)).toEqual([...clientKey('a1', 'c1')]);
    }
    expect(reportKey(scope, 'social')).not.toEqual(reportKey({ ...scope, clientId: 'c2' }, 'social'));
  });

  it('never compare a content cohort, and read later pages with the revision of the first', async () => {
    const page = (number: number, total: number) => ({ revision: 'r1', rows: [{ n: number }], page: { page: number, total_pages: total } });
    const server = fakeApi({
      'GET /agencies/a1/clients/c1/reports/social': ({ url }) => json(200, page(Number(new URL(url).searchParams.get('page')), 2)),
    });
    const client = new QueryClient();
    const answer = await client.fetchQuery(socialReportQuery(scope, 'k1', 'content_cohort'));
    const [first, second] = server.sent('GET /agencies/a1/clients/c1/reports/social').map((request) => new URL(request.url).searchParams);
    expect(first?.get('compare')).toBeNull();
    expect(first?.get('view')).toBe('content_cohort');
    expect(first?.get('expected_revision')).toBeNull();
    expect(second?.get('page')).toBe('2');
    expect(second?.get('expected_revision')).toBe('r1');
    expect(answer.rows).toHaveLength(2);
  });

  it('ask the 014 read for the same days, its last day included, and follow its pages', async () => {
    const server = fakeApi({
      'GET /agencies/a1/clients/c1/ad-spend': ({ url }) =>
        new URL(url).searchParams.get('after')
          ? json(200, { rows: [{ object_id: '2', name: 'Second' }], next_after: null })
          : json(200, { rows: [{ object_id: '1', name: 'First' }, { object_id: '3', name: null }], next_after: '1:EGP' }),
    });
    const names = await new QueryClient().fetchQuery(spendNamesQuery(scope, 'k2', 'campaign'));
    const [first] = server.sent('GET /agencies/a1/clients/c1/ad-spend').map((request) => new URL(request.url).searchParams);
    expect(first?.get('since')).toBe('2026-11-01');
    expect(first?.get('until')).toBe('2026-11-07');
    expect(first?.get('level')).toBe('campaign');
    expect([...names.entries()]).toEqual([
      ['1', 'First'],
      ['2', 'Second'],
    ]);
  });

  it('join the names to the report rows by ID and keep every ID', () => {
    const rows = [{ object_id: '1' }, { object_id: '9' }, { object_id: null }] as never;
    expect(namedRows(rows, new Map([['1', 'Ramadan']])).map((row) => [row.object_id, row.name])).toEqual([
      ['1', 'Ramadan'],
      ['9', null],
      [null, null],
    ]);
  });

  it('download a CSV straight from the API, without pages', async () => {
    const server = fakeApi({
      'GET /agencies/a1/clients/c1/reports/spend': () => new Response('a,b\n1,2\n', { status: 200, headers: { 'Content-Type': 'text/csv' } }),
    });
    const file = await reportCsv(scope, 'spend', { connection_id: 'k2', level: 'ad' });
    const [request] = server.sent('GET /agencies/a1/clients/c1/reports/spend');
    const query = new URL(request?.url ?? '').searchParams;
    expect(query.get('format')).toBe('csv');
    expect(query.get('compare')).toBe('previous');
    expect(query.get('page')).toBeNull();
    expect(query.get('page_size')).toBeNull();
    expect(await file.text()).toBe('a,b\n1,2\n');
  });
});

