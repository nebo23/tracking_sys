const entryPages = /^\/(sign-in|register|verify-email|forgot-password)(?:[/?#]|$)/;

/**
 * The place to continue to after sign-in. Only a path inside this application is accepted;
 * an address on another site, a protocol-relative address or an entry page becomes "/".
 */
export function safeNext(next: unknown): string {
  if (typeof next !== 'string' || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return '/';
  try {
    const target = new URL(next, window.location.origin);
    if (target.origin !== window.location.origin) return '/';
    const path = target.pathname + target.search;
    return entryPages.test(path) ? '/' : path;
  } catch {
    return '/';
  }
}
