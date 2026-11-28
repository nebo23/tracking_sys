import type { DestinationSite, LinkDomain, ManagedLink } from '@/api/links';
import { shortLinkOrigin } from '@/app/config';
import type { MessageId } from '@/i18n';

// The rules of the API for managed links (backend/app/links/policy.py), checked before a request
// is sent so that a person learns which rule a value breaks: the API answers a broken rule with
// one general code. The API checks everything again and decides. A unit test compares these
// lists with the backend source.

export const SLUG_MAX = 64;
export const LABEL_MAX = 100;
export const CONTENT_LABEL_MAX = 64;
export const CONTENT_CODE_MAX = 128;
export const HOSTNAME_MAX = 253;
export const SITE_MAX = 200;
export const DESTINATION_MAX = 2048;
export const QUERY_NAMES_MAX = 20;

const SLUG = /^[a-z0-9][a-z0-9-]{2,63}$/;
const CODE = /^[A-Za-z0-9_.-]{1,64}$/;
const CONTENT_CODE = /^[A-Za-z0-9_.:-]{1,128}$/;
const QUERY_NAME = /^[a-z0-9_]{1,64}$/;
const LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const PRINTABLE = /^[\x21-\x7e]+$/;
// Encoded characters that would change a path or a value once decoded, and a lone percent sign.
const AMBIGUOUS = /%(?:2[EeFf5]|5[Cc]|[01][0-9A-Fa-f]|7[Ff])/;
const LONE_PERCENT = /%(?![0-9A-Fa-f]{2})/;
const DOT_SEGMENT = /(?:^|\/)\.{1,2}(?:\/|$)/;

/** Short paths that a link may not take, now or in a later specification. */
export const RESERVED_SLUGS: ReadonlySet<string> = new Set([
  'admin',
  'api',
  'app',
  'assets',
  'auth',
  'collect',
  'docs',
  'health',
  'help',
  'login',
  'logout',
  'openapi',
  'redoc',
  'static',
  'status',
  'support',
  'tracker',
  'webhooks',
  'www',
]);

/** The campaign values a link or a template may set (the utm_ names the collector keeps). */
export const UTM_NAMES = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'utm_id'] as const;
export type UtmName = (typeof UTM_NAMES)[number];

/** Click identifiers of the advertising platforms. A destination site may not keep them as its own. */
export const CLICK_NAMES: ReadonlySet<string> = new Set(['gclid', 'gbraid', 'wbraid', 'fbclid', 'msclkid', 'ttclid', 'li_fat_id', 'twclid']);

/** The name under which the issued address carries the link. */
export const LINK_PARAMETER = 'ts_link';

// Words of a query name that would carry a credential or a person's identifier.
const SENSITIVE_WORDS = new Set([
  'token',
  'sig',
  'signature',
  'key',
  'apikey',
  'auth',
  'session',
  'sid',
  'secret',
  'password',
  'passwd',
  'pwd',
  'email',
  'mail',
  'phone',
  'tel',
  'user',
  'uid',
  'customer',
  'account',
  'credential',
  'otp',
  'card',
]);
const SENSITIVE_PARTS = ['token', 'secret', 'passw', 'email', 'signature'];

export function slugError(slug: string): MessageId | null {
  if (slug === '') return 'field.error.required';
  if (!SLUG.test(slug)) return 'links.rule.slug';
  return RESERVED_SLUGS.has(slug) ? 'links.rule.slugReserved' : null;
}

/** A campaign code or a UTM value: letters, digits, dot, hyphen and underscore, at most 64. */
export const isCode = (value: string): boolean => CODE.test(value);

export function codeError(value: string): MessageId | null {
  if (value === '') return 'field.error.required';
  return isCode(value) ? null : 'links.rule.code';
}

export function contentCodeError(value: string): MessageId | null {
  if (value === '') return 'field.error.required';
  return CONTENT_CODE.test(value) ? null : 'links.rule.contentCode';
}

export function labelError(value: string, maximum: number): MessageId | null {
  const label = value.trim();
  if (label === '') return 'field.error.required';
  return label.length > maximum ? 'links.rule.labelLong' : null;
}

