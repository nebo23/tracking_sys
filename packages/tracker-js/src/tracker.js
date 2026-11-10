// First-party website tracker (specification 005-D, D-033).
//
// A self-hosted native ES module with no runtime dependency. It connects a client website to
// the specification 004 public collection routes under J1 strict opt-in:
//
// - Before an explicit grant (or a host-confirmed resume) it reads no storage, URL, referrer or
//   form value, creates no identifier, sends nothing and keeps no event backlog.
// - grant() records the visitor's explicit choice once; resume() only reads the stored token
//   and the server's current state (POST consent-state) and never recreates or renews consent.
// - withdraw() and erase() stop local collection immediately, discard affected queued events,
//   and are serialized after any pending consent request, so a late response never re-enables
//   capture. Consent-state responses older than the latest local change are ignored.
// - The subject token, granted-purpose snapshot and a fixed local expiry (at most 24 hours from
//   first storage, never extended) live in sessionStorage only after permission, with an
//   in-memory fallback. No localStorage, cookie, fingerprint or cross-site identifier is used.
// - URL and form minimization runs in the browser before transmission (./minimize.js) and again
//   on the server. Only explicitly configured option/code/quantity fields are read, after the
//   never-collect rules have excluded their controls.
// - Events go one per request in a bounded in-memory queue (20 events, 128 KiB, 60 seconds),
//   at most three attempts, honoring readable Retry-After; a 202 is a generic acknowledgement,
//   not proof of storage. Tracking failures never block navigation or form submission.

import {
  ANALYTICS,
  MAX_TEXT,
  Rejected,
  minimizePageUrl,
  neverCollectReason,
  originOnly,
  sanitizeFieldValue,
} from "./minimize.js";

