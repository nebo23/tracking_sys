// First-party website tracker (specification 005-D, D-033).
//
// A self-hosted native ES module with no runtime dependency. It connects a client website to
// the specification 004 public collection routes under J1 strict opt-in:
//
// - Before an explicit grant (or a host-confirmed resume) it reads no storage, URL, referrer or
//   form value, creates no identifier, sends nothing and keeps no event backlog.
// - A purpose is effective only while all of these hold: the collector reports it granted and
//   its server expiry has not passed; the host (the visitor's latest choice given to grant,
//   resume or withdraw) still allows it; Global Privacy Control does not restrict it; and the
//   fixed local lifetime has not ended. Every capture and every send re-evaluates this, and
//   every queued event records each purpose its serialized bytes depend on (analytics, plus
//   attribution when a URL keeps a click identifier), so a narrowing drops affected events.
// - grant() records the visitor's explicit choice once; resume() only reads the stored token
//   and the server's current state (POST consent-state) and never recreates or renews consent.
//   Narrowing by the host takes effect synchronously; late responses can never widen it.
// - withdraw() and erase() stop local collection immediately and are serialized after any
//   pending consent request. A grant response is reconciled per purpose with the latest
//   choices, so a partial withdrawal leaves the other purposes untouched.
// - The subject token, granted-purpose snapshot and a fixed local expiry (at most 24 hours from
//   first storage, never extended) live in sessionStorage only after permission, with an
//   in-memory fallback. No background request uses a token past that lifetime.
// - URL and form minimization runs in the browser before transmission (./minimize.js) and again
//   on the server. Only explicitly configured option/code/quantity fields are read, after the
//   never-collect rules have excluded their controls.
// - Events go one per request in a bounded in-memory queue (20 events, 128 KiB, 60 seconds),
//   at most three attempts, honoring readable Retry-After; each request is aborted when its
//   event's lifetime ends. A 202 is a generic acknowledgement, not proof of storage. Tracking
//   failures never block navigation or form submission.

import {
  ANALYTICS,
  ATTRIBUTION,
  CLICK_PARAMETERS,
  MAX_TEXT,
  Rejected,
  minimizePageUrl,
  neverCollectReason,
  originOnly,
  parseQsl,
  sanitizeFieldValue,
  urlsplit,
} from "./minimize.js";

export const VERSION = "0.5.1";
export const PURPOSES = Object.freeze([
  "analytics.first_party",
  "attribution",
  "identity_link",
  "ads.measurement",
  "ads.personalization",
  "sale_or_share",
]);
// Purposes a Global Privacy Control signal may only deny (003 GPC_PURPOSES).
export const GPC_PURPOSES = Object.freeze(["sale_or_share", "ads.measurement", "ads.personalization"]);
export const LIMITS = Object.freeze({
  queueEvents: 20,
  queueBytes: 128 * 1024,
  eventTtlMs: 60_000,
  maxAttempts: 3,
  bodyBytes: 16 * 1024,
  keepaliveBytes: 60 * 1024,
  refreshMs: 60_000,
  refreshLeadMs: 5_000,
  localLifetimeMs: 24 * 60 * 60 * 1000,
  retryDelaysMs: [1_000, 4_000],
});
const CHOICES = new Set(["granted", "denied", "withdrawn"]);
const PUBLIC_KEY = /^pk_[A-Za-z0-9_-]{43}$/;
const SUBJECT_TOKEN = /^sbj_[A-Za-z0-9_-]{43}$/;
const LINK_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const FORM_KEY = /^[a-z0-9_-]{1,100}$/;
const FIELD_NAME = /^[A-Za-z0-9_.-]{1,100}$/;
const STORAGE_PREFIX = "ts:v1:";
// DOM controls each 004 class may be read from; everything else is excluded before its value
// is touched. Free text (textarea), email, telephone, password, hidden and file inputs never.
const CONTROL_TYPES = Object.freeze({
  "form.option": new Set(["select-one", "radio", "checkbox"]),
  "form.code": new Set(["text", "search"]),
  "form.quantity": new Set(["number", "range", "text"]),
});

