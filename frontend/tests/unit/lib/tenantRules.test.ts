import { readFileSync } from 'node:fs';

import { afterEach, describe, expect, it } from 'vitest';

import { PAGE_SIZE, readAll } from '@/api/pages';
import { relativeParts } from '@/components/Time';
import { summarize } from '@/features/clients/summary';
import { coverageBar, runReason, statusReason, streamName } from '@/features/connections/coverage';
import { connectionErrors } from '@/features/connections/errors';
import { pendingConnection } from '@/features/connections/pendingConnection';
import { connectable, providerLabel, providerOf } from '@/features/connections/providers';
import { returnErrorMessage, returnErrors } from '@/features/connections/returnErrors';
import { keyState } from '@/features/keys/KeysPage';
import { invitationState } from '@/features/team/TeamPage';
import { messages } from '@/i18n';
import { isIdentifier } from '@/lib/identifier';
import { byName } from '@/lib/sort';
import { KEY_NAME_MAX } from '@/lib/validation';

import { connection } from '../support/api';
import { inRepository } from '../support/files';

afterEach(() => window.sessionStorage.clear());

const at = (text: string) => new Date(text).getTime();
const now = at('2026-11-26T12:00:00Z');

describe('identifiers', () => {
  it('are the only thing an address may hand to the API as one', () => {
    expect(isIdentifier('8a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d')).toBe(true);
    for (const other of ['', 'clients', '../account', '8A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D', '8a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d/x', undefined, null, 7]) {
      expect(isIdentifier(other), String(other)).toBe(false);
    }
  });
});

describe('paged lists', () => {
  it('are read until a page comes back short', async () => {
    const asked: number[] = [];
    const all = await readAll(async (offset) => {
      asked.push(offset);
      return Array.from({ length: offset < 2 * PAGE_SIZE ? PAGE_SIZE : 7 }, (_item, index) => offset + index);
    });
    expect(asked).toEqual([0, 100, 200]);
    expect(all).toHaveLength(207);
    expect(all.at(-1)).toBe(206);
  });

  it('stop at a bound instead of asking for ever', async () => {
    let pages = 0;
    await readAll(async () => {
      pages += 1;
      return Array.from({ length: PAGE_SIZE }, () => 0);
    });
    expect(pages).toBe(50);
  });
});

describe('a moment said as its distance from now', () => {
  it.each([
    ['2026-11-26T11:59:40Z', 0, 'second'],
    ['2026-11-26T11:15:00Z', -45, 'minute'],
    ['2026-11-26T09:00:00Z', -3, 'hour'],
    ['2026-11-22T12:00:00Z', -4, 'day'],
    ['2026-08-20T12:00:00Z', -3, 'month'],
    ['2024-11-01T12:00:00Z', -2, 'year'],
    ['2026-11-26T14:30:00Z', 2, 'hour'],
  ])('%s is %i %s', (moment, value, unit) => {
    const parts = relativeParts(now, at(moment));
    expect(parts.unit).toBe(unit);
    expect(parts.value + 0).toBe(value);
  });
});

describe('the summary of a client\'s connections', () => {
  it('counts only connections that still exist', () => {
    const summary = summarize([connection({ status: 'disconnected' }), connection({ status: 'disconnected', id: 'd2' })]);
    expect(summary.state).toBe('none');
    expect(summary.live).toHaveLength(0);
    expect(summary.lastSync).toBeNull();
  });

  it('puts a needed reconnect before everything else', () => {
    const summary = summarize([connection(), connection({ id: 'd2', status: 'reconnect_required' }), connection({ id: 'd3', status: 'disconnecting' })]);
    expect(summary.state).toBe('reconnect');
    expect(summary.reconnect.map((item) => item.id)).toEqual(['d2']);
  });

  it('says disconnecting only when nothing else is left', () => {
    expect(summarize([connection({ status: 'disconnecting' })]).state).toBe('disconnecting');
    expect(summarize([connection({ status: 'disconnecting' }), connection({ id: 'd2' })]).state).toBe('connected');
  });

  it('takes the newest synchronization, and none when nothing was ever read', () => {
    const summary = summarize([
      connection({ last_successful_sync_at: '2026-11-20T09:00:00Z' }),
      connection({ id: 'd2', last_successful_sync_at: '2026-11-26T09:00:00Z' }),
      connection({ id: 'd3', last_successful_sync_at: null }),
    ]);
    expect(summary.lastSync).toBe('2026-11-26T09:00:00Z');
    expect(summarize([connection({ last_successful_sync_at: null })]).lastSync).toBeNull();
  });
});