export const VERSION = "0.5.0";
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
const REQUIRED = Object.freeze({
  page_view: ANALYTICS,
  link_click: ANALYTICS,
  form_submit: ANALYTICS,
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

  let generation = 0; // bumped by withdraw, erase and destroy: older consent results are stale
  let stateEpoch = 0; // bumped by every local change and page restore: older state reads ignored
  let destroyed = false;
  let token = null;
  let granted = new Set();
  let expiresAt = 0;
  let confirmedAt = 0;
  let continuity = "none";
  let linkId; // undefined until read after permission; null when the page has none
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

  // Storage is touched only from grant, resume, withdraw and erase, never before permission.
  function area() {
    try {
      return win?.sessionStorage ?? null;
    } catch {
      return null;
    }
  }

  function readRecord() {
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
      if (!valid || record.expiresAt <= now()) {
        storage.removeItem(storageKey);
        return null;
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
        JSON.stringify({ v: 1, token, purposes: [...granted].sort(), expiresAt }),
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

  function scheduleRefresh() {
    cancelRefresh();
    if (destroyed || !token || granted.size === 0) return;
    const delay = Math.max(0, confirmedAt + LIMITS.refreshMs - LIMITS.refreshLeadMs - now());
    refreshTimer = setTimer(() => {
      refreshTimer = null;
      if (!doc?.hidden) refresh().catch(() => {});
    }, delay);
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

  function grantedFrom(states) {
    return new Set(
      Object.entries(states || {})
        .filter(([purpose, state]) => PURPOSES.includes(purpose) && state === "granted")
        .map(([purpose]) => purpose),
    );
  }

  function dropQueued(predicate, reason) {
    for (let index = queue.length - 1; index >= 0; index -= 1) {
      if (predicate(queue[index])) {
        queue.splice(index, 1);
        stats[reason] += 1;
      }
    }
  }

  // Permission for one purpose right now: granted, inside the fixed local lifetime, and
  // confirmed by the server within the refresh interval.
  function allowed(purpose) {
    return !destroyed && token !== null && granted.has(purpose) && now() < expiresAt;
  }

  function clearLocal() {
    granted = new Set();
    expiresAt = 0;
    confirmedAt = 0;
    cancelRefresh();
    dropQueued(() => true, "dropped_permission");
    removeRecord();
  }

  function gpcActive() {
    try {
      return win?.navigator?.globalPrivacyControl === true;
    } catch {
      return false;
    }
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
  // signal refuses sale/share and advertising grants before anything is sent.
  function grant(choices) {
    const refused = [];
    const send = {};
    const gpc = gpcActive();
    for (const [purpose, state] of validChoices(choices)) {
      if (gpc && state === "granted" && GPC_PURPOSES.includes(purpose)) refused.push(purpose);
      else send[purpose] = state;
    }
    if (Object.keys(send).length === 0) return Promise.resolve({ status: "nothing_sent", refused });
    const started = generation;
    return serialized(async () => {
      if (destroyed || started !== generation) return { status: "superseded", refused };
      const body = { choices: send };
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
      const serverGranted = grantedFrom(data?.states);
      if (destroyed || started !== generation) {
        // Withdrawal, erasure or destruction happened while this grant was pending: never
        // enable it. Withdraw what the response granted; keep a new token in memory only, so
        // a queued erasure can still reach it.
        if (returned && !token) token = returned;
        if (token && serverGranted.size > 0) {
          const withdrawal = Object.fromEntries([...serverGranted].map((p) => [p, "withdrawn"]));
          try {
            await control("consent", { subject_token: token, choices: withdrawal });
          } catch {
            stats.unconfirmed_withdrawals += 1;
          }
        }
        return { status: "superseded", refused };
      }
      const fresh = returned !== null && returned !== token;
      if (returned) token = returned;
      if (!token) return { status: "nothing_granted", refused };
      if (fresh || expiresAt <= now()) {
        const stored = fresh ? null : readRecord();
        expiresAt =
          stored && stored.token === token ? stored.expiresAt : now() + LIMITS.localLifetimeMs;
      }
      granted = serverGranted;
      confirmedAt = now();
      stateEpoch += 1;
      dropQueued((item) => !granted.has(item.purpose), "dropped_permission");
      writeRecord();
      scheduleRefresh();
      return { status: granted.size ? "granted" : "nothing_granted", purposes: [...granted], refused, continuity };
    });
  }

  // Resume a decision the host or its consent platform confirms for this visitor. Reads the
  // stored token and the server's current state; never grants, renews or recreates consent.
  function resume(choices) {
    const wanted = new Set();
    const gpc = gpcActive();
    for (const [purpose, state] of validChoices(choices)) {
      if (state === "granted" && !(gpc && GPC_PURPOSES.includes(purpose))) wanted.add(purpose);
    }
    if (wanted.size === 0) return Promise.resolve({ status: "blocked" });
    const started = generation;
    return serialized(async () => {
      if (destroyed || started !== generation) return { status: "superseded" };
      const record = token ? { token, expiresAt } : readRecord();
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
      if (destroyed || started !== generation || epoch !== stateEpoch) return { status: "superseded" };
      if (state?.status !== "active") {
        token = null;
        clearLocal();
        return { status: "needs_grant" };
      }
      const enabled = new Set([...grantedFrom(state.states)].filter((p) => wanted.has(p)));
      token = record.token;
      expiresAt = record.expiresAt;
      granted = enabled;
      confirmedAt = now();
      writeRecord();
      scheduleRefresh();
      return enabled.size ? { status: "resumed", purposes: [...enabled], continuity } : { status: "needs_grant" };
    });
  }

  // Re-read the server state while collecting. A failure leaves capture blocked once due.
  function refresh() {
    if (refreshing) return refreshing;
    if (destroyed || !token) return Promise.resolve(false);
    const epoch = ++stateEpoch;
    const started = generation;
    const current = token;
    refreshing = (async () => {
      try {
        const response = await control("consent-state", { subject_token: current });
        if (!response.ok) return false;
        const state = await response.json();
        if (destroyed || epoch !== stateEpoch || started !== generation || current !== token) {
          return false;
        }
        if (state?.status !== "active") {
          token = null;
          clearLocal();
          return false;
        }
        const server = grantedFrom(state.states);
        granted = new Set([...granted].filter((purpose) => server.has(purpose)));
        dropQueued((item) => !granted.has(item.purpose), "dropped_permission");
        confirmedAt = now();
        writeRecord();
        scheduleRefresh();
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
    generation += 1;
    stateEpoch += 1;
    for (const purpose of list) granted.delete(purpose);
    dropQueued((item) => !granted.has(item.purpose), "dropped_permission");
    const known = token ?? readRecord()?.token ?? null;
    if (granted.size === 0) {
      cancelRefresh();
      removeRecord();
    } else if (token) {
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

  // Erase this visitor's subject. Local state is cleared first; only a new explicit grant may
  // start a new subject afterwards.
  function erase() {
    generation += 1;
    stateEpoch += 1;
    const known = token ?? readRecord()?.token ?? null;
    clearLocal();
    queue.length = 0;
    return serialized(async () => {
      const subject = token ?? known;
      token = null;
      if (!subject) return { status: "erased", confirmed: false };
      const confirmed = await sendControl("erasure", { subject_token: subject });
      return { status: "erased", confirmed };
    });
  }

  function currentLinkId() {
    if (linkId === undefined) {
      linkId = null;
      try {
        const value = new URL(win.location.href).searchParams.get("ts_link");
        if (value && LINK_ID.test(value)) linkId = value;
      } catch {
        linkId = null;
      }
    }
    return linkId;
  }

  function pageUrl() {
    return minimizePageUrl(win.location.href, granted).url;
  }

  // Build, bound and queue one event. Returns a closed status; never throws to the page.
  function capture(eventType, buildPayload) {
    const purpose = REQUIRED[eventType];
    if (!allowed(purpose)) return { status: "blocked" };
    if (now() - confirmedAt > LIMITS.refreshMs) {
      refresh().catch(() => {});
      return { status: "blocked" };
    }
    let payload;
    try {
      payload = buildPayload();
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
    queue.push({ body, bytes, purpose, token, enqueuedAt: now(), attempts: 0, notBefore: 0 });
    // Overflow drops the oldest event that is not already in flight; a request on the wire
    // cannot be recalled, so it stays counted until its outcome.
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

  function trackPageView() {
    return capture("page_view", () => {
      const payload = { url: pageUrl() };
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
    return capture("link_click", () => {
      const href = element?.href;
      if (typeof href !== "string") throw new Rejected("url_not_allowed");
      return { url: pageUrl(), link_url: minimizePageUrl(href, granted).url };
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
    return capture("form_submit", () => {
      const fields = forms.get(formKey);
      if (!fields || !form?.elements) throw new Rejected("unknown_form");
      const values = {};
      for (const field of fields) {
        const value = sanitizeFieldValue(field, readField(field, form));
        if (value !== undefined) values[field.name] = value;
      }
      return { url: pageUrl(), form_key: formKey, fields: values };
    });
  }

  function permitted(item) {
    return (
      !destroyed &&
      item.token === token &&
      granted.has(item.purpose) &&
      now() < expiresAt
    );
  }

  async function send(item) {
    item.attempts += 1;
    item.inFlight = true;
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
        if (now() - item.enqueuedAt > LIMITS.eventTtlMs) {
          queue.shift();
          stats.dropped_ttl += 1;
          continue;
        }
        if (!permitted(item)) {
          queue.shift();
          stats.dropped_permission += 1;
          continue;
        }
        if (now() - confirmedAt > LIMITS.refreshMs) {
          if (!(await refresh())) {
            await sleep(1_000);
          }
          continue;
        }
        if (item.notBefore > now()) {
          await sleep(item.notBefore - now());
          continue;
        }
        const outcome = await send(item);
        if (queue[0] !== item) continue;
        if (outcome.done) {
          queue.shift();
          stats[outcome.acknowledged ? "acknowledged" : "rejected"] += 1;
          continue;
        }
        const delay = outcome.delay ?? backoff(item.attempts);
        if (item.attempts >= LIMITS.maxAttempts || now() + delay - item.enqueuedAt > LIMITS.eventTtlMs) {
          queue.shift();
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
        if (!allowed(ANALYTICS)) return;
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
        if (!allowed(ANALYTICS)) return;
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
      if (!event.persisted || !token) return;
      stateEpoch += 1;
      confirmedAt = 0;
      refresh().then((ok) => ok && pump()).catch(() => {});
    });
  }
  if (doc) {
    listen(doc, "visibilitychange", () => {
      if (!doc.hidden && token && granted.size && now() - confirmedAt > LIMITS.refreshMs - LIMITS.refreshLeadMs) {
        refresh().catch(() => {});
      }
    });
  }

  function destroy() {
    destroyed = true;
    generation += 1;
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
      purposes: [...granted].sort(),
      collecting: allowed(ANALYTICS) && now() - confirmedAt <= LIMITS.refreshMs,
      continuity,
      queued: queue.length,
    }),
    stats: () => ({ ...stats }),
    flush: () => pump(),
    limits: LIMITS,
    maxText: MAX_TEXT,
  });
}
