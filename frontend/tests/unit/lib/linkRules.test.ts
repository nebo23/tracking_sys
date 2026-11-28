import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import type { DestinationSite, LinkDomain } from '@/api/links';
import {
  CLICK_NAMES,
  destinationError,
  domainError,
  domainFailureMessage,
  domainFailures,
  domainState,
  linkState,
  moment,
  localValue,
  queryNamesError,
  readableAddress,
  RESERVED_SLUGS,
  shortAddress,
  siteOrigin,
  slugError,
  UTM_NAMES,
} from '@/features/links/rules';
import { messages } from '@/i18n';

import { inRepository } from '../support/files';

const policy = readFileSync(inRepository('backend', 'app', 'links', 'policy.py'), 'utf8');
const quoted = (block: string) => [...block.matchAll(/"([a-z0-9_.-]+)"/g)].map((match) => match[1] as string).sort();

const site = (given: Partial<DestinationSite> = {}): DestinationSite => ({
  id: 'e1111111-1111-4111-8111-111111111111',
  client_id: 'c1111111-1111-4111-8111-111111111111',
  origin: 'https://shop.olive.example',
  query_names: ['lang'],
  status: 'active',
  created_at: '2026-11-20T09:00:00Z',
  updated_at: '2026-11-20T09:00:00Z',
  ...given,
});
const domain = (given: Partial<LinkDomain> = {}): LinkDomain => ({
  id: 'd9999999-9999-4999-8999-999999999999',
  client_id: 'c1111111-1111-4111-8111-111111111111',
  hostname: 'go.olive.example',
  status: 'pending',
  challenge_generation: 0,
  challenge_expires_at: null,
  verified_at: null,
  verification_expires_at: null,
  certificate_expires_at: null,
  last_checked_at: null,
  failure_code: null,
  version: 1,
  created_at: '2026-11-21T09:00:00Z',
  ...given,
});
const now = new Date('2026-11-26T12:00:00Z').getTime();

describe('the rules of a link, as the API states them', () => {
  it('reserve the same slugs as the API', () => {
    const block = /RESERVED_SLUGS = frozenset\(\s*\{([^}]*)\}/.exec(policy)?.[1] ?? '';
    expect([...RESERVED_SLUGS].sort()).toEqual(quoted(block));
    expect(policy).toContain('SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")');
  });

  it('know the same campaign values and click identifiers as the collector', () => {
    const source = readFileSync(inRepository('backend', 'app', 'privacy', 'collection.py'), 'utf8');
    const names = quoted(/DEFAULT_URL_PARAMETERS = frozenset\(\s*\{([^}]*)\}/.exec(source)?.[1] ?? '');
    expect([...UTM_NAMES].sort()).toEqual(names.filter((name) => name.startsWith('utm_')));
    expect([...CLICK_NAMES].sort()).toEqual(names.filter((name) => !name.startsWith('utm_')));
  });

  it('give every failure code of a domain check its own sentence', () => {
    const sources = ['links/verification.py', 'services/links.py'].map((file) => readFileSync(inRepository('backend', 'app', ...file.split('/')), 'utf8'));
    const codes = new Set<string>();
    for (const source of sources) {
      for (const match of source.matchAll(/CheckResult\("([a-z_]+)"\)|failure = "([a-z_]+)"|failure_code = failure or "([a-z_]+)"/g)) {
        codes.add((match[1] ?? match[2] ?? match[3]) as string);
      }
    }
    expect([...codes].sort()).toEqual([...domainFailures].sort());
    for (const code of codes) expect(messages.en[domainFailureMessage(code)], code).not.toBe(messages.en['links.domain.failure.other']);
    expect(domainFailureMessage('something_new')).toBe('links.domain.failure.other');
  });

  it.each([
    ['ramadan-reel', null],
    ['abc', null],
    ['', 'field.error.required'],
    ['ab', 'links.rule.slug'],
    ['-abc', 'links.rule.slug'],
    ['Ramadan', 'links.rule.slug'],
    ['a'.repeat(65), 'links.rule.slug'],
    ['help', 'links.rule.slugReserved'],
  ])('a slug %s is %s', (slug, error) => {
    expect(slugError(slug)).toBe(error);
  });

  it.each([
    ['https://shop.olive.example', null],
    ['https://shop.olive.example/', null],
    ['https://shop.olive.example/page', null],
    ['https://shop.olive.example/page?lang=ar&utm_source=story', null],
    ['https://SHOP.olive.example:443/page', null],
    ['https://shop.olive.example/page?ref=a', 'links.rule.destinationQueryName'],
    ['https://shop.olive.example/page?lang=ar&lang=en', 'links.rule.destinationQuery'],
    ['https://shop.olive.example/page?lang', 'links.rule.destinationQuery'],
    ['https://shop.olive.example/page?ts_link=a', 'links.rule.destinationQuery'],
    ['https://shop.olive.example/page?lang=a+b', 'links.rule.destinationQuery'],
    ['https://shop.olive.example/page#top', 'links.rule.destination'],
    ['https://user@shop.olive.example/page', 'links.rule.destination'],
    ['https://shop.olive.example/a/./b', 'links.rule.destination'],
    ['https://shop.olive.example//b', 'links.rule.destination'],
    ['https://shop.olive.example/a%2Fb', 'links.rule.destination'],
    ['https://shop.olive.example/50%', 'links.rule.destination'],
    ['https://shop.olive.example/café', 'links.rule.destination'],
    ['https://shop.olive.example:8443/page', 'links.rule.destinationSite'],
    ['http://shop.olive.example/page', 'links.rule.destinationSite'],
    ['https://other.example/page', 'links.rule.destinationSite'],
    ['shop.olive.example/page', 'links.rule.destination'],
  ])('a destination %s is %s', (destination, error) => {
    expect(destinationError(destination, [site()])).toBe(error);
  });

  it('never leads to a site that is turned off', () => {
    expect(destinationError('https://shop.olive.example/page', [site({ status: 'disabled' })])).toBe('links.rule.destinationSite');
  });

  it.each([
    ['https://shop.example.com', 'https://shop.example.com', null],
    ['https://Shop.Example.COM/', 'https://shop.example.com', null],
    ['https://shop.example.com:443', 'https://shop.example.com', null],
    ['http://shop.example.com', null, 'links.rule.siteHttps'],
    ['https://shop.example.com/path', null, 'links.rule.site'],
    ['https://shop.example.com:8443', null, 'links.rule.site'],
    ['https://localhost', null, 'links.rule.hostname'],
    ['https://printer.local', null, 'links.rule.hostnameInternal'],
    ['https://10.0.0.1', null, 'links.rule.hostname'],
  ])('a site %s is %s', (text, origin, error) => {
    expect(siteOrigin(text)).toEqual({ origin, error });
  });

  it.each([
    [[], null],
    [['lang', 'ref'], null],
    [['Lang'], 'links.rule.queryName'],
    [['lang', 'lang'], 'links.rule.queryNamesTwice'],
    [['utm_source'], 'links.rule.queryNameReserved'],
    [['fbclid'], 'links.rule.queryNameReserved'],
    [['ts_link'], 'links.rule.queryNameReserved'],
    [['session_id'], 'links.rule.queryNameSensitive'],
    [['customer'], 'links.rule.queryNameSensitive'],
    [['resettoken'], 'links.rule.queryNameSensitive'],
    [Array.from({ length: 21 }, (_, index) => `n${index}`), 'links.rule.queryNamesMany'],
  ])('kept query names %j are %s', (names, error) => {
    expect(queryNamesError(names)).toBe(error);
  });

  it.each([
    ['go.example.com', null],
    ['', 'field.error.required'],
    ['go', 'links.rule.hostname'],
    ['go.example.com.', 'links.rule.hostname'],
    ['*.example.com', 'links.rule.hostname'],
    ['go.internal', 'links.rule.hostnameInternal'],
  ])('a domain %s is %s', (text, error) => {
    expect(domainError(text)).toBe(error);
  });
});