describe('the covered range of a stream', () => {
  const stream = (given: Record<string, unknown>) => ({
    stream: 'account',
    state: 'complete' as const,
    covered_from: '2026-10-27T12:00:00Z',
    complete_through: '2026-11-26T12:00:00Z',
    history_limit_days: 30,
    sync: { state: 'idle' as const, kind: null, reason: null, next_attempt_at: null },
    ...given,
  });

  it('fills the bar when the whole history is stored', () => {
    expect(coverageBar(stream({}), now)).toEqual({ start: 0, size: 100 });
  });

  it('starts later when the history begins later, and ends where the stored range ends', () => {
    const bar = coverageBar(stream({ covered_from: '2026-11-11T12:00:00Z', complete_through: '2026-11-21T12:00:00Z' }), now);
    expect(bar?.start).toBeCloseTo(50, 1);
    expect(bar?.size).toBeCloseTo(33.3, 1);
  });

  it('keeps a single day visible and inside the bar', () => {
    const bar = coverageBar(stream({ covered_from: '2026-11-26T11:00:00Z', complete_through: '2026-11-26T12:00:00Z' }), now);
    expect(bar).not.toBeNull();
    expect((bar?.start ?? 0) + (bar?.size ?? 0)).toBeLessThanOrEqual(100);
    expect(bar?.size).toBeGreaterThanOrEqual(2);
  });

  it('draws nothing for a stream that was never read, or whose range makes no sense', () => {
    expect(coverageBar(stream({ covered_from: null, complete_through: null }), now)).toBeNull();
    expect(coverageBar(stream({ covered_from: '2026-11-20T00:00:00Z', complete_through: '2026-11-10T00:00:00Z' }), now)).toBeNull();
  });

  it('reaches back to a history older than the provider now offers', () => {
    const bar = coverageBar(stream({ covered_from: '2026-07-01T12:00:00Z' }), now);
    expect(bar).toEqual({ start: 0, size: 100 });
  });
});

