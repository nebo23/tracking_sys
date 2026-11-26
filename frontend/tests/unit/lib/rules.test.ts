import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { isSecureAddress } from '@/lib/browser';
import { initials } from '@/lib/initials';
import { safeNext } from '@/lib/safeNext';
import {
  CODE_LENGTH,
  codeError,
  EMAIL_MAX,
  emailError,
  NAME_MAX,
  nameError,
  newPasswordError,
  PASSWORD_MAX,
  PASSWORD_MIN,
} from '@/lib/validation';

import { inRepository } from '../support/files';

interface Property {
  minLength?: number;
  maxLength?: number;
  pattern?: string;
}

const contract = JSON.parse(readFileSync(inRepository('contracts', 'openapi.json'), 'utf8')) as { components: { schemas: Record<string, { properties: Record<string, Property> }> } };

const property = (schema: string, name: string): Property => {
  const found = contract.components.schemas[schema]?.properties[name];
  if (!found) throw new Error(`The contract has no ${schema}.${name}.`);
  return found;
};

describe('the field rules match the API contract', () => {
  it.each([
    ['Registration', 'password'],
    ['PasswordReset', 'password'],
    ['PasswordChange', 'new_password'],
  ])('a new password in %s.%s', (schema, name) => {
    expect(property(schema, name)).toMatchObject({ minLength: PASSWORD_MIN, maxLength: PASSWORD_MAX });
  });

  it.each([
    ['Registration', 'display_name'],
    ['AgencyInput', 'name'],
  ])('a name in %s.%s', (schema, name) => {
    expect(property(schema, name).maxLength).toBe(NAME_MAX);
  });

  it('an email address', () => {
    expect(property('Registration', 'email').maxLength).toBe(EMAIL_MAX);
    expect(property('Login', 'email').maxLength).toBe(EMAIL_MAX);
  });

  it('a verification code', () => {
    expect(property('VerificationCode', 'code').pattern).toBe(`^[0-9]{${CODE_LENGTH}}$`);
  });
});

describe('the field rules', () => {
  it('accept a password from 15 to 128 characters', () => {
    expect(newPasswordError('')).toBe('field.error.required');
    expect(newPasswordError('a'.repeat(PASSWORD_MIN - 1))).toBe('field.error.passwordShort');
    expect(newPasswordError('a'.repeat(PASSWORD_MIN))).toBeNull();
    expect(newPasswordError('a'.repeat(PASSWORD_MAX))).toBeNull();
    expect(newPasswordError('a'.repeat(PASSWORD_MAX + 1))).toBe('field.error.passwordLong');
  });

  it('do not trim a password: spaces are part of it', () => {
    expect(newPasswordError(' '.repeat(PASSWORD_MIN))).toBeNull();
  });

  it('ask for a complete email address', () => {
    expect(emailError('  ')).toBe('field.error.required');
    expect(emailError('mona')).toBe('field.error.email');
    expect(emailError('mona@lumen')).toBe('field.error.email');
    expect(emailError('mona @lumen.example')).toBe('field.error.email');
    expect(emailError(' mona@lumen.example ')).toBeNull();
    expect(emailError(`${'a'.repeat(EMAIL_MAX)}@lumen.example`)).toBe('field.error.email');
  });

  it('ask for a name that is not only spaces', () => {
    expect(nameError('   ')).toBe('field.error.required');
    expect(nameError('منى حسن')).toBeNull();
    expect(nameError('a'.repeat(NAME_MAX + 1))).toBe('field.error.nameLong');
  });

  it('ask for all six digits of a code', () => {
    expect(codeError('12345')).toBe('verify.error.incomplete');
    expect(codeError('12345a')).toBe('verify.error.incomplete');
    expect(codeError('1234567')).toBe('verify.error.incomplete');
    expect(codeError('012345')).toBeNull();
  });
});

describe('the place to continue to after sign-in', () => {
  it.each([
    ['/account', '/account'],
    ['/account?notice=googleLinked', '/account?notice=googleLinked'],
    ['/auth/accept-invitation', '/auth/accept-invitation'],
  ])('keeps a path of this application: %s', (next, expected) => {
    expect(safeNext(next)).toBe(expected);
  });

  it.each([
    ['another site', 'https://evil.example/account'],
    ['an address without a scheme', '//evil.example/account'],
    ['a backslash trick', '/\\evil.example'],
    ['a script', 'javascript:alert(1)'],
    // The address parser drops a tab, which would turn this into an address on another site.
    ['a tab that hides a second slash', '/' + String.fromCharCode(9) + '/evil.example/account'],
    ['a relative path', 'account'],
    ['nothing', ''],
    ['a number', 42],
    ['an absent value', undefined],
    ['the sign-in screen', '/sign-in?next=/account'],
    ['the register screen', '/register'],
  ])('answers the start page for %s', (_what, next) => {
    expect(safeNext(next)).toBe('/');
  });

  it('never carries a fragment along', () => {
    expect(safeNext('/account#token=secret')).toBe('/account');
  });
});

describe('small helpers', () => {
  it('make initials from the first two words, in any script', () => {
    expect(initials('Mona Hassan')).toBe('MH');
    expect(initials('  lumen   studio  berlin ')).toBe('LS');
    expect(initials('Olive')).toBe('O');
    expect(initials('منى حسن')).toBe('مح');
    expect(initials('')).toBe('');
  });

  it('follow an address from the API only when it is https', () => {
    expect(isSecureAddress('https://accounts.google.com/o/oauth2/v2/auth?state=x')).toBe(true);
    expect(isSecureAddress('http://accounts.google.com/')).toBe(false);
    expect(isSecureAddress('javascript:alert(1)')).toBe(false);
    expect(isSecureAddress('/account')).toBe(false);
    expect(isSecureAddress('')).toBe(false);
  });
});
