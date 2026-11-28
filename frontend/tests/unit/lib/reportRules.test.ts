import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import type { Member } from '@/api/team';
import { comparesWith, exportInput } from '@/features/reports/SaveExport';
import { reportOf } from '@/features/reports/ScheduleDialog';
import {
  daysLeft,
  EXPORT_LIMIT,
  exportGone,
  goneReasons,
  mayReceive,
  needsFinance,
  pauseReasons,
  RECIPIENT_LIMIT,
  runError,
  runErrors,
  SCHEDULE_LIMIT,
  scheduleNameProblem,
} from '@/features/reports/rules';

import { inRepository } from '../support/files';

const backend = (...parts: string[]) => readFileSync(inRepository('backend', 'app', ...parts), 'utf8');
const literal = (source: string, field: string) => {
  const found = new RegExp(`${field}: \\(?\\s*Literal\\[([^\\]]+)\\]`).exec(source)?.[1] ?? '';
  return [...found.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]).sort();
};

const scope = { agencyId: 'a', clientId: 'c', range: { start: '2026-11-01', end: '2026-11-08' }, compare: true };
const clientId = 'c1111111-1111-4111-8111-111111111111';
const member = (given: Partial<Member> = {}): Member => ({
  id: 'm1',
  agency_id: 'a',
  user_id: 'u1',
  role: 'analyst',
  status: 'active',
  joined_at: '2026-11-01T00:00:00Z',
  display_name: 'Youssef Salah',
  email_normalized: 'youssef@lumen.example',
  account: 'active',
  clients: [],
  ...given,
});

describe('the rules of exports and schedules', () => {
  it('keep the bounds of the API', () => {
    expect(backend('services', 'report_exports.py')).toContain(`EXPORT_LIMIT = ${EXPORT_LIMIT}`);
    const schedules = backend('services', 'report_schedules.py');
    expect(schedules).toContain(`ACTIVE_LIMIT = ${SCHEDULE_LIMIT}`);
    expect(schedules).toContain(`RECIPIENT_LIMIT = ${RECIPIENT_LIMIT}`);
  });

  it('name every reason an export is gone, every pause and every failed run, and no other', () => {
    const delivery = backend('api', 'report_delivery.py');
    expect(Object.keys(goneReasons).filter((reason) => reason !== 'expired').sort()).toEqual(literal(delivery, 'revoked_reason'));
    expect(Object.keys(pauseReasons).sort()).toEqual(literal(delivery, 'pause_reason'));
    const codes = [...backend('services', 'report_schedules.py').matchAll(/^ {4}"[a-z_]+": "([a-z_]+)",$/gm)].map((match) => match[1]);
    expect([...new Set([...codes, 'build_failed'])].sort()).toEqual(Object.keys(runErrors).sort());
    expect(runError('something_new')).toBe(runErrors.build_failed);
    expect(runError(null)).toBe(runErrors.build_failed);
  });

  it('need financial access as the API does', () => {
    const reporting = backend('services', 'reporting.py');
    expect(reporting).toContain('"spend": "finance:read"');
    expect(reporting).toContain('"social": "client:read"');
    expect(reporting).toContain('FINANCE_SPLIT = frozenset({"attribution", "funnel"})');
    expect(needsFinance('revenue', false)).toBe(true);
    expect(needsFinance('roas', false)).toBe(true);
    expect(needsFinance('social', true)).toBe(false);
    expect(needsFinance('attribution', false)).toBe(false);
    expect(needsFinance('attribution', true)).toBe(true);
  });

  it('let only members who may read the report receive it', () => {
    expect(mayReceive(member({ role: 'owner' }), clientId, 'revenue', false)).toBe(true);
    expect(mayReceive(member({ role: 'admin' }), clientId, 'funnel', true)).toBe(true);
    expect(mayReceive(member(), clientId, 'social', false)).toBe(false);
    const granted = member({ clients: [{ client_id: clientId, can_view_financials: false, can_view_identities: false }] });
    expect(mayReceive(granted, clientId, 'social', false)).toBe(true);
    expect(mayReceive(granted, clientId, 'attribution', false)).toBe(true);
    expect(mayReceive(granted, clientId, 'attribution', true)).toBe(false);
    expect(mayReceive(granted, clientId, 'revenue', false)).toBe(false);
    const financial = member({ role: 'client_viewer', clients: [{ client_id: clientId, can_view_financials: true, can_view_identities: false }] });
    expect(mayReceive(financial, clientId, 'revenue', false)).toBe(true);
    expect(mayReceive({ ...financial, status: 'paused' }, clientId, 'social', false)).toBe(false);
    expect(mayReceive({ ...financial, account: 'disabled' }, clientId, 'social', false)).toBe(false);
  });

  it('check the name of a schedule as the API does', () => {
    expect(backend('services', 'report_schedules.py')).toContain('if not 1 <= len(value) <= 100 or any(ord(char) < 32 or ord(char) == 127 for char in value):');
    expect(scheduleNameProblem('  Weekly revenue ')).toBeNull();
    expect(scheduleNameProblem(' ')).toBe('required');
    expect(scheduleNameProblem('a'.repeat(101))).toBe('too_long');
    expect(scheduleNameProblem('Weekly\u0009revenue')).toBe('invalid');
  });

  it('say how an export stands and how long it is kept', () => {
    const base = { status: 'ready', revoked_reason: null } as const;
    expect(exportGone(base as never)).toBeNull();
    expect(exportGone({ ...base, status: 'expired' } as never)).toBe('expired');
    expect(exportGone({ status: 'revoked', revoked_reason: 'disconnection' } as never)).toBe('disconnection');
    expect(daysLeft('2026-11-08T10:00:00Z', new Date('2026-11-01T11:00:00Z'))).toBe(7);
    expect(daysLeft('2026-11-01T10:00:00Z', new Date('2026-11-02T00:00:00Z'))).toBe(0);
  });
});