describe('the words for what the API reports', () => {
  it('names the streams the adapters declare, and leaves an unknown one to its own name', () => {
    const declared = ['account', 'media', 'stories', 'channel', 'channel_daily', 'videos', 'video_totals', 'ad_objects', 'ad_daily'];
    for (const name of declared) expect(streamName(name), name).not.toBeNull();
    expect(streamName('something_new')).toBeNull();
  });

  it('has a sentence for every stream an adapter declares in the API', () => {
    const declared = new Set<string>();
    for (const file of ['synthetic_instagram', 'synthetic_youtube', 'synthetic_meta_ads']) {
      const source = readFileSync(inRepository('backend', 'app', 'connectors', `${file}.py`), 'utf8');
      for (const match of source.matchAll(/StreamSpec\(\s*"([a-z_]+)"/g)) declared.add(match[1] as string);
    }
    expect(declared.size).toBeGreaterThanOrEqual(9);
    expect([...declared].filter((name) => streamName(name) === null)).toEqual([]);
  });

  it('explains why a run waits or failed, and falls back for a reason added later', () => {
    expect(runReason('rate_limited')).toBe('connections.run.reason.rate_limited');
    expect(runReason('something_new')).toBeNull();
    expect(runReason(null)).toBeNull();
    expect(statusReason('provider_revoked', 'connections.reason.credential_expired')).toBe('connections.reason.provider_revoked');
    expect(statusReason('something_new', 'connections.reason.credential_expired')).toBe('connections.reason.credential_expired');
    expect(statusReason(null, 'connections.reason.user_requested')).toBe('connections.reason.user_requested');
  });

  it('has a sentence for every reason for which the API stops or removes a connection', () => {
    const source = readFileSync(inRepository('backend', 'app', 'services', 'connectors.py'), 'utf8');
    const reasons = new Set<string>();
    for (const match of source.matchAll(/(?:_require_reconnect|start_disconnect)\([^)]*?"([a-z_]+)"/g)) reasons.add(match[1] as string);
    expect([...reasons].sort()).toEqual(['authorization_lost', 'credential_expired', 'provider_revoked', 'user_requested']);
    for (const reason of reasons) expect(statusReason(reason, 'error.unknown'), reason).not.toBe('error.unknown');
  });
});

describe('the outcomes of a return from a provider', () => {
  it('are exactly the ones the API sends', () => {
    const source = readFileSync(inRepository('backend', 'app', 'services', 'connectors.py'), 'utf8');
    const block = /CALLBACK_ERRORS = frozenset\(\s*\{([^}]*)\}/.exec(source)?.[1] ?? '';
    const sent = [...block.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]).sort();
    expect(sent.length).toBeGreaterThan(0);
    expect([...returnErrors].sort()).toEqual(sent);
  });

  it('each have a sentence in both languages', () => {
    for (const code of returnErrors) {
      expect(messages.en[returnErrorMessage[code]], code).toMatch(/\S/);
      expect(messages.ar[returnErrorMessage[code]], code).toMatch(/\S/);
    }
  });
});