function exactOrigin(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  const bare = `${url.protocol}//${url.host}`;
  if (!["http:", "https:"].includes(url.protocol) || value !== bare) return null;
  return bare;
}

function validateForms(forms) {
  const result = new Map();
  for (const [key, definition] of Object.entries(forms || {})) {
    if (!FORM_KEY.test(key) || !Array.isArray(definition?.fields)) {
      throw new TypeError("Each form needs a valid key and a fields list.");
    }
    const fields = definition.fields.map((field) => {
      if (!FIELD_NAME.test(field?.name ?? "") || !(field.data_class in CONTROL_TYPES)) {
        throw new TypeError("Form fields need a name and an option, code or quantity class.");
      }
      return Object.freeze({
        name: field.name,
        data_class: field.data_class,
        input_type: field.input_type ?? "text",
        autocomplete: field.autocomplete ?? "",
        label: field.label ?? "",
        options: Object.freeze([...(field.options ?? [])]),
      });
    });
    result.set(key, Object.freeze(fields));
  }
  return result;
}

const utf8 = new TextEncoder();

// Version 4 UUID from the platform random source; available in insecure contexts as well.
function randomUuid(crypto) {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function retryAfterMs(response, now) {
  const value = response.headers?.get?.("retry-after");
  if (!value) return null;
  if (/^[0-9]{1,6}$/.test(value.trim())) return Number(value.trim()) * 1000;
  const date = Date.parse(value);
  return Number.isNaN(date) ? null : Math.max(0, date - now);
}

// Purposes the serialized payload depends on: analytics always, and attribution when a kept
// URL still carries a click identifier (which minimization keeps only with attribution).
function contentPurposes(payload) {
  const purposes = new Set([ANALYTICS]);
  for (const url of [payload.url, payload.link_url]) {
    if (typeof url !== "string") continue;
    try {
      if (parseQsl(urlsplit(url).query).some(([name]) => CLICK_PARAMETERS.has(name))) {
        purposes.add(ATTRIBUTION);
      }
    } catch {
      // Minimized URLs always parse; nothing more to record.
    }
  }
  return purposes;
}

// Create a tracker. config: { collector, publicKey, forms?, bindings? }. environment injects
// window, document, fetch, crypto, timers and clock for tests; it defaults to the browser.
export function createTracker(config, environment = {}) {
  const collector = exactOrigin(config?.collector ?? "");
  if (!collector) throw new TypeError("collector must be an exact HTTP(S) origin.");
  if (!PUBLIC_KEY.test(config?.publicKey ?? "")) throw new TypeError("publicKey is invalid.");
  const forms = validateForms(config.forms);
  const bindings = config.bindings ?? {};
  const win = environment.window ?? globalThis.window;
  const doc = environment.document ?? win?.document;
  const fetchImpl = environment.fetch ?? globalThis.fetch.bind(globalThis);
  const crypto = environment.crypto ?? globalThis.crypto;
  const now = environment.now ?? (() => Date.now());
  const random = environment.random ?? Math.random;
  const setTimer = environment.setTimeout ?? globalThis.setTimeout.bind(globalThis);
  const clearTimer = environment.clearTimeout ?? globalThis.clearTimeout.bind(globalThis);
  const base = `${collector}/collect/v1/${config.publicKey}`;
  const storageKey = `${STORAGE_PREFIX}${config.publicKey}`;

  let token = null; // the subject token while it may be used
  let localExpiresAt = 0; // fixed local deadline of that token, never extended
  let erasable = null; // a token that outlived its local lifetime, kept for an explicit erasure
  const server = new Map(); // purposes the collector reports granted -> local expiry time
  const host = new Set(); // purposes the visitor's latest choices allow
  const intent = new Map(); // purpose -> counter, bumped by every choice that concerns it
  const reconciledGpc = new Set(); // GPC purposes already withdrawn on the server by this page
  let stateEpoch = 0; // bumped by every state read and local change: older reads are ignored
  let confirmedAt = 0;
  let destroyed = false;
  let continuity = "none";
  let mutation = Promise.resolve();
  let refreshing = null;
  let refreshTimer = null;
  let pumping = false;
  let wake = null;
  const queue = [];
  const listeners = [];
  const stats = {
    acknowledged: 0,
    retried: 0,
    failed: 0,
    rejected: 0,
    timed_out: 0,
    dropped_overflow: 0,
    dropped_ttl: 0,
    dropped_permission: 0,
    dropped_size: 0,
    unconfirmed_withdrawals: 0,
  };

  const sleep = (ms) =>
    new Promise((resolve) => {
      const timer = setTimer(() => {
        if (wake === resolve) wake = null;
        resolve();
      }, ms);
      wake = () => {
        clearTimer(timer);
        resolve();
      };
    });

  function gpcActive() {
    try {
      return win?.navigator?.globalPrivacyControl === true;
    } catch {
      return false;
    }
  }

  // The single permission rule: server grant and expiry, host choice, GPC, local lifetime.
  function effective(purpose) {
    if (destroyed || token === null || now() >= localExpiresAt) return false;
    if (!host.has(purpose) || (gpcActive() && GPC_PURPOSES.includes(purpose))) return false;
    const deadline = server.get(purpose);
    return deadline !== undefined && now() < deadline;
  }

  function effectiveSet() {
    return new Set(PURPOSES.filter(effective));
  }

  function bump(purpose) {
    intent.set(purpose, (intent.get(purpose) ?? 0) + 1);
  }

  // Storage is touched only from consent actions (grant, resume, withdraw, erase).
  function area() {
    try {
      return win?.sessionStorage ?? null;
    } catch {
      return null;
    }
  }

  function readRecord({ allowExpired = false } = {}) {
    const storage = area();
    if (!storage) {
      continuity = "memory";
      return null;
    }
    try {
      const raw = storage.getItem(storageKey);
      if (!raw) return null;
      const record = JSON.parse(raw);
      const valid =
        record?.v === 1 &&
        SUBJECT_TOKEN.test(record.token ?? "") &&
        Array.isArray(record.purposes) &&
        Number.isFinite(record.expiresAt);
      if (!valid || (!allowExpired && record.expiresAt <= now())) {
        storage.removeItem(storageKey);
        return valid && allowExpired ? record : null;
      }
      return record;
    } catch {
      continuity = "memory";
      return null;
    }
  }

  function writeRecord() {
    const storage = area();
    if (!storage) {
      continuity = "memory";
      return;
    }
    try {
      storage.setItem(
        storageKey,
        JSON.stringify({ v: 1, token, purposes: [...effectiveSet()].sort(), expiresAt: localExpiresAt }),
      );
      continuity = "session";
    } catch {
      continuity = "memory";
    }
  }

  function removeRecord() {
    try {
      area()?.removeItem(storageKey);
    } catch {
      // Removal failure leaves at most a record that expires within its fixed lifetime.
    }
  }

  function cancelRefresh() {
    if (refreshTimer !== null) clearTimer(refreshTimer);
    refreshTimer = null;
  }

  // Drop queued events whose bytes need a purpose that is no longer effective. A request
  // already on the wire cannot be recalled; it is not retried if it fails.
  function purge() {
    for (let index = queue.length - 1; index >= 0; index -= 1) {
      const item = queue[index];
      if (item.inFlight) continue;
      if (!eligible(item)) {
        queue.splice(index, 1);
        stats.dropped_permission += 1;
      }
    }
  }

  function eligible(item) {
    return item.token === token && [...item.purposes].every(effective);
  }

  // Forget the subject after its local lifetime or an unknown server state. The token stays
  // in memory only so that an explicit erase() can still reach it.
  function clearSubject() {
    if (token !== null) erasable = token;
    token = null;
    localExpiresAt = 0;
    server.clear();
    confirmedAt = 0;
    stateEpoch += 1;
    cancelRefresh();
    queue.splice(0).forEach((item) => {
      if (!item.inFlight) stats.dropped_permission += 1;
    });
    removeRecord();
  }

  function expireIfNeeded() {
    if (token !== null && now() >= localExpiresAt) {
      clearSubject();
      return true;
    }
    return false;
  }

  function scheduleRefresh() {
    cancelRefresh();
    if (destroyed || token === null || effectiveSet().size === 0) return;
    const due = Math.min(confirmedAt + LIMITS.refreshMs - LIMITS.refreshLeadMs, localExpiresAt);
    refreshTimer = setTimer(() => {
      refreshTimer = null;
      if (expireIfNeeded()) return;
      if (!doc?.hidden) refresh().catch(() => {});
    }, Math.max(0, due - now()));
  }

  function control(route, body) {
    return fetchImpl(`${base}/${route}`, {
      method: "POST",
      mode: "cors",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  function serialized(task) {
    const run = mutation.then(task, task);
    mutation = run.catch(() => {});
    return run;
  }

  // Adopt the collector's view: granted purposes with their expiry translated onto the local
  // clock through the reported server time (no clock agreement is assumed).
  function applyServer(data) {
    const received = now();
    const serverTime = Date.parse(data?.server_time ?? "");
    server.clear();
    for (const [purpose, state] of Object.entries(data?.states ?? {})) {
      if (!PURPOSES.includes(purpose) || state !== "granted") continue;
      const expiry = Date.parse(data?.expires_at?.[purpose] ?? "");
      const deadline =
        Number.isFinite(expiry) && Number.isFinite(serverTime)
          ? received + (expiry - serverTime)
          : Number.POSITIVE_INFINITY;
      server.set(purpose, deadline);
    }
    confirmedAt = received;
    stateEpoch += 1;
  }

  // Under an active GPC signal, a subject's existing sale/share or advertising grant is
  // narrowed on the server too: one withdrawal through the tracker's existing source. GPC
  // only ever denies these purposes (D-033); it never grants or touches other purposes.
  function reconcileGpc() {
    if (!gpcActive() || token === null) return;
    const affected = GPC_PURPOSES.filter((purpose) => server.has(purpose) && !reconciledGpc.has(purpose));
    if (affected.length === 0) return;
    affected.forEach((purpose) => reconciledGpc.add(purpose));
    const subject = token;
    serialized(async () => {
      const choices = Object.fromEntries(affected.map((purpose) => [purpose, "withdrawn"]));
      if (!(await sendControl("consent", { subject_token: subject, choices }))) {
        stats.unconfirmed_withdrawals += 1;
      }
    });
  }

  // After a server response: narrow under GPC, drop ineligible events, and persist the record
  // only while some purpose is effective (nothing is stored once every purpose has stopped).
  function settled() {
    reconcileGpc();
    purge();
    if (effectiveSet().size > 0) writeRecord();
    else removeRecord();
    scheduleRefresh();
  }

  function validChoices(choices) {
    if (!choices || typeof choices !== "object") throw new TypeError("choices must be an object.");
    const entries = Object.entries(choices);
    if (entries.length === 0) throw new TypeError("choices must not be empty.");
    for (const [purpose, state] of entries) {
      if (!PURPOSES.includes(purpose) || !CHOICES.has(state)) {
        throw new TypeError("choices use unknown purposes or states.");
      }
    }
    return entries;
  }

  // Record the visitor's explicit choices (one consent request). A Global Privacy Control
  // signal refuses sale/share and advertising grants before anything is sent. Choices take
  // local effect at once; the response can only enable purposes the latest choices allow.
  function grant(choices) {
    const refused = [];
    const send = {};
    const gpc = gpcActive();
    for (const [purpose, state] of validChoices(choices)) {
      if (gpc && state === "granted" && GPC_PURPOSES.includes(purpose)) refused.push(purpose);
      else send[purpose] = state;
    }
    const versions = {};
    for (const [purpose, state] of Object.entries(send)) {
      bump(purpose);
      versions[purpose] = intent.get(purpose);
      if (state === "granted") host.add(purpose);
      else host.delete(purpose);
    }
    for (const purpose of refused) {
      bump(purpose);
      host.delete(purpose);
    }
    stateEpoch += 1;
    purge();
    if (Object.keys(send).length === 0) return Promise.resolve({ status: "nothing_sent", refused });
    return serialized(async () => {
      if (destroyed) return { status: "superseded", refused };
      const current = Object.fromEntries(
        Object.entries(send).filter(([purpose]) => intent.get(purpose) === versions[purpose]),
      );
      if (Object.keys(current).length === 0) return { status: "superseded", refused };
      expireIfNeeded();
      const granting = Object.values(current).includes("granted");
      if (token === null && granting) {
        const record = readRecord();
        if (record) {
          token = record.token;
          localExpiresAt = record.expiresAt;
        }
      }
      if (token === null && !granting) {
        return { status: "nothing_granted", refused };
      }
      const body = { choices: current };
      if (token) body.subject_token = token;
      let response;
      let data;
      try {
        response = await control("consent", body);
        data = response.ok ? await response.json() : null;
      } catch {
        return { status: "unavailable", refused };
      }
      if (!response.ok) {
        return { status: response.status === 429 ? "rate_limited" : "rejected", refused };
      }
      const returned = SUBJECT_TOKEN.test(data?.subject_token ?? "") ? data.subject_token : null;
      if (returned && returned !== token) {
        token = returned;
        localExpiresAt = now() + LIMITS.localLifetimeMs;
        erasable = null;
      }
      if (token === null) return { status: "nothing_granted", refused };
      if (destroyed) return { status: "superseded", refused };
      applyServer(data);
      settled();
      const changed = Object.keys(current).some((purpose) => intent.get(purpose) !== versions[purpose]);
      const purposes = [...effectiveSet()];
      const status = changed ? "superseded" : purposes.length ? "granted" : "nothing_granted";
      return { status, purposes, refused, continuity };
    });
  }

  // Apply a decision the host or its consent platform confirms for this visitor. Purposes the
  // host no longer allows stop at once; then the stored token and the server's current state
  // are read. Never grants, renews or recreates consent.
  function resume(choices) {
    const wanted = new Set();
    const gpc = gpcActive();
    for (const [purpose, state] of validChoices(choices)) {
      if (state === "granted" && !(gpc && GPC_PURPOSES.includes(purpose))) wanted.add(purpose);
    }
    for (const purpose of PURPOSES) {
      if (host.has(purpose) !== wanted.has(purpose)) bump(purpose);
    }
    host.clear();
    wanted.forEach((purpose) => host.add(purpose));
    stateEpoch += 1;
    purge();
    if (token !== null && effectiveSet().size === 0 && wanted.size === 0) cancelRefresh();
    if (wanted.size === 0) return Promise.resolve({ status: "blocked" });
    return serialized(async () => {
      if (destroyed) return { status: "superseded" };
      expireIfNeeded();
      const record = token !== null ? { token, expiresAt: localExpiresAt } : readRecord();
      if (!record || record.expiresAt <= now()) return { status: "needs_grant" };
      const epoch = ++stateEpoch;
      let state;
      try {
        const response = await control("consent-state", { subject_token: record.token });
        if (!response.ok) return { status: response.status === 429 ? "rate_limited" : "unavailable" };
        state = await response.json();
      } catch {
        return { status: "unavailable" };
      }
      if (destroyed || epoch !== stateEpoch) return { status: "superseded" };
      token = record.token;
      localExpiresAt = record.expiresAt;
      if (state?.status !== "active") {
        clearSubject();
        return { status: "needs_grant" };
      }
      applyServer(state);
      settled();
      const purposes = [...effectiveSet()];
      return purposes.length ? { status: "resumed", purposes, continuity } : { status: "needs_grant" };
    });
  }

  // Re-read the server state while collecting. A failure leaves capture blocked once due. No
  // request is made with a token past its local lifetime.
  function refresh() {
    if (refreshing) return refreshing;
    if (destroyed || token === null || expireIfNeeded()) return Promise.resolve(false);
    const epoch = ++stateEpoch;
    const current = token;
    refreshing = (async () => {
      try {
        const response = await control("consent-state", { subject_token: current });
        if (!response.ok) return false;
        const state = await response.json();
        if (destroyed || epoch !== stateEpoch || current !== token) return false;
        if (state?.status !== "active") {
          clearSubject();
          return false;
        }
        applyServer(state);
        settled();
        return true;
      } catch {
        return false;
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  async function sendControl(route, body) {
    for (let attempt = 0; attempt < LIMITS.maxAttempts; attempt += 1) {
      try {
        const response = await control(route, body);
        if (response.ok || response.status === 202) return true;
        if (response.status !== 429 && response.status < 500) return false;
      } catch {
        // Network failure: retry within the bounded attempts.
      }
      if (attempt + 1 < LIMITS.maxAttempts) await sleep(LIMITS.retryDelaysMs[attempt] ?? 4_000);
    }
    return false;
  }

  // Withdraw purposes (default: all). Local collection stops before any request is sent.
  function withdraw(purposes = PURPOSES) {
    const list = [...purposes].filter((purpose) => PURPOSES.includes(purpose));
    for (const purpose of list) {
      bump(purpose);
      host.delete(purpose);
    }
    stateEpoch += 1;
    purge();
    const known = token ?? readRecord({ allowExpired: true })?.token ?? erasable;
    if (effectiveSet().size === 0) {
      cancelRefresh();
      removeRecord();
    } else if (token !== null) {
      writeRecord();
    }
    return serialized(async () => {
      const subject = token ?? known;
      if (!subject || list.length === 0) return { status: "withdrawn", confirmed: false };
      const choices = Object.fromEntries(list.map((purpose) => [purpose, "withdrawn"]));
      const confirmed = await sendControl("consent", { subject_token: subject, choices });
      if (!confirmed) stats.unconfirmed_withdrawals += 1;
      return { status: "withdrawn", confirmed };
    });
  }

  // Erase this visitor's subject, including one whose local lifetime has ended. Local state is
  // cleared first; only a new explicit grant may start a new subject afterwards.
  function erase() {
    PURPOSES.forEach(bump);
    host.clear();
    const known = token ?? readRecord({ allowExpired: true })?.token ?? erasable;
    clearSubject();
    return serialized(async () => {
      const subject = token ?? erasable ?? known;
      token = null;
      erasable = null;
      if (!subject) return { status: "erased", confirmed: false };
      const confirmed = await sendControl("erasure", { subject_token: subject });
      return { status: "erased", confirmed };
    });
  }

  // The managed-link reference of the page at capture time (single-page routes change it).
  function currentLinkId() {
    try {
      const value = new URL(win.location.href).searchParams.get("ts_link");
      return value && LINK_ID.test(value) ? value : null;
    } catch {
      return null;
    }
  }

  // Build, bound and queue one event. Returns a closed status; never throws to the page.
  function capture(eventType, buildPayload) {
    if (expireIfNeeded() || !effective(ANALYTICS)) return { status: "blocked" };
    if (now() - confirmedAt > LIMITS.refreshMs) {
      refresh().catch(() => {});
      return { status: "blocked" };
    }
    const granted = effectiveSet();
    let payload;
    try {
      payload = buildPayload(granted);
    } catch (error) {
      stats.rejected += 1;
      return { status: "rejected", reason: error instanceof Rejected ? error.reason : "invalid" };
    }
    const envelope = {
      schema_version: 1,
      event_id: randomUuid(crypto),
      event_type: eventType,
      occurred_at: new Date(now()).toISOString(),
      subject_token: token,
      payload,
    };
    const reference = currentLinkId();
    if (reference) envelope.link_id = reference;
    const body = JSON.stringify(envelope);
    const bytes = utf8.encode(body).length;
    if (bytes > LIMITS.bodyBytes) {
      stats.dropped_size += 1;
      return { status: "rejected", reason: "too_large" };
    }
    queue.push({
      body,
      bytes,
      purposes: contentPurposes(payload),
      token,
      enqueuedAt: now(),
      attempts: 0,
      notBefore: 0,
    });
    // Overflow drops the oldest event that is not already in flight.
    let total = queue.reduce((sum, item) => sum + item.bytes, 0);
    while (queue.length > LIMITS.queueEvents || total > LIMITS.queueBytes) {
      const index = queue.findIndex((item) => !item.inFlight);
      if (index < 0) break;
      total -= queue.splice(index, 1)[0].bytes;
      stats.dropped_overflow += 1;
    }
    pump();
    return { status: "queued", event_id: envelope.event_id };
  }

  const pageUrl = (granted) => minimizePageUrl(win.location.href, granted).url;

  function trackPageView() {
    return capture("page_view", (granted) => {
      const payload = { url: pageUrl(granted) };
      const referrer = doc?.referrer;
      if (referrer) {
        try {
          payload.referrer_origin = originOnly(referrer);
        } catch {
          // A non-HTTP referrer is omitted.
        }
      }
      return payload;
    });
  }

  function trackLinkClick(element) {
    return capture("link_click", (granted) => {
      const href = element?.href;
      if (typeof href !== "string") throw new Rejected("url_not_allowed");
      return { url: pageUrl(granted), link_url: minimizePageUrl(href, granted).url };
    });
  }

  function labelText(element) {
    try {
      return [...(element.labels ?? [])].map((label) => label.textContent ?? "").join(" ");
    } catch {
      return "";
    }
  }

  // Exclusion reason of one DOM control for a registered field, decided from the element's
  // descriptors only (tag, type, autocomplete, name, id, labels); its value is not read.
  function controlReason(field, element, form) {
    if (!element || element.form !== form || element.disabled) return "unavailable";
    const type = element.tagName === "SELECT" ? element.type : String(element.type ?? "").toLowerCase();
    if (element.tagName !== "SELECT" && element.tagName !== "INPUT") return "control_not_allowed";
    if (!CONTROL_TYPES[field.data_class].has(type)) return "control_not_allowed";
    return neverCollectReason({
      name: element.name ?? "",
      input_type: type,
      autocomplete: element.getAttribute?.("autocomplete") ?? "",
      label: labelText(element),
      element_id: element.id ?? "",
      in_payment_frame: element.ownerDocument !== doc,
    });
  }

  function readField(field, form) {
    if (neverCollectReason(field) !== null) return undefined;
    const found = form.elements.namedItem(field.name);
    if (!found) return undefined;
    const elements = typeof found.length === "number" && !found.tagName ? [...found] : [found];
    if (elements.length === 0 || elements.some((element) => controlReason(field, element, form))) {
      return undefined;
    }
    const [first] = elements;
    if (first.type === "radio") {
      const checked = elements.find((element) => element.checked);
      return checked ? checked.value : undefined;
    }
    if (elements.length !== 1) return undefined;
    if (first.type === "checkbox") return first.checked ? first.value : undefined;
    return first.value;
  }

  function trackForm(formKey, form) {
    return capture("form_submit", (granted) => {
      const fields = forms.get(formKey);
      if (!fields || !form?.elements) throw new Rejected("unknown_form");
      const values = {};
      for (const field of fields) {
        const value = sanitizeFieldValue(field, readField(field, form));
        if (value !== undefined) values[field.name] = value;
      }
      return { url: pageUrl(granted), form_key: formKey, fields: values };
    });
  }

  // Send one event. The request is aborted when the event's lifetime ends, so a stalled
  // connection can neither keep an expired payload nor hold back fresh events.
  async function send(item) {
    item.attempts += 1;
    item.inFlight = true;
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const budget = item.enqueuedAt + LIMITS.eventTtlMs - now();
    const timer = controller
      ? setTimer(() => {
          stats.timed_out += 1;
          controller.abort();
        }, Math.max(0, budget))
      : null;
    try {
      const response = await fetchImpl(`${base}/events`, {
        method: "POST",
        mode: "cors",
        credentials: "omit",
        referrerPolicy: "no-referrer",
        cache: "no-store",
        keepalive: item.bytes <= LIMITS.keepaliveBytes,
        headers: { "Content-Type": "text/plain;charset=UTF-8" },
        body: item.body,
        signal: controller?.signal,
      });
      if (response.status === 202) return { done: true, acknowledged: true };
      if (response.status === 429 || response.status === 503) {
        return { done: false, delay: retryAfterMs(response, now()) };
      }
      if (response.status >= 500) return { done: false, delay: null };
      return { done: true, acknowledged: false };
    } catch {
      return { done: false, delay: null };
    } finally {
      if (timer !== null) clearTimer(timer);
      item.inFlight = false;
    }
  }

  function backoff(attempt) {
    const delay = LIMITS.retryDelaysMs[Math.min(attempt - 1, LIMITS.retryDelaysMs.length - 1)];
    return Math.round(delay * (0.8 + random() * 0.4));
  }

  async function pump() {
    if (pumping) return;
    pumping = true;
    try {
      while (queue.length > 0 && !destroyed) {
        const item = queue[0];
        if (expireIfNeeded()) break;
        if (now() - item.enqueuedAt >= LIMITS.eventTtlMs) {
          queue.shift();
          stats.dropped_ttl += 1;
          continue;
        }
        if (!eligible(item)) {
          queue.shift();
          stats.dropped_permission += 1;
          continue;
        }
        if (now() - confirmedAt > LIMITS.refreshMs) {
          if (!(await refresh())) await sleep(1_000);
          continue;
        }
        if (item.notBefore > now()) {
          await sleep(item.notBefore - now());
          continue;
        }
        const outcome = await send(item);
        const index = queue.indexOf(item);
        if (index < 0) continue;
        if (outcome.done) {
          queue.splice(index, 1);
          stats[outcome.acknowledged ? "acknowledged" : "rejected"] += 1;
          continue;
        }
        const delay = outcome.delay ?? backoff(item.attempts);
        if (
          item.attempts >= LIMITS.maxAttempts ||
          now() + delay - item.enqueuedAt >= LIMITS.eventTtlMs ||
          !eligible(item)
        ) {
          queue.splice(index, 1);
          stats.failed += 1;
          continue;
        }
        stats.retried += 1;
        item.notBefore = now() + delay;
      }
    } finally {
      pumping = false;
    }
  }

  function listen(target, type, handler, options) {
    if (!target?.addEventListener) return;
    const safe = (event) => {
      try {
        handler(event);
      } catch {
        // Tracking errors never reach the page.
      }
    };
    target.addEventListener(type, safe, options);
    listeners.push(() => target.removeEventListener(type, safe, options));
  }

  // Optional DOM bindings. Handlers return before touching the element unless analytics is
  // currently allowed; they never prevent the default action.
  if (bindings.links && doc) {
    listen(
      doc,
      "click",
      (event) => {
        if (!effective(ANALYTICS)) return;
        const anchor = event.target?.closest?.(bindings.links);
        if (anchor) trackLinkClick(anchor);
      },
      { capture: true, passive: true },
    );
  }
  if (bindings.forms && doc) {
    listen(
      doc,
      "submit",
      (event) => {
        if (!effective(ANALYTICS)) return;
        for (const [formKey, selector] of Object.entries(bindings.forms)) {
          if (event.target?.matches?.(selector)) trackForm(formKey, event.target);
        }
      },
      { capture: true },
    );
  }
  if (win) {
    // A page restored from the back/forward cache must confirm consent again before sending.
    listen(win, "pageshow", (event) => {
      if (!event.persisted || token === null || expireIfNeeded()) return;
      stateEpoch += 1;
      confirmedAt = 0;
      refresh().then((ok) => ok && pump()).catch(() => {});
    });
  }
  if (doc) {
    listen(doc, "visibilitychange", () => {
      if (doc.hidden || token === null || expireIfNeeded()) return;
      if (effectiveSet().size && now() - confirmedAt > LIMITS.refreshMs - LIMITS.refreshLeadMs) {
        refresh().catch(() => {});
      }
    });
  }

  function destroy() {
    destroyed = true;
    stateEpoch += 1;
    cancelRefresh();
    queue.length = 0;
    if (wake) wake();
    for (const remove of listeners.splice(0)) remove();
  }

  return Object.freeze({
    grant,
    resume,
    withdraw,
    erase,
    refresh: () => refresh(),
    trackPageView,
    trackLinkClick,
    trackForm,
    destroy,
    state: () => ({
      purposes: [...effectiveSet()].sort(),
      collecting: effective(ANALYTICS) && now() - confirmedAt <= LIMITS.refreshMs,
      continuity,
      queued: queue.length,
    }),
    stats: () => ({ ...stats }),
    flush: () => pump(),
    limits: LIMITS,
    maxText: MAX_TEXT,
  });
}