describe('the report an export or a schedule keeps', () => {
  it('is the page’s report, compared only where the API allows it', () => {
    expect(exportInput({ scope, family: 'revenue', parameters: {} })).toEqual({ family: 'revenue', start: '2026-11-01', end: '2026-11-08', compare: 'previous' });
    expect(exportInput({ scope, family: 'social', parameters: { connection_id: 'x', view: 'content_cohort' } })).toMatchObject({ compare: null, view: 'content_cohort' });
    expect(comparesWith({ scope, family: 'attribution', parameters: { view: 'models', group_by: 'campaign' } })).toBe(false);
    expect(exportInput({ scope: { ...scope, compare: false }, family: 'spend', parameters: { connection_id: 'x', level: 'ad' } })).toMatchObject({ compare: null, level: 'ad' });
  });

  it('carries the choices of the schedule form, without days', () => {
    const draft = {
      name: 'Weekly',
      family: 'funnel' as const,
      connectionId: '',
      view: 'daily' as const,
      level: 'campaign' as const,
      group: 'recipient' as const,
      modelVersion: '',
      compare: true,
      saleValues: true,
      cadence: 'weekly' as const,
      weekday: 1,
      hour: 9,
      timeZone: 'Africa/Cairo',
      recipients: [],
    };
    expect(reportOf(draft)).toEqual({ family: 'funnel', group_by: 'campaign', model_version: null, compare: 'previous' });
    expect(reportOf({ ...draft, family: 'social', connectionId: 'k', view: 'content_cohort' })).toEqual({ family: 'social', connection_id: 'k', view: 'content_cohort', compare: null });
    expect(reportOf({ ...draft, family: 'roas', connectionId: 'k', modelVersion: 'v' })).toEqual({ family: 'roas', connection_id: 'k', level: 'campaign', model_version: 'v', compare: 'previous' });
  });
});
