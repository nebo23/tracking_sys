// Browser-side mirror of the specification 003/004 minimization contracts (D-025, D-027).
//
// These functions reproduce app.privacy.collection and the URL rules of
// app.collection.contract so the tracker removes values before they leave the browser
// (003 case M4). The server applies the same rules again regardless of tracker version.
// Shared fixtures in test/fixtures/parity.json are checked by both the Python and the
// JavaScript suites. Pattern checks recognize known forms of email addresses and card
// numbers only; they are not general personal-data detection.

const cp = (value) => String.fromCodePoint(value);
const span = (first, last) => `${cp(first)}-${cp(last)}`;

// The characters Python's re module matches with \s in str patterns (Unicode 15). JavaScript's
// own \s differs slightly, so the set is spelled out to keep both sides identical.
const WHITESPACE = [
  span(0x09, 0x0d),
  span(0x1c, 0x20),
  cp(0x85),
  cp(0xa0),
  cp(0x1680),
  span(0x2000, 0x200a),
  cp(0x2028),
  cp(0x2029),
  cp(0x202f),
  cp(0x205f),
  cp(0x3000),
].join("");
// Card digit-group separators: whitespace, hyphen-minus, Unicode hyphens and dashes, the minus
// sign, and the fullwidth hyphen-minus (app.privacy.collection._SEPARATOR).
const SEPARATOR = `[${WHITESPACE}\\-${span(0x2010, 0x2015)}${cp(0x2212)}${cp(0xff0d)}]`;
const DIGIT_RUN = new RegExp(`\\p{Nd}+(?:${SEPARATOR}+\\p{Nd}+)*`, "gu");
const DIGIT_GROUP = /\p{Nd}+/gu;
const DECIMAL = /\p{Nd}/u;
const EMAIL_LIKE = new RegExp(`[^/@${WHITESPACE}]+@[^/@${WHITESPACE}]+\\.[^/@${WHITESPACE}]+`, "u");
const SPLIT_WHITESPACE = new RegExp(`[${WHITESPACE}]+`, "u");
const TOKENS = /[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\p{Nd}+/gu;
const C0_OR_SPACE = new RegExp(`^[${span(0x00, 0x20)}]+`, "u");
const UNSAFE = /[\t\r\n]/g;
const ASCII_RUN = new RegExp(`[${span(0x00, 0x7f)}]+`, "gu");
const SCHEME_CHARS = /^[A-Za-z0-9+.-]+$/;
const HEX_PAIR = /^[0-9A-Fa-f]{2}/;
const UNRESERVED = /^[A-Za-z0-9_.~-]$/;

export const ANALYTICS = "analytics.first_party";
export const ATTRIBUTION = "attribution";
export const MAX_TEXT = 2048;
export const CODE = /^[A-Za-z0-9_.-]{1,64}$/;
export const CAMPAIGN_PARAMETERS = new Set([
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
  "utm_id",
]);
export const CLICK_PARAMETERS = new Set([
  "gclid",
  "gbraid",
  "wbraid",
  "fbclid",
  "msclkid",
  "ttclid",
  "li_fat_id",
  "twclid",
]);
const NEVER_COLLECT_TYPES = new Set(["password", "hidden"]);
const NEVER_COLLECT_AUTOCOMPLETE = new Set(["current-password", "new-password", "one-time-code"]);
const SENSITIVE_TOKENS = new Set([
  "password",
  "passwd",
  "pwd",
  "passcode",
  "pin",
  "otp",
  "cvv",
  "cvv2",
  "cvc",
  "csc",
  "card",
  "cardnumber",
  "ccnum",
  "ccnumber",
  "creditcard",
  "securitycode",
]);

// A refusal with a closed reason code, as in app.collection.contract.Rejected.
export class Rejected extends Error {
  constructor(reason) {
    super(reason);
    this.reason = reason;
  }
}

const codePoints = (text) => [...text].length;
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: false });