/** UTM values as a person typed them: empty ones are left out, the others must be codes. */
export function utmValues(values: Partial<Record<UtmName, string>>): { values: Record<string, string>; invalid: UtmName[] } {
  const kept: Record<string, string> = {};
  const invalid: UtmName[] = [];
  for (const name of UTM_NAMES) {
    const value = values[name]?.trim() ?? '';
    if (value === '') continue;
    if (isCode(value)) kept[name] = value;
    else invalid.push(name);
  }
  return { values: kept, invalid };
}

export function queryNamesError(names: readonly string[]): MessageId | null {
  if (names.length > QUERY_NAMES_MAX) return 'links.rule.queryNamesMany';
  if (new Set(names).size !== names.length) return 'links.rule.queryNamesTwice';
  for (const name of names) {
    if (!QUERY_NAME.test(name)) return 'links.rule.queryName';
    if ((UTM_NAMES as readonly string[]).includes(name) || CLICK_NAMES.has(name) || name === LINK_PARAMETER) {
      return 'links.rule.queryNameReserved';
    }
    const words = new Set([...name.split('_'), name.replaceAll('_', '')]);
    if ([...words].some((word) => SENSITIVE_WORDS.has(word)) || SENSITIVE_PARTS.some((part) => name.includes(part))) {
      return 'links.rule.queryNameSensitive';
    }
  }
  return null;
}

/** The names typed into one field, separated by commas or spaces. */
export const splitNames = (text: string): string[] =>
  text
    .split(/[\s,]+/)
    .map((name) => name.trim())
    .filter(Boolean);

function hostnameError(host: string): MessageId | null {
  if (host === '' || host.length > HOSTNAME_MAX || host.endsWith('.') || host.includes('*')) return 'links.rule.hostname';
  if (/^[0-9.]+$/.test(host) || host.includes(':')) return 'links.rule.hostname';
  const labels = host.split('.');
  if (labels.length < 2 || !labels.every((label) => LABEL.test(label)) || /^[0-9]+$/.test(labels.at(-1) ?? '')) {
    return 'links.rule.hostname';
  }
  const internal = ['localhost', 'local', 'internal', 'intranet', 'lan', 'home.arpa', 'corp', 'private', 'arpa', 'onion', 'invalid'];
  return internal.some((suffix) => host === suffix || host.endsWith(`.${suffix}`)) ? 'links.rule.hostnameInternal' : null;
}

/** A custom domain as the API expects it: a lowercase public hostname. */
export function domainError(value: string): MessageId | null {
  const host = value.trim();
  if (host === '') return 'field.error.required';
  return hostnameError(host);
}

/**
 * A destination site: an HTTPS origin on the default port, such as https://shop.example.test,
 * with no path, query or fragment. Returns the canonical text the API will store.
 */
export function siteOrigin(value: string): { origin: string | null; error: MessageId | null } {
  const text = value.trim().replace(/\/$/, '');
  if (text === '') return { origin: null, error: 'field.error.required' };
  const match = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#@\\]+)$/.exec(text);
  if (!match || text.length > SITE_MAX || !PRINTABLE.test(text)) return { origin: null, error: 'links.rule.site' };
  const [, scheme = '', authority = ''] = match;
  if (scheme.toLowerCase() !== 'https') return { origin: null, error: 'links.rule.siteHttps' };
  const [host = '', port, ...rest] = authority.toLowerCase().split(':');
  if (rest.length > 0 || (port !== undefined && port !== '443')) return { origin: null, error: 'links.rule.site' };
  const error = hostnameError(host);
  return error ? { origin: null, error } : { origin: `https://${host}`, error: null };
}

/**
 * Checks a destination address against the client's active destination sites, with the rules of
 * the API: printable characters only, no fragment or credentials, an absolute path without dot
 * segments, and only the site's own query names and UTM values in its query.
 */
