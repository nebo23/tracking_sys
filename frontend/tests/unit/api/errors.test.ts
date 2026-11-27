import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { ApiError, describeError } from '@/api/errors';
import { messages } from '@/i18n';

import { inRepository } from '../support/files';

// The codes of the authentication guide (docs/engineering/authentication.md) and of the plan.
const documented = [
  'authentication_required',
  'invalid_credentials',
  'email_verification_required',
  'invalid_or_expired_code',
  'invalid_or_expired_token',
  'reauthentication_required',
  'origin_not_allowed',
  'csrf_failed',
  'access_denied',
  'not_found',
  'state_conflict',
  'rate_limited',
  'validation_failed',
  'request_too_large',
  'temporarily_unavailable',
];

/** Every error code the API's authentication code can answer, read from its source. */
function codesInTheBackend(): string[] {
  const root = inRepository('backend', 'app');
  const found = new Set<string>();
  for (const name of readdirSync(root, { recursive: true, encoding: 'utf8' })) {
    if (!name.endsWith('.py')) continue;
    const source = readFileSync(path.join(root, name), 'utf8');
    for (const match of source.matchAll(/AuthError\(\s*"([a-z_]+)"/g)) found.add(match[1] ?? '');
    // The code of an AuthError raised without arguments; the class lives in security.py.
    if (name === 'security.py') {
      for (const match of source.matchAll(/def __init__\(self, code: str = "([a-z_]+)"/g)) found.add(match[1] ?? '');
    }
    // The codes the Google callback may put in the address of the completion page.
    if (name.replaceAll('\\', '/') === 'api/google.py') {
      const list = /CALLBACK_ERRORS = frozenset\(\s*\{([^}]*)\}/.exec(source)?.[1] ?? '';
      for (const match of list.matchAll(/"([a-z_]+)"/g)) found.add(match[1] ?? '');
    }
    if (name === 'main.py') {
      for (const match of source.matchAll(/\{"error": "([a-z_]+)"\}/g)) found.add(match[1] ?? '');
    }
  }
  return [...found].sort();
}

describe('a plan limit', () => {
  it('is named with its value and its use when the API names it, in both languages', () => {
    const limit = { limit: 'managed_links' as const, value: 500, used: 500 };
    const message = describeError(new ApiError(409, 'plan_limit_reached', null, limit), {
      plan_limit_reached: 'connections.error.plan_limit_reached',
    });
    expect(message).toEqual({ id: 'error.plan_limit_reached.managed_links', values: { value: 500, used: 500 } });
    for (const name of ['clients', 'seats', 'connections', 'managed_links'] as const) {
      expect(messages.en[`error.plan_limit_reached.${name}`]).toContain('{used, number}');
      expect(messages.ar[`error.plan_limit_reached.${name}`]).toContain('{used, number}');
    }
    expect(describeError(new ApiError(409, 'plan_limit_reached')).id).toBe('error.plan_limit_reached');
  });
});

describe('the error table', () => {
  it.each(documented)('has a sentence in both languages for %s', (code) => {
    const { id } = describeError(new ApiError(400, code));
    expect(id).not.toBe('error.unknown');
    expect(messages.en[id]).toBeTruthy();
    expect(messages.ar[id]).toBeTruthy();
  });

  it('covers every code the authentication code of the API can answer', () => {
    const codes = codesInTheBackend();
    // The scan must have found the API, or this test would pass on nothing.
    expect(codes).toEqual(expect.arrayContaining(['invalid_credentials', 'authentication_required', 'rate_limited']));
    expect(codes.length).toBeGreaterThan(12);
    const withoutSentence = codes.filter((code) => describeError(new ApiError(400, code)).id === 'error.unknown');
    expect(withoutSentence).toEqual([]);
  });

  it('says a request did not reach the API', () => {
    expect(describeError(new ApiError(0, 'network_error'))).toEqual({ id: 'error.network' });
  });

  it('names the waiting time of a rate limit only when it is known', () => {
    expect(describeError(new ApiError(429, 'rate_limited', 41))).toEqual({
      id: 'error.rate_limitedSeconds',
      values: { seconds: 41 },
    });
    expect(describeError(new ApiError(429, 'rate_limited'))).toEqual({ id: 'error.rate_limited' });
  });

  it('lets a screen use a sentence that fits its context', () => {
    const wrongPassword = new ApiError(401, 'invalid_credentials');
    expect(describeError(wrongPassword).id).toBe('signIn.error.credentials');
    expect(describeError(wrongPassword, { invalid_credentials: 'account.password.error.current' }).id).toBe(
      'account.password.error.current',
    );
  });

  it('falls back to a general sentence for an unknown code or a failure that is not from the API', () => {
    expect(describeError(new ApiError(418, 'something_new')).id).toBe('error.unknown');
    expect(describeError(new TypeError('boom')).id).toBe('error.unknown');
  });
});