describe('what a link and a domain are now', () => {
  it('reads a paused link as paused whatever its end, and an active one past its end as expired', () => {
    expect(linkState({ status: 'active', expires_at: null }, now)).toBe('active');
    expect(linkState({ status: 'active', expires_at: '2026-11-27T00:00:00Z' }, now)).toBe('active');
    expect(linkState({ status: 'active', expires_at: '2026-11-26T12:00:00Z' }, now)).toBe('expired');
    expect(linkState({ status: 'disabled', expires_at: '2026-11-20T00:00:00Z' }, now)).toBe('paused');
  });

  it('reads the state of a domain in the order a person acts on it', () => {
    expect(domainState(domain(), now)).toBe('unverified');
    expect(domainState(domain({ challenge_expires_at: '2026-11-27T00:00:00Z' }), now)).toBe('waiting');
    expect(domainState(domain({ challenge_expires_at: '2026-11-26T00:00:00Z' }), now)).toBe('expired');
    expect(domainState(domain({ status: 'verified', verification_expires_at: '2026-11-27T00:00:00Z' }), now)).toBe('verified');
    expect(domainState(domain({ status: 'verified', verification_expires_at: '2026-11-26T11:00:00Z' }), now)).toBe('recheck');
    // A failed recheck of a verified domain needs attention before its verification runs out.
    expect(domainState(domain({ status: 'verified', verification_expires_at: '2026-11-27T00:00:00Z', failure_code: 'tls_invalid' }), now)).toBe('failed');
    expect(domainState(domain({ status: 'disabled', failure_code: 'tls_invalid' }), now)).toBe('off');
  });

  it('builds the short address on the platform host or on the domain', () => {
    expect(shortAddress('ramadan-reel', null)).toBe('http://127.0.0.1:8000/r/ramadan-reel');
    expect(shortAddress('ramadan-reel', { hostname: 'go.olive.example' })).toBe('https://go.olive.example/r/ramadan-reel');
    expect(readableAddress('https://go.olive.example/r/ramadan-reel')).toBe('go.olive.example/r/ramadan-reel');
  });

  it('turns the local time of a field into a moment and back', () => {
    expect(moment('')).toBeNull();
    expect(moment('not a time')).toBeNull();
    const chosen = moment('2026-12-01T09:30');
    expect(chosen).not.toBeNull();
    expect(localValue(chosen)).toBe('2026-12-01T09:30');
    expect(localValue(null)).toBe('');
  });
});