export function destinationError(value: string, sites: readonly DestinationSite[]): MessageId | null {
  const text = value.trim();
  if (text === '') return 'field.error.required';
  if (text.length > DESTINATION_MAX || !PRINTABLE.test(text) || text.includes('\\') || text.includes('#')) return 'links.rule.destination';
  if (LONE_PERCENT.test(text) || AMBIGUOUS.test(text)) return 'links.rule.destination';
  const match = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#]*)([^?#]*)(?:\?([^#]*))?$/.exec(text);
  if (!match) return 'links.rule.destination';
  const [, scheme = '', authority = '', rawPath = '', query] = match;
  if (authority.includes('@') || authority === '') return 'links.rule.destination';
  const origin = siteOrigin(`${scheme}://${authority}`).origin;
  const site = sites.find((item) => item.status === 'active' && item.origin === origin);
  if (!site) return 'links.rule.destinationSite';
  const path = rawPath === '' ? '/' : rawPath;
  if (!path.startsWith('/') || path.startsWith('//') || DOT_SEGMENT.test(path) || path.includes('@')) return 'links.rule.destination';
  if (query === undefined || query === '') return null;
  const seen = new Set<string>();
  for (const pair of query.split('&')) {
    const [name = '', ...values] = pair.split('=');
    if (values.length === 0 || !QUERY_NAME.test(name) || seen.has(name)) return 'links.rule.destinationQuery';
    seen.add(name);
    if (name === LINK_PARAMETER) return 'links.rule.destinationQuery';
    if (!site.query_names.includes(name) && !(UTM_NAMES as readonly string[]).includes(name)) return 'links.rule.destinationQueryName';
    if (!isCode(values.join('='))) return 'links.rule.destinationQuery';
  }
  return null;
}

/** The address a visitor opens: the link's custom domain, or the platform host of the short links. */
export function shortAddress(slug: string, domain: Pick<LinkDomain, 'hostname'> | null | undefined): string {
  return `${domain ? `https://${domain.hostname}` : shortLinkOrigin}/r/${slug}`;
}

/** The short address as it reads in a list: without its scheme. */
export const readableAddress = (address: string): string => address.replace(/^https?:\/\//, '');

export type LinkState = 'active' | 'paused' | 'expired';

/** A paused link is paused whatever its expiry; an active one stops working when its time has passed. */
export function linkState(link: Pick<ManagedLink, 'status' | 'expires_at'>, now: number): LinkState {
  if (link.status !== 'active') return 'paused';
  return link.expires_at && new Date(link.expires_at).getTime() <= now ? 'expired' : 'active';
}

export type DomainState = 'off' | 'verified' | 'recheck' | 'failed' | 'waiting' | 'expired' | 'unverified';

/** What a domain's record says, in the order a person needs to act on it (plan section 4.5). */
export function domainState(domain: LinkDomain, now: number): DomainState {
  if (domain.status === 'disabled') return 'off';
  const current = (moment: string | null | undefined) => (moment ? new Date(moment).getTime() > now : false);
  if (domain.failure_code) return 'failed';
  if (domain.status === 'verified') return current(domain.verification_expires_at) ? 'verified' : 'recheck';
  if (domain.challenge_expires_at) return current(domain.challenge_expires_at) ? 'waiting' : 'expired';
  return 'unverified';
}

/** The failure codes of a domain check (backend/app/links/verification.py and services/links.py). */
export const domainFailures = [
  'ownership_missing',
  'routing_mismatch',
  'address_not_allowed',
  'tls_invalid',
  'challenge_expired',
  'host_conflict',
  'verification_unavailable',
] as const;

export function domainFailureMessage(code: string | null | undefined): MessageId {
  const known = domainFailures.find((item) => item === code);
  return known ? `links.domain.failure.${known}` : 'links.domain.failure.other';
}

/** The local date and time of a field of type datetime-local, as the moment the API expects. */
export function moment(localValue: string): string | null {
  if (localValue === '') return null;
  const time = new Date(localValue);
  return Number.isNaN(time.getTime()) ? null : time.toISOString();
}

/** A moment as a field of type datetime-local shows it, in the person's own time zone. */
export function localValue(moment: string | null | undefined): string {
  if (!moment) return '';
  const time = new Date(moment);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${time.getFullYear()}-${pad(time.getMonth() + 1)}-${pad(time.getDate())}T${pad(time.getHours())}:${pad(time.getMinutes())}`;
}
