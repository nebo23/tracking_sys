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
//   attribution when a URL keeps a click identifier) and the server grant it was captured
//   under, so a narrowing drops affected events and marks in-flight ones as never retried.
// - grant() records the visitor's explicit choice once; resume() only reads the stored token
//   and the server's current state (POST consent-state) and never recreates or renews consent.
//   Narrowing by the host takes effect synchronously. A purpose the host newly allows stays
//   suspended until a consent or state request that started after that choice confirms it, so
//   a pending, failed or older answer can never widen permission.
// - Server expiry is translated onto the local clock from the time each request started, so
//   transport latency never extends it. A grant without a valid expiry is not effective.
// - withdraw() and erase() stop local collection immediately, drop the cached server grant of
//   the affected purposes and are serialized after any pending consent request. A grant
//   response is reconciled per purpose with the latest choices, so a partial withdrawal leaves
//   the other purposes untouched. Consent and state requests are aborted after a fixed timeout.
// - Queued consent work re-checks the host's intent when its turn comes: a grant or resume
//   that a newer choice made obsolete ends without reading storage or sending the token.
// - A background state read cannot be ordered against a consent write that was on the wire at
//   the same time, so its answer is not adopted; the write's own answer is. A read that was
//   answered but not adopted is repeated once the pending consent work has finished, unless a
//   newer answer was adopted meanwhile, and only while the host still allows a purpose.
// - Under Global Privacy Control a known subject's sale/share or advertising grant is also
//   withdrawn at the collector, with a bounded number of attempts for each distinct grant.
// - The subject token, granted-purpose snapshot and a fixed local expiry (at most 24 hours from
//   first storage, never extended) live in sessionStorage only after permission, with an
//   in-memory fallback. Background state reads (refresh timer, visibility, page restoration)
//   need current host permission and a token within that lifetime; a token kept only so that
//   an explicit erase() can reach its subject never authorizes background traffic.
// - URL and form minimization runs in the browser before transmission (./minimize.js) and again
//   on the server. Only explicitly configured option/code/quantity fields are read, after the
//   never-collect rules have excluded their controls.
// - Events go one per request in a bounded in-memory queue (20 events, 128 KiB, 60 seconds),
//   at most three attempts, honoring readable Retry-After; each request is aborted when its
//   event's lifetime ends, and waiting for a state read never outlasts that lifetime either.
//   A 202 is a generic acknowledgement, not proof of storage. Tracking failures never block
//   navigation or form submission.

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

