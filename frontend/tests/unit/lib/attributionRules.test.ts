import { readFileSync } from 'node:fs';

import { QueryClient } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { clientKey } from '@/api/clients';
import { attributionReportQuery, funnelReportQuery, modelVersionsQuery, roasReportQuery, type ReportScope } from '@/api/reports';
import { attributionSearch } from '@/features/analyze/search';
import { orderedVersions } from '@/features/attribution/parts';
import { attributionReasons, freshnessBanners, roasReasons, shareText } from '@/features/attribution/states';
import { messages } from '@/i18n';

import { fakeApi, json } from '../support/api';
import { inRepository } from '../support/files';

const source = (...file: string[]) => readFileSync(inRepository('backend', 'app', ...file), 'utf8');

describe('the states of the attribution reports', () => {
  it('have a sentence for every reason the 016-B reports set, so a new code fails this test', () => {
    const credit = source('reporting', 'credit.py');
    const found = new Set<string>();
    // The freshness of the store becomes a reason of its own: attribution_behind, _rebuilding, _failed.
    expect(credit).toContain('f"attribution_{self.state}"');
    for (const state of ['behind', 'rebuilding', 'failed']) found.add(`attribution_${state}`);
    for (const file of [['reporting', 'credit.py'], ['reporting', 'funnel.py'], ['reporting', 'roas.py'], ['advertising', 'roas.py']]) {
      const text = source(...file);
      for (const match of text.matchAll(/"((?:attribution|ledger|unexplained|zero|currency)_[a-z_]+)"/g)) found.add(match[1] as string);
    }
    const known = new Set([...Object.keys(attributionReasons), ...Object.keys(roasReasons)]);
    // Literals of the same shape that are not reasons: a refusal of the request (an API error with
    // its own sentence) and a field of the answer.
    const notReasons = new Set(['currency_exponent_conflict', 'ledger_net']);
    expect([...found].filter((code) => !known.has(code) && !notReasons.has(code))).toEqual([]);
    expect(found.size).toBeGreaterThanOrEqual(8);
  });

  it('name only reasons the API sends, in both languages', () => {
    const all = ['reporting/credit.py', 'reporting/funnel.py', 'reporting/roas.py', 'advertising/roas.py'].map((file) => source(...file.split('/'))).join('\n');
    for (const code of [...Object.keys(attributionReasons), ...Object.keys(roasReasons)]) {
      const fromState = code.startsWith('attribution_') && ['behind', 'rebuilding', 'failed'].includes(code.slice('attribution_'.length));
      expect(fromState || all.includes(`"${code}"`), code).toBe(true);
    }
    for (const id of [...Object.values(attributionReasons), ...Object.values(roasReasons), ...Object.values(freshnessBanners)]) {
      expect(messages.en[id], id).toMatch(/\S/);
      expect(messages.ar[id], id).toMatch(/\S/);
    }
  });

  it('show a share of credit exactly as its decimal text', () => {
    expect(shareText('en', { numerator: 117, denominator: 2, decimal: '58.5' })).toBe('58.5');
    expect(shareText('en', { numerator: 1, denominator: 3, decimal: '0.333333' })).toBe('0.33');
    expect(shareText('ar', { numerator: 3, denominator: 1, decimal: '3' })).toBe('3');
    expect(shareText('en', null)).toBeNull();
  });
});

describe('the address of the Attribution page', () => {
  it('keeps the tab, the model and the grouping, leaving the defaults out', () => {
    const model = 'b1111111-1111-4111-8111-111111111111';
    expect(attributionSearch({ tab: 'roas', model, group: 'link', level: 'ad', from: '2026-11-01', to: '2026-11-07' })).toMatchObject({
      tab: 'roas',
      model,
      group: 'link',
      level: 'ad',
      from: '2026-11-01',
      to: '2026-11-07',
    });
    expect(attributionSearch({ tab: 'credit', group: 'campaign' })).toMatchObject({ tab: undefined, group: undefined });
    expect(attributionSearch({ tab: 'conversions', model: 'not-an-id', group: 'person' })).toMatchObject({ tab: undefined, model: undefined, group: undefined });
  });

  it('offers the active models with the client default first', () => {
    const version = (id: string, isDefault: boolean, status = 'active') => ({ id, is_default: isDefault, status }) as never;
    expect(orderedVersions([version('a', false), version('b', true), version('c', false, 'retired')]).map((item: { id: string }) => item.id)).toEqual(['b', 'a']);
  });
});

describe('the attribution requests', () => {
  const scope: ReportScope = { agencyId: 'a1', clientId: 'c1', range: { start: '2026-11-01', end: '2026-11-08' }, compare: true };
  afterEach(() => vi.unstubAllGlobals());
  const answer = { revision: 'r1', rows: [], page: { page: 1, total_pages: 1 } };

  it('send the model and the comparison with the groups view, and neither with the models view', async () => {
    const server = fakeApi({ 'GET /agencies/a1/clients/c1/reports/attribution': json(200, answer) });
    const client = new QueryClient();
    await client.fetchQuery(attributionReportQuery(scope, 'groups', 'content', 'm1'));
    await client.fetchQuery(attributionReportQuery(scope, 'models', 'content', 'm1'));
    const [groups, models] = server.sent('GET /agencies/a1/clients/c1/reports/attribution').map((request) => new URL(request.url).searchParams);
    expect(groups?.get('model_version')).toBe('m1');
    expect(groups?.get('compare')).toBe('previous');
    expect(groups?.get('group_by')).toBe('content');
    expect(models?.get('view')).toBe('models');
    expect(models?.get('model_version')).toBeNull();
    expect(models?.get('compare')).toBeNull();
  });

  it('ask for the return on ad spend of one account and level, under the chosen model', async () => {
    const server = fakeApi({
      'GET /agencies/a1/clients/c1/reports/roas': json(200, answer),
      'GET /agencies/a1/clients/c1/reports/funnel': json(200, answer),
    });
    const client = new QueryClient();
    await client.fetchQuery(roasReportQuery(scope, 'k2', 'adset', 'm1'));
    await client.fetchQuery(funnelReportQuery(scope, 'link', 'm1'));
    const [roas] = server.sent('GET /agencies/a1/clients/c1/reports/roas').map((request) => new URL(request.url).searchParams);
    expect(roas?.get('connection_id')).toBe('k2');
    expect(roas?.get('level')).toBe('adset');
    expect(roas?.get('model_version')).toBe('m1');
    const [funnel] = server.sent('GET /agencies/a1/clients/c1/reports/funnel').map((request) => new URL(request.url).searchParams);
    expect(funnel?.get('group_by')).toBe('link');
  });

  it('are kept under the agency and the client', () => {
    for (const query of [attributionReportQuery(scope, 'groups', 'campaign'), funnelReportQuery(scope, 'campaign'), roasReportQuery(scope, 'k2', 'ad'), modelVersionsQuery('a1', 'c1')]) {
      expect(query.queryKey.slice(0, 4)).toEqual([...clientKey('a1', 'c1')]);
    }
  });
});
