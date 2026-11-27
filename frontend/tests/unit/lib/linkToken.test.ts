import { afterEach, describe, expect, it } from 'vitest';

import { captureLinkToken, heldLinkToken, releaseLinkToken } from '@/lib/linkToken';

import { linkToken } from '../support/api';

afterEach(() => {
  releaseLinkToken('reset');
  releaseLinkToken('invitation');
  window.history.replaceState(null, '', '/');
});

const open = (address: string) => {
  window.history.replaceState({ kept: true }, '', address);
  captureLinkToken();
};

const everythingStored = () => JSON.stringify({ ...window.localStorage }) + JSON.stringify({ ...window.sessionStorage });

describe('the token of a mail link', () => {
  it('leaves the address bar at once and is kept in memory only', () => {
    open(`/auth/reset-password#token=${linkToken}`);
    expect(window.location.hash).toBe('');
    expect(window.location.href).not.toContain(linkToken);
    expect(window.location.pathname).toBe('/auth/reset-password');
    expect(heldLinkToken('reset')).toBe(linkToken);
    expect(everythingStored()).not.toContain(linkToken);
  });

  it('keeps the state the router put in the history entry', () => {
    open(`/auth/reset-password#token=${linkToken}`);
    expect(window.history.state).toEqual({ kept: true });
  });

  it('keeps a reset link and an invitation apart', () => {
    open(`/auth/accept-invitation#token=${linkToken}`);
    expect(heldLinkToken('invitation')).toBe(linkToken);
    expect(heldLinkToken('reset')).toBeNull();
  });

  it('stays held when the same page is opened again without a token', () => {
    open(`/auth/accept-invitation#token=${linkToken}`);
    open('/auth/accept-invitation');
    expect(heldLinkToken('invitation')).toBe(linkToken);
  });

  it.each([
    ['too short', 'abc'],
    ['with characters the API never issues', `${linkToken.slice(0, 40)}<>"`],
    ['badly encoded', '%E0%A4%A'],
  ])('is not kept when it is %s, and still leaves the address bar', (_what, token) => {
    open(`/auth/reset-password#token=${token}`);
    expect(heldLinkToken('reset')).toBeNull();
    expect(window.location.hash).toBe('');
  });

  it('is left alone on a page that takes no token', () => {
    open(`/account#token=${linkToken}`);
    expect(heldLinkToken('reset')).toBeNull();
    expect(heldLinkToken('invitation')).toBeNull();
  });

  it('is forgotten once it was used', () => {
    open(`/auth/reset-password#token=${linkToken}`);
    releaseLinkToken('reset');
    expect(heldLinkToken('reset')).toBeNull();
  });
});