describe('the refusals of the connection operations', () => {
  // What the routes of this slice can answer: connect, reconnect, list, read, coverage, sync and
  // disconnect. The other codes of these files belong to operations no screen of this slice calls.
  const elsewhere = new Set([
    'invalid_delivery',
    'signature_invalid',
    'signature_expired',
    'deletion_request_not_found',
    'invalid_cursor',
    'not_a_spend_connection',
    'not_a_delivery_connection',
    'invalid_period',
    'invalid_event_name',
    'invalid_test_event_code',
    'destination_exists',
    'requeue_not_available',
    'dismiss_not_available',
  ]);

  it('each have a sentence, so a new code of the API fails this test', () => {
    const raised = new Set<string>();
    for (const file of [['services', 'connectors.py'], ['api', 'connectors.py']]) {
      const source = readFileSync(inRepository('backend', 'app', ...file), 'utf8');
      for (const match of source.matchAll(/ConnectorError\(\s*"([a-z_]+)"/g)) raised.add(match[1] as string);
    }
    expect(raised.size).toBeGreaterThan(10);
    const without = [...raised].filter((code) => !elsewhere.has(code) && connectionErrors[code] === undefined);
    expect(without).toEqual([]);
  });
});

describe('the providers a person can choose', () => {
  it('are the product\'s own in an ordinary build', () => {
    expect(connectable.map((provider) => provider.id)).toEqual(['instagram', 'youtube', 'meta_ads']);
    expect(connectable.some((provider) => provider.synthetic)).toBe(false);
  });

  it('ask for what the API requires of each', () => {
    expect(providerOf('instagram')).toMatchObject({ account: null, approval: null });
    expect(providerOf('youtube')?.approval).toBe('dev-agent-approval-1');
    expect(providerOf('synthetic_youtube')?.approval).toBe('dev-agent-approval-1');
    const number = providerOf('meta_ads')?.account?.pattern;
    for (const accepted of ['1234567890', 'act_1234567890']) expect(number?.test(accepted), accepted).toBe(true);
    for (const refused of ['', '0123', 'act_', 'act_12a', '12 34', 'ACT_123', '1'.repeat(21)]) expect(number?.test(refused), refused).toBe(false);
  });

  it('use the approval version and the account rule of the API', () => {
    const youtube = readFileSync(inRepository('backend', 'app', 'connectors', 'synthetic_youtube.py'), 'utf8');
    expect(/agent_disclosure="([a-z0-9-]+)"/.exec(youtube)?.[1]).toBe(providerOf('youtube')?.approval);
    const contract = JSON.parse(readFileSync(inRepository('contracts', 'openapi.json'), 'utf8')) as {
      components: { schemas: Record<string, { properties: Record<string, { anyOf?: Array<{ pattern?: string }>; maxLength?: number }> }> };
    };
    const account = contract.components.schemas.ConnectInput?.properties.account?.anyOf?.find((option) => option.pattern);
    expect(account?.pattern).toBe(providerOf('meta_ads')?.account?.pattern.source);
    expect(contract.components.schemas.ServiceKeyInput?.properties.name?.maxLength).toBe(KEY_NAME_MAX);
  });

  it('name a connection of a kind this page does not start, and leave an unknown one to its own word', () => {
    expect(providerLabel('meta_capi')).toEqual({ name: 'provider.meta_capi', glyph: 'meta' });
    expect(providerLabel('something_new')).toEqual({ name: null, glyph: null });
  });
});

describe('the record of a connection that was started', () => {
  const pending = { agencyId: '8a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d', clientId: 'c1111111-1111-4111-8111-111111111111' };

  it('holds the two identifiers and nothing else, until it is cleared', () => {
    pendingConnection.set(pending);
    expect(JSON.parse(window.sessionStorage.getItem('connect.pendingConnection') ?? '{}')).toEqual(pending);
    expect(pendingConnection.get()).toEqual(pending);
    // Reading does not remove it: a page that is drawn twice still finds it.
    expect(pendingConnection.get()).toEqual(pending);
    pendingConnection.clear();
    expect(pendingConnection.get()).toBeNull();
  });

  it.each(['not json', '[]', '"text"', '{"agencyId":"x","clientId":"y"}', '{"agencyId":7}'])('is ignored when it holds %s', (stored) => {
    window.sessionStorage.setItem('connect.pendingConnection', stored);
    expect(pendingConnection.get()).toBeNull();
  });
});

describe('time that has passed', () => {
  const invitation = { id: 'e1', agency_id: 'a', email_normalized: 'x@y.example', role: 'analyst' as const, created_at: '2026-11-20T00:00:00Z' };
  const key = { id: 'f1', agency_id: 'a', name: 'k', kind: 'read', created_at: '2026-11-20T00:00:00Z' };

  it('makes a pending invitation expired, at the very moment it ends', () => {
    expect(invitationState({ ...invitation, status: 'pending', expires_at: '2026-11-26T12:00:01Z' }, now)).toBe('pending');
    expect(invitationState({ ...invitation, status: 'pending', expires_at: '2026-11-26T12:00:00Z' }, now)).toBe('expired');
    expect(invitationState({ ...invitation, status: 'accepted', expires_at: '2026-11-01T00:00:00Z' }, now)).toBe('accepted');
    expect(invitationState({ ...invitation, status: 'revoked', expires_at: '2026-12-01T00:00:00Z' }, now)).toBe('revoked');
  });

  it('makes an active key expired, and leaves a revoked key revoked', () => {
    expect(keyState({ ...key, status: 'active', expires_at: '2026-11-26T12:00:01Z' }, now)).toBe('active');
    expect(keyState({ ...key, status: 'active', expires_at: '2026-11-26T12:00:00Z' }, now)).toBe('expired');
    expect(keyState({ ...key, status: 'revoked', expires_at: '2027-01-01T00:00:00Z' }, now)).toBe('revoked');
  });
});

describe('names in order', () => {
  it('follow the language, with numbers in their natural order', () => {
    const names = ['Olive 10', 'olive 2', 'Cedar', 'Élan'].map((name) => ({ name }));
    expect(names.sort(byName('en')).map((item) => item.name)).toEqual(['Cedar', 'Élan', 'olive 2', 'Olive 10']);
  });
});