export const VERSION = "0.5.3";
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
  controlTimeoutMs: 10_000,
  gpcRounds: 3,
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
  // Purposes the collector reports granted -> { deadline (local clock), seq (request that
  // reported it), id (identity of this continuous grant; a regrant gets a new one) }.
  const server = new Map();
  // Purposes the newest adopted answer reports granted, whether or not their expiry data made
  // them effective, each with the identity of that grant at the collector: its reported expiry
  // instant, which a routine read repeats unchanged and every new grant replaces (0 when the
  // answer carries no valid expiry). GPC reconciliation narrows all of them.
  const reported = new Map();
  const host = new Set(); // purposes the visitor's latest choices allow
  const hostSince = new Map(); // purpose -> requestSeq when the host last newly allowed it
  const intent = new Map(); // purpose -> counter, bumped by every choice that concerns it
  // GPC reconciliation per subject and purpose: { grant (identity of the grant the failures
  // were counted for), pending, failures, after (requestSeq when the last round ended; only an
  // answer requested later, or a choice GPC refuses, may trigger another round) }.
  const gpcRounds = new Map();
  let requestSeq = 0; // numbers consent and state requests in the order they start
  let appliedSeq = 0; // the newest request whose answer was adopted
  let grantIds = 0;
  let stateEpoch = 0; // bumped by every state read and local change: older reads are ignored
  let confirmedAt = 0;
  let destroyed = false;
  let continuity = "none";
  let mutation = Promise.resolve();
  let queued = 0; // serialized consent operations that have not finished
  let writes = 0; // consent writes (grant, withdrawal, erasure) currently on the wire
  let writeMark = 0; // bumped whenever a consent write goes on the wire
  let rereadDue = false; // an answered background state read could not be adopted
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

  // The queue pump's pause: wake() ends it early (new state, destroy). Only the pump uses it.
  const sleep = (ms) =>
    new Promise((resolve) => {
      let timer = null;
      const done = () => {
        if (timer !== null) clearTimer(timer);
        if (wake === done) wake = null;
        resolve();
      };
      timer = setTimer(done, Math.max(0, ms));
      wake = done;
    });
  // A plain delay between control attempts, independent of the pump.
  const delay = (ms) => new Promise((resolve) => setTimer(resolve, ms));

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
    const grant = server.get(purpose);
    return grant !== undefined && grant.seq > (hostSince.get(purpose) ?? 0) && now() < grant.deadline;
  }

  // The host allows a purpose. A newly allowed purpose stays suspended until a consent or state
  // request that starts after this point confirms it; an earlier answer can never enable it.
  function allow(purpose) {
    if (host.has(purpose)) return;
    host.add(purpose);
    hostSince.set(purpose, requestSeq);
  }

  // The host no longer allows a purpose. A withdrawal or denial also drops its cached server
  // grant, so nothing captured or confirmed before it can become eligible again.
  function disallow(purpose, { forgetGrant = false } = {}) {
    host.delete(purpose);
    if (forgetGrant) server.delete(purpose);
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
  // already on the wire cannot be recalled; it is marked revoked, so it is never attempted
  // again even if a later grant makes the purpose effective once more.
  function purge() {
    for (let index = queue.length - 1; index >= 0; index -= 1) {
      const item = queue[index];
      if (eligible(item)) continue;
      if (item.inFlight) {
        item.revoked = true;
        continue;
      }
      queue.splice(index, 1);
      stats.dropped_permission += 1;
    }
  }

  // An event may be (re)sent only for its own subject, while every purpose its bytes depend on
  // is effective under the same continuous server grant it was captured under.
  function eligible(item) {
    return (
      !item.revoked &&
      item.token === token &&
      [...item.purposes].every(
        (purpose) => effective(purpose) && server.get(purpose)?.id === item.grants.get(purpose),
      )
    );
  }

  // Forget the subject after its local lifetime or an unknown server state. The token stays
  // in memory only so that an explicit erase() can still reach it.
  function clearSubject() {
    if (token !== null) erasable = token;
    token = null;
    localExpiresAt = 0;
    server.clear();
    reported.clear();
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

  // One consent, state or erasure request. It is aborted after LIMITS.controlTimeoutMs,
  // including reading its body, so a stalled collector can hold neither the consent sequence
  // nor a state read indefinitely. Returns { ok, status, data }; throws on network failure,
  // abort or an unreadable success body (when read is requested).
  async function control(route, body, { read = true } = {}) {
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller ? setTimer(() => controller.abort(), LIMITS.controlTimeoutMs) : null;
    try {
      const response = await fetchImpl(`${base}/${route}`, {
        method: "POST",
        mode: "cors",
        credentials: "omit",
        referrerPolicy: "no-referrer",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller?.signal,
      });
      const data = response.ok && read ? await response.json() : null;
      return { ok: response.ok, status: response.status, data };
    } finally {
      if (timer !== null) clearTimer(timer);
    }
  }

  // Consent operations run one at a time, in the order they were requested. Each one checks
  // the host's current intent again when its turn comes, because choices made while it waited
  // took local effect at once.
  function serialized(task) {
    queued += 1;
    const turn = async () => {
      try {
        return await task();
      } finally {
        queued -= 1;
        reread();
      }
    };
    const run = mutation.then(turn, turn);
    mutation = run.catch(() => {});
    return run;
  }

  // A consent write on the wire, including the handling of its answer. The collector may
  // process a state read sent during this time before or after the write, so the order in
  // which the two requests started says nothing about which answer is newer.
  async function writing(send) {
    writes += 1;
    writeMark += 1;
    try {
      return await send();
    } finally {
      writes -= 1;
    }
  }

  // Repeat a background state read that was answered but could not be adopted, once no consent
  // operation is pending. refresh() checks host permission, the token and its lifetime again
  // before anything is sent; an answer adopted in the meantime makes the repeat unnecessary.
  function reread() {
    if (!rereadDue || queued > 0 || refreshing) return;
    rereadDue = false;
    refresh().catch(() => {});
  }

  // Adopt the collector's view from the answer to request seq, which started at local time
  // started. Each grant's remaining lifetime (expires_at - server_time) is counted from the
  // request start: the server cannot have answered earlier, so transport latency shortens the
  // local deadline and never extends it. No clock agreement is assumed. A grant without a
  // valid expiry or server time is not effective. Answers to requests older than the last
  // adopted one are ignored.
  function applyServer(data, seq, started) {
    if (seq < appliedSeq) return;
    appliedSeq = seq;
    const serverTime = Date.parse(data?.server_time ?? "");
    const previous = new Map(server);
    server.clear();
    reported.clear();
    for (const [purpose, state] of Object.entries(data?.states ?? {})) {
      if (!PURPOSES.includes(purpose) || state !== "granted") continue;
      const expiry = Date.parse(data?.expires_at?.[purpose] ?? "");
      reported.set(purpose, Number.isFinite(expiry) ? expiry : 0);
      if (!Number.isFinite(expiry) || !Number.isFinite(serverTime) || expiry <= serverTime) continue;
      const prior = previous.get(purpose);
      const id = prior !== undefined && now() < prior.deadline ? prior.id : (grantIds += 1);
      server.set(purpose, { deadline: started + (expiry - serverTime), seq, id });
    }
    confirmedAt = started;
    stateEpoch += 1;
    rereadDue = false;
  }

  // Under an active GPC signal, a subject's existing sale/share or advertising grant is
  // narrowed on the server too, through the tracker's existing consent source. A round (one
  // bounded withdrawal request) starts when an adopted answer reports such a grant and was
  // requested after the previous round for that subject and purpose ended, so a transient
  // failure is retried after recovery and a later regrant is withdrawn again, while answers
  // older than a confirmed withdrawal never trigger one. A choice that GPC refuses (explicit)
  // also starts a round for a grant the collector is known to report, because without host
  // permission no later state read would. At most LIMITS.gpcRounds consecutive rounds may fail
  // for one grant: a routine read of the unchanged grant keeps that count, and a distinct new
  // grant (the collector reports a different expiry) starts its own. Local GPC restrictions
  // apply throughout. GPC only ever denies these purposes (D-033); it never grants or touches
  // other purposes.
  function reconcileGpc({ explicit = false } = {}) {
    if (!gpcActive() || token === null) return;
    const subject = token;
    const affected = GPC_PURPOSES.filter((purpose) => {
      if (!reported.has(purpose)) return false;
      const round = gpcRounds.get(`${subject} ${purpose}`);
      if (!round) return true;
      if (round.pending) return false;
      const failures = round.grant === reported.get(purpose) ? round.failures : 0;
      return failures < LIMITS.gpcRounds && (explicit || appliedSeq > round.after);
    });
    if (affected.length === 0) return;
    const rounds = affected.map((purpose) => {
      const key = `${subject} ${purpose}`;
      const grant = reported.get(purpose);
      const round = gpcRounds.get(key) ?? { grant, failures: 0, after: 0 };
      if (round.grant !== grant) {
        round.grant = grant;
        round.failures = 0;
      }
      round.pending = true;
      gpcRounds.set(key, round);
      return round;
    });
    serialized(() =>
      writing(async () => {
        const choices = Object.fromEntries(affected.map((purpose) => [purpose, "withdrawn"]));
        const confirmed = await sendControl("consent", { subject_token: subject, choices });
        for (const round of rounds) {
          round.pending = false;
          round.after = requestSeq;
          round.failures = confirmed ? 0 : round.failures + 1;
        }
        if (confirmed && token === subject) {
          for (const purpose of affected) {
            reported.delete(purpose);
            server.delete(purpose);
          }
        }
        if (!confirmed) stats.unconfirmed_withdrawals += 1;
      }),
    );
  }

  // After a server response: narrow under GPC, drop ineligible events, persist the record only
  // while some purpose is effective (nothing is stored once every purpose has stopped), and let
  // a waiting queue re-evaluate against the new state.
  function settled() {
    reconcileGpc();
    purge();
    if (effectiveSet().size > 0) writeRecord();
    else removeRecord();
    scheduleRefresh();
    if (wake) wake();
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
      if (state === "granted") allow(purpose);
      else disallow(purpose, { forgetGrant: true });
    }
    for (const purpose of refused) {
      bump(purpose);
      disallow(purpose);
    }
    stateEpoch += 1;
    purge();
    // A grant the collector is known to hold for a purpose GPC refuses is withdrawn there too,
    // even when nothing else is left to send. An unknown visitor has no subject to reconcile.
    if (refused.length > 0) reconcileGpc({ explicit: true });
    if (Object.keys(send).length === 0) return Promise.resolve({ status: "nothing_sent", refused });
    return serialized(async () => {
      if (destroyed) return { status: "superseded", refused };
      // Only the choices that are still the visitor's latest are sent; when none is, nothing
      // is read from storage and nothing leaves the browser.
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
      return writing(async () => {
        const seq = ++requestSeq;
        const started = now();
        let reply;
        try {
          reply = await control("consent", body);
        } catch {
          return { status: "unavailable", refused };
        }
        if (!reply.ok) {
          return { status: reply.status === 429 ? "rate_limited" : "rejected", refused };
        }
        const { data } = reply;
        const returned = SUBJECT_TOKEN.test(data?.subject_token ?? "") ? data.subject_token : null;
        if (returned && returned !== token) {
          token = returned;
          localExpiresAt = now() + LIMITS.localLifetimeMs;
          erasable = null;
        }
        if (token === null) return { status: "nothing_granted", refused };
        if (destroyed) return { status: "superseded", refused };
        applyServer(data, seq, started);
        settled();
        const changed = Object.keys(current).some((purpose) => intent.get(purpose) !== versions[purpose]);
        const purposes = [...effectiveSet()];
        const status = changed ? "superseded" : purposes.length ? "granted" : "nothing_granted";
        return { status, purposes, refused, continuity };
      });
    });
  }

  // Apply a decision the host or its consent platform confirms for this visitor. Purposes the
  // host no longer allows stop at once; purposes it newly allows wait for this state read (or
  // a later one) to confirm them. Never grants, renews or recreates consent.
  function resume(choices) {
    const wanted = new Set();
    const gpc = gpcActive();
    let refused = false;
    for (const [purpose, state] of validChoices(choices)) {
      if (state !== "granted") continue;
      if (gpc && GPC_PURPOSES.includes(purpose)) refused = true;
      else wanted.add(purpose);
    }
    for (const purpose of PURPOSES) {
      if (host.has(purpose) !== wanted.has(purpose)) bump(purpose);
      if (wanted.has(purpose)) allow(purpose);
      else disallow(purpose);
    }
    stateEpoch += 1;
    purge();
    if (token !== null && effectiveSet().size === 0 && wanted.size === 0) cancelRefresh();
    // As in grant(): a known server grant for a purpose GPC refuses is withdrawn there too.
    if (refused) reconcileGpc({ explicit: true });
    if (wanted.size === 0) return Promise.resolve({ status: "blocked" });
    // The host's intent this read acts on. A newer choice for a purpose changes its counter.
    const versions = new Map([...wanted].map((purpose) => [purpose, intent.get(purpose) ?? 0]));
    return serialized(async () => {
      if (destroyed) return { status: "superseded" };
      // This read may have waited behind other consent work. It goes ahead only while the
      // host still allows a purpose it was asked for under the same choice; otherwise it ends
      // here, before storage is read or the subject token is sent.
      const standing = [...wanted].some(
        (purpose) => host.has(purpose) && (intent.get(purpose) ?? 0) === versions.get(purpose),
      );
      if (!standing) return { status: "superseded" };
      expireIfNeeded();
      const record = token !== null ? { token, expiresAt: localExpiresAt } : readRecord();
      if (!record || record.expiresAt <= now()) return { status: "needs_grant" };
      const epoch = ++stateEpoch;
      const seq = ++requestSeq;
      const started = now();
      let reply;
      try {
        reply = await control("consent-state", { subject_token: record.token });
      } catch {
        return { status: "unavailable" };
      }
      if (!reply.ok) return { status: reply.status === 429 ? "rate_limited" : "unavailable" };
      const state = reply.data;
      if (destroyed || epoch !== stateEpoch) return { status: "superseded" };
      token = record.token;
      localExpiresAt = record.expiresAt;
      if (state?.status !== "active") {
        clearSubject();
        return { status: "needs_grant" };
      }
      applyServer(state, seq, started);
      settled();
      const purposes = [...effectiveSet()];
      return purposes.length ? { status: "resumed", purposes, continuity } : { status: "needs_grant" };
    });
  }

  // Re-read the server state while collecting. A failure leaves capture blocked once due. No
  // request is made without current host permission or with a token past its local lifetime;
  // a token kept after a full withdrawal serves only an explicit erase(). The answer is
  // adopted only if no local change and no consent write happened while it was outstanding:
  // a write on the wire at the same time may have been processed before or after this read,
  // so the write's own answer is the one that counts. A read that was answered but not
  // adopted is repeated once the pending consent work has finished (see reread()).
  function refresh() {
    if (refreshing) return refreshing;
    if (destroyed || token === null || expireIfNeeded() || host.size === 0) return Promise.resolve(false);
    // A repeat is already due when the pending consent work ends; nothing more is sent now.
    if (rereadDue) return Promise.resolve(false);
    const epoch = ++stateEpoch;
    const seq = ++requestSeq;
    const started = now();
    const current = token;
    const mark = writes > 0 ? -1 : writeMark;
    refreshing = (async () => {
      try {
        const reply = await control("consent-state", { subject_token: current });
        if (!reply.ok) return false;
        const state = reply.data;
        if (destroyed || current !== token) return false;
        if (epoch !== stateEpoch || mark !== writeMark) {
          rereadDue = true;
          return false;
        }
        if (state?.status !== "active") {
          clearSubject();
          return false;
        }
        applyServer(state, seq, started);
        settled();
        return true;
      } catch {
        return false;
      } finally {
        refreshing = null;
        reread();
      }
    })();
    return refreshing;
  }

  async function sendControl(route, body) {
    for (let attempt = 0; attempt < LIMITS.maxAttempts; attempt += 1) {
      try {
        const reply = await control(route, body, { read: false });
        if (reply.ok || reply.status === 202) return true;
        if (reply.status !== 429 && reply.status < 500) return false;
      } catch {
        // Network failure or timeout: retry within the bounded attempts.
      }
      if (attempt + 1 < LIMITS.maxAttempts) await delay(LIMITS.retryDelaysMs[attempt] ?? 4_000);
    }
    return false;
  }

  // Withdraw purposes (default: all). Local collection stops before any request is sent.
  function withdraw(purposes = PURPOSES) {
    const list = [...purposes].filter((purpose) => PURPOSES.includes(purpose));
    for (const purpose of list) {
      bump(purpose);
      disallow(purpose, { forgetGrant: true });
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
      const confirmed = await writing(() => sendControl("consent", { subject_token: subject, choices }));
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
      const confirmed = await writing(() => sendControl("erasure", { subject_token: subject }));
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
    const purposes = contentPurposes(payload);
    queue.push({
      body,
      bytes,
      purposes,
      grants: new Map([...purposes].map((purpose) => [purpose, server.get(purpose)?.id])),
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
          // Wait for a current state, but never past this event's lifetime: a stalled read
          // releases the queue, and its late answer is ignored once newer state exists.
          const left = () => Math.max(0, item.enqueuedAt + LIMITS.eventTtlMs - now());
          const confirmed = await Promise.race([refresh(), sleep(left()).then(() => null)]);
          if (wake) wake();
          if (confirmed === false) await sleep(Math.min(1_000, left()));
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
    // Without current host permission nothing is read: the token then serves erase() only.
    listen(win, "pageshow", (event) => {
      if (!event.persisted || token === null || host.size === 0 || expireIfNeeded()) return;
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
