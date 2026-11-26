import type { MessageId } from '@/i18n';

// The limits of the API contract (contracts/openapi.json: Registration, PasswordReset,
// PasswordChange, AgencyInput). A unit test compares these numbers with the contract.
export const PASSWORD_MIN = 15;
export const PASSWORD_MAX = 128;
export const NAME_MAX = 200;
// ServiceKeyInput: the name of a key.
export const KEY_NAME_MAX = 100;
export const EMAIL_MAX = 320;
export const CODE_LENGTH = 6;

const completeAddress = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function emailError(value: string): MessageId | null {
  const email = value.trim();
  if (email === '') return 'field.error.required';
  return completeAddress.test(email) && email.length <= EMAIL_MAX ? null : 'field.error.email';
}

export function newPasswordError(value: string): MessageId | null {
  if (value === '') return 'field.error.required';
  if (value.length < PASSWORD_MIN) return 'field.error.passwordShort';
  return value.length > PASSWORD_MAX ? 'field.error.passwordLong' : null;
}

export function nameError(value: string): MessageId | null {
  const name = value.trim();
  if (name === '') return 'field.error.required';
  return name.length > NAME_MAX ? 'field.error.nameLong' : null;
}

export const requiredError = (value: string): MessageId | null => (value === '' ? 'field.error.required' : null);

export const codeError = (value: string): MessageId | null =>
  new RegExp(`^[0-9]{${CODE_LENGTH}}$`).test(value) ? null : 'verify.error.incomplete';
