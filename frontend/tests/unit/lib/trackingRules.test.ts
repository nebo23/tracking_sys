import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { ApiError } from '@/api/errors';
import { worthRetrying } from '@/app/queryClient';
import {
  channels,
  erasureStates,
  erasureTargets,
  exactOrigins,
  formFields,
  formKeyError,
  installCode,
  lastDays,
  noticeDigest,
  outcomes,
  reasonMessage,
  requesterKinds,
  summarize,
  TRACKER_VERSION,
} from '@/features/tracking/rules';

import { inRepository } from '../support/files';

const backend = (...parts: string[]) => readFileSync(inRepository('backend', 'app', ...parts), 'utf8');
const quoted = (text: string) => [...text.matchAll(/'([a-z_]+)'/g)].map((match) => match[1] as string);

describe('the rules of event collection, as the API states them', () => {
  it('know the channels and outcomes the counters may hold', () => {
    const model = backend('models', 'collection.py');
    expect([...channels].sort()).toEqual(quoted(/"channel IN \(([^)]*)\)"/.exec(model)?.[1] ?? '').sort());
    const outcomeBlock = /"outcome IN \(([^)]*)\)"/s.exec(model.replace(/"\s*\n\s*"/g, ''))?.[1] ?? '';
    expect([...outcomes].sort()).toEqual(quoted(outcomeBlock).sort());
  });

  it('know the states, requesters and targets of an erasure', () => {
    const deletion = backend('privacy', 'deletion.py');
    const values = (name: string) => [...(new RegExp(`class ${name}\\(StrEnum\\):([\\s\\S]*?)\\n\\n`).exec(deletion)?.[1] ?? '').matchAll(/= "([a-z_]+)"/g)].map((match) => match[1]);
    expect([...erasureStates].sort()).toEqual(values('RequestStatus').sort());
    expect([...requesterKinds].sort()).toEqual(values('RequesterKind').sort());
    const service = backend('services', 'collection.py');
    for (const target of erasureTargets) expect(service, target).toContain(`"${target}": TargetStatus`);
  });

  it('install the version of the tracker package that the repository holds', () => {
    const manifest = JSON.parse(readFileSync(inRepository('packages', 'tracker-js', 'package.json'), 'utf8')) as { version: string };
    expect(TRACKER_VERSION).toBe(manifest.version);
    expect(installCode('https://api.connect.example', 'pk_example')).toBe(
      [
        `import { createTracker } from "/assets/tracker-${manifest.version}/tracker.js";`,
        '',
        'const tracker = createTracker({',
        '  collector: "https://api.connect.example",',
        '  publicKey: "pk_example",',
        '});',
      ].join('\n'),
    );
  });

  it('fingerprint the notice with SHA-256 of its exact text', async () => {
    for (const text of ['We count visits with your consent.', 'نستخدم التحليلات بموافقتك.\nيمكنك تغيير اختيارك.', ' spaces kept ']) {
      expect(await noticeDigest(text)).toBe(createHash('sha256').update(text, 'utf8').digest('hex'));
    }
  });

  it.each([
    [['https://shop.example.com'], ['https://shop.example.com'], null],
    [['https://SHOP.example.com/'], ['https://shop.example.com'], null],
    [['https://shop.example.com:443', 'http://localhost:3000'], ['https://shop.example.com', 'http://localhost:3000'], null],
    [[], [], 'tracking.rule.originsNone'],
    [['https://shop.example.com/page'], [], 'tracking.rule.origin'],
    [['https://shop.example.com?x=1'], [], 'tracking.rule.origin'],
    [['ftp://shop.example.com'], [], 'tracking.rule.origin'],
    [['https://*.example.com'], [], 'tracking.rule.origin'],
    [['https://user@shop.example.com'], [], 'tracking.rule.origin'],
    [['https://a.example', 'https://A.example'], [], 'tracking.rule.originsTwice'],
    [Array.from({ length: 11 }, (_, index) => `https://s${index}.example`), [], 'tracking.rule.originsMany'],
  ])('sites %j become %j (%s)', (texts, origins, error) => {
    expect(exactOrigins(texts)).toEqual({ origins, error });
  });

  it('check the fields of a form', () => {
    expect(formFields([]).error).toBe('tracking.rule.fieldsNone');
    const checked = formFields([
      { name: 'plan', label: ' Plan ', dataClass: 'form.option', options: 'basic\npro' },
      { name: 'plan', label: '', dataClass: 'form.code', options: '' },
      { name: 'bad name', label: '', dataClass: 'form.quantity', options: '' },
      { name: 'menu', label: '', dataClass: 'form.option', options: '' },
    ]);
    expect(checked.fields).toEqual([]);
    expect(checked.errors).toEqual([{}, { name: 'tracking.rule.fieldNameTwice' }, { name: 'tracking.rule.fieldName' }, { options: 'tracking.rule.optionsNone' }]);
    expect(formFields([{ name: 'plan', label: ' Plan ', dataClass: 'form.option', options: 'basic, pro' }]).fields).toEqual([
      { name: 'plan', input_type: 'text', autocomplete: '', label: 'Plan', data_class: 'form.option', options: ['basic', 'pro'] },
    ]);
    expect(formKeyError('lead_form-2')).toBeNull();
    expect(formKeyError('Lead')).toBe('tracking.rule.formKey');
  });

  it('read at most 31 days, both ends included, in UTC', () => {
    const now = new Date('2026-11-26T23:30:00Z').getTime();
    expect(lastDays(7, now)).toEqual({ start: '2026-11-20', end: '2026-11-26' });
    expect(lastDays(31, now)).toEqual({ start: '2026-10-27', end: '2026-11-26' });
    expect(lastDays(90, now)).toEqual({ start: '2026-10-27', end: '2026-11-26' });
  });

  it('add up what was kept, refused, held back and trimmed', () => {
    expect(
      summarize([
        { outcome: 'accepted', count: 5 },
        { outcome: 'upgraded', count: 1 },
        { outcome: 'duplicate', count: 9 },
        { outcome: 'rejected', count: 2 },
        { outcome: 'conflict', count: 1 },
        { outcome: 'suppressed', count: 4 },
        { outcome: 'minimized', count: 3 },
      ]),
    ).toEqual({ kept: 6, refused: 3, withoutConsent: 4, trimmed: 3 });
    expect(reasonMessage('consent_denied')).toBe('tracking.reason.consent_denied');
    expect(reasonMessage('a_reason_from_later')).toBeNull();
  });
});

describe('asking again', () => {
  it('waits for a passing problem, and not for a feature the server has switched off', () => {
    expect(worthRetrying(0, new ApiError(503, 'temporarily_unavailable'))).toBe(true);
    expect(worthRetrying(0, new ApiError(0, 'network_error'))).toBe(true);
    expect(worthRetrying(2, new ApiError(503, 'temporarily_unavailable'))).toBe(false);
    for (const code of ['collection_not_configured', 'payments_unavailable', 'integration_unavailable', 'whatsapp_unavailable', 'verification_unavailable']) {
      expect(worthRetrying(0, new ApiError(503, code)), code).toBe(false);
    }
    expect(worthRetrying(0, new ApiError(403, 'access_denied'))).toBe(false);
  });
});