// Value of one decimal digit of any script: digits of a script are consecutive code points
// starting at zero, so the offset from the start of its run of decimal digits, modulo ten,
// is the digit value (Python's int() of the character).
function digitValue(character) {
  const point = character.codePointAt(0);
  let start = point;
  for (let step = 0; step < 60 && start > 0 && DECIMAL.test(cp(start - 1)); step += 1) {
    start -= 1;
  }
  return (point - start) % 10;
}

function luhnValid(digits) {
  let total = 0;
  digits.forEach((digit, index) => {
    let value = digit;
    if ((digits.length - 1 - index) % 2 === 1) {
      value = value > 4 ? value * 2 - 9 : value * 2;
    }
    total += value;
  });
  return total % 10 === 0;
}

// True when text contains a Luhn-valid card number of 13-19 digits formed by consecutive digit
// groups of one run (app.privacy.collection.contains_card_number).
export function containsCardNumber(value) {
  for (const run of String(value).matchAll(DIGIT_RUN)) {
    const groups = run[0].match(DIGIT_GROUP).map((group) => [...group].map(digitValue));
    for (let start = 0; start < groups.length; start += 1) {
      let digits = [];
      for (const group of groups.slice(start)) {
        digits = digits.concat(group);
        if (digits.length > 19) break;
        if (digits.length >= 13 && luhnValid(digits)) return true;
      }
    }
  }
  return false;
}

// urllib.parse.unquote with UTF-8 and replacement of invalid sequences.
export function unquote(text) {
  if (!text.includes("%")) return text;
  return text.replace(ASCII_RUN, (run) => {
    const parts = run.split("%");
    const bytes = [...encoder.encode(parts[0])];
    for (const item of parts.slice(1)) {
      if (HEX_PAIR.test(item)) {
        bytes.push(Number.parseInt(item.slice(0, 2), 16), ...encoder.encode(item.slice(2)));
      } else {
        bytes.push(0x25, ...encoder.encode(item));
      }
    }
    return decoder.decode(new Uint8Array(bytes));
  });
}

// urllib.parse.quote_plus with an empty safe set.
function quotePlus(text) {
  let result = "";
  for (const character of text) {
    if (character === " ") {
      result += "+";
    } else if (UNRESERVED.test(character)) {
      result += character;
    } else {
      for (const byte of encoder.encode(character)) {
        result += `%${byte.toString(16).toUpperCase().padStart(2, "0")}`;
      }
    }
  }
  return result;
}

export function urlencode(pairs) {
  return pairs.map(([name, value]) => `${quotePlus(name)}=${quotePlus(value)}`).join("&");
}

// urllib.parse.parse_qsl with keep_blank_values=True.
export function parseQsl(query) {
  const pairs = [];
  for (const item of query.split("&")) {
    if (!item) continue;
    const index = item.indexOf("=");
    const name = index < 0 ? item : item.slice(0, index);
    const value = index < 0 ? "" : item.slice(index + 1);
    pairs.push([unquote(name.replaceAll("+", " ")), unquote(value.replaceAll("+", " "))]);
  }
  return pairs;
}

function checkNetloc(netloc) {
  if (!netloc || /^[\x00-\x7f]*$/.test(netloc)) return;
  const stripped = netloc.replace(/[@:#?]/g, "");
  const normalized = stripped.normalize("NFKC");
  if (stripped === normalized) return;
  for (const character of "/?#@:") {
    if (normalized.includes(character)) throw new Rejected("url_not_allowed");
  }
}

// urllib.parse.urlsplit (Python 3.12) plus its hostname, port, and username properties. An
// invalid port or bracketed host raises Rejected, as Python's ValueError does in the contract.
export function urlsplit(input) {
  let url = String(input).replace(C0_OR_SPACE, "").replace(UNSAFE, "");
  let scheme = "";
  let netloc = "";
  let query = "";
  let fragment = "";
  const colon = url.indexOf(":");
  if (colon > 0 && /^[A-Za-z]/.test(url) && SCHEME_CHARS.test(url.slice(0, colon))) {
    scheme = url.slice(0, colon).toLowerCase();
    url = url.slice(colon + 1);
  }
  if (url.startsWith("//")) {
    let end = url.length;
    for (const delimiter of "/?#") {
      const found = url.indexOf(delimiter, 2);
      if (found >= 0) end = Math.min(end, found);
    }
    netloc = url.slice(2, end);
    url = url.slice(end);
    if (netloc.includes("[") !== netloc.includes("]")) throw new Rejected("url_not_allowed");
  }
  const hash = url.indexOf("#");
  if (hash >= 0) {
    fragment = url.slice(hash + 1);
    url = url.slice(0, hash);
  }
  const mark = url.indexOf("?");
  if (mark >= 0) {
    query = url.slice(mark + 1);
    url = url.slice(0, mark);
  }
  checkNetloc(netloc);
  const at = netloc.lastIndexOf("@");
  const userinfo = at >= 0 ? netloc.slice(0, at) : null;
  const hostinfo = at >= 0 ? netloc.slice(at + 1) : netloc;
  let hostname;
  let port;
  const open = hostinfo.indexOf("[");
  if (open >= 0) {
    const bracketed = hostinfo.slice(open + 1);
    const close = bracketed.indexOf("]");
    hostname = close >= 0 ? bracketed.slice(0, close) : bracketed;
    const rest = close >= 0 ? bracketed.slice(close + 1) : "";
    const portColon = rest.indexOf(":");
    port = portColon >= 0 ? rest.slice(portColon + 1) : "";
    if (!/^[0-9A-Fa-f:.]+(%.*)?$/.test(hostname) && !/^v[0-9A-Fa-f]+\..+$/i.test(hostname)) {
      throw new Rejected("url_not_allowed");
    }
  } else {
    const portColon = hostinfo.indexOf(":");
    hostname = portColon >= 0 ? hostinfo.slice(0, portColon) : hostinfo;
    port = portColon >= 0 ? hostinfo.slice(portColon + 1) : "";
  }
  let portNumber = null;
  if (port) {
    if (!/^[0-9]+$/.test(port)) throw new Rejected("url_not_allowed");
    portNumber = Number.parseInt(port, 10);
    if (portNumber > 65535) throw new Rejected("url_not_allowed");
  }
  let host = null;
  if (hostname) {
    const percent = hostname.indexOf("%");
    host =
      percent >= 0
        ? hostname.slice(0, percent).toLowerCase() + hostname.slice(percent)
        : hostname.toLowerCase();
  }
  const username = userinfo === null ? null : userinfo.split(":")[0];
  return { scheme, netloc, path: url, query, fragment, hostname: host, port: portNumber, username };
}

// urllib.parse.urlunsplit for the URLs produced here.
function urlunsplit(scheme, netloc, path, query) {
  let url = path;
  if (netloc || (scheme && ["http", "https"].includes(scheme) && !url.startsWith("//"))) {
    if (url && !url.startsWith("/")) url = `/${url}`;
    url = `//${netloc}${url}`;
  }
  if (scheme) url = `${scheme}:${url}`;
  if (query) url = `${url}?${query}`;
  return url;
}

function httpParts(url) {
  const parts = urlsplit(url);
  if (!["http", "https"].includes(parts.scheme) || !parts.hostname) {
    throw new Rejected("url_not_allowed");
  }
  return parts;
}

// app.collection.contract._prohibited: an email-like value or a card number, also after one
// further level of percent-decoding.
export function hasProhibitedValue(decoded) {
  return [decoded, unquote(decoded)].some(
    (text) => EMAIL_LIKE.test(text) || containsCardNumber(text),
  );
}

// app.privacy.collection.minimize_url: keep scheme, host, port, path and allowlisted query
// parameters. Returns [minimized URL, number of removed components].
export function minimizeUrl(url, allowed) {
  const parts = urlsplit(url);
  const pairs = parseQsl(parts.query);
  const kept = pairs.filter(([name]) => allowed.has(name));
  let netloc = parts.hostname || "";
  if (parts.port !== null) netloc = `${netloc}:${parts.port}`;
  const minimized = urlunsplit(parts.scheme, netloc, parts.path, urlencode(kept));
  const removed =
    pairs.length - kept.length + Number(Boolean(parts.fragment)) + Number(Boolean(parts.username));
  return [minimized, removed];
}

// app.collection.contract.minimize_page_url: campaign parameters with analytics, click
// identifiers only with attribution as well, prohibited values removed or rejected.
// Returns { url, dropped } where dropped counts closed reason codes.
export function minimizePageUrl(url, granted) {
  const parts = httpParts(url);
  if (hasProhibitedValue(unquote(parts.path))) throw new Rejected("url_identifier");
  const allowed = new Set();
  if (granted.has(ANALYTICS)) {
    for (const name of CAMPAIGN_PARAMETERS) allowed.add(name);
    if (granted.has(ATTRIBUTION)) for (const name of CLICK_PARAMETERS) allowed.add(name);
  }
  const dropped = {};
  const add = (reason, amount) => {
    dropped[reason] = (dropped[reason] || 0) + amount;
  };
  const pairs = parseQsl(parts.query);
  const clicks = pairs.filter(([name]) => CLICK_PARAMETERS.has(name) && !allowed.has(name)).length;
  if (clicks) add("click_identifier", clicks);
  let [minimized, removed] = minimizeUrl(url, allowed);
  if (removed - clicks) add("url_component", removed - clicks);
  const kept = urlsplit(minimized);
  const retained = parseQsl(kept.query);
  const safe = retained.filter(([, value]) => !hasProhibitedValue(value));
  if (safe.length < retained.length) {
    add("sensitive_query_value", retained.length - safe.length);
    minimized = urlunsplit(kept.scheme, kept.netloc, kept.path, urlencode(safe));
  }
  if (codePoints(minimized) > MAX_TEXT) throw new Rejected("url_not_allowed");
  return { url: minimized, dropped };
}

// app.collection.contract.origin_only: scheme, host and port of a referrer.
export function originOnly(url) {
  const parts = httpParts(url);
  let host = parts.hostname || "";
  if (host.includes(":")) host = `[${host}]`;
  return `${parts.scheme}://${host}${parts.port !== null ? `:${parts.port}` : ""}`;
}

function tokens(text) {
  const parts = (String(text).match(TOKENS) || []).map((part) => part.toLowerCase());
  return parts.length ? new Set([...parts, parts.join("")]) : new Set();
}

// app.privacy.collection.never_collect_reason for one field descriptor
// { name, input_type, autocomplete, label, element_id, in_payment_frame }.
export function neverCollectReason(item) {
  if (item.in_payment_frame) return "payment_frame";
  if (NEVER_COLLECT_TYPES.has(String(item.input_type ?? "text").trim().toLowerCase())) {
    return "never_collect_type";
  }
  const autocomplete = String(item.autocomplete ?? "")
    .toLowerCase()
    .split(SPLIT_WHITESPACE)
    .filter(Boolean);
  if (autocomplete.some((token) => NEVER_COLLECT_AUTOCOMPLETE.has(token) || token.startsWith("cc-"))) {
    return "never_collect_autocomplete";
  }
  for (const text of [item.name ?? "", item.element_id ?? "", item.label ?? ""]) {
    for (const token of tokens(text)) {
      if (SENSITIVE_TOKENS.has(token)) return "sensitive_field_name";
    }
  }
  return null;
}

// The value kept for one registered field after the card rule and its 004 class
// (app.collection.contract.sanitize_form), or undefined when it must not be sent.
export function sanitizeFieldValue(field, value) {
  if (value === undefined || value === null) return undefined;
  const text = String(value);
  if (containsCardNumber(text)) return undefined;
  if (field.data_class === "form.option") {
    return (field.options || []).includes(text) ? text : undefined;
  }
  if (field.data_class === "form.code") return CODE.test(text) ? text : undefined;
  if (field.data_class === "form.quantity") {
    if (!/^[0-9]{1,7}$/.test(text)) return undefined;
    const number = Number.parseInt(text, 10);
    return number <= 1000000 ? number : undefined;
  }
  return undefined;
}
