// Deterministic, instrumented browser stand-in for the tracker's Node unit tests: a manual
// clock and timers, a fake collector that keeps per-token consent with per-purpose expiry, a
// mutable location for single-page navigation, abortable held requests, and access logs for
// storage, location and network use. Synthetic values only.
import { webcrypto } from "node:crypto";

export const COLLECTOR = "https://collect.example.test";
export const PUBLIC_KEY = `pk_${"A".repeat(43)}`;
const START = Date.UTC(2026, 10, 10, 12, 0, 0);
const YEAR = 365 * 24 * 60 * 60 * 1000;

let counter = 0;
const newToken = () => `sbj_${String(++counter).padStart(43, "x")}`;

function json(status, body, headers = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function abortError() {
  return new DOMException("The operation was aborted.", "AbortError");
}

export function fakeEnvironment({
  href = "https://shop.example.test/landing?utm_source=site",
  referrer = "",
  storage = "ok",
  gpc = false,
} = {}) {
  let time = START;
  let timerId = 0;
  let location = href;
  const timers = new Map();
  const log = { storage: [], location: 0, requests: [] };
  const store = new Map();
  // token -> { purpose: state } and token -> { purpose: expiry in ms }.
  const server = new Map();
  const expiries = new Map();
  const held = [];
  const scripted = [];
  const listeners = { window: {}, document: {} };

  const sessionStorage = {
    getItem(key) {
      log.storage.push(["get", key]);
      return store.has(key) ? store.get(key) : null;
    },
    setItem(key, value) {
      log.storage.push(["set", key]);
      if (storage === "full") throw new Error("QuotaExceededError");
      store.set(key, String(value));
    },
    removeItem(key) {
      log.storage.push(["remove", key]);
      store.delete(key);
    },
  };
  const target = (bucket) => ({
    addEventListener(type, handler) {
      (bucket[type] ??= []).push(handler);
    },
    removeEventListener(type, handler) {
      bucket[type] = (bucket[type] ?? []).filter((item) => item !== handler);
    },
  });
  const navigator = { globalPrivacyControl: gpc };
  const window = {
    ...target(listeners.window),
    get sessionStorage() {
      log.storage.push(["area"]);
      if (storage === "blocked") throw new Error("SecurityError");
      return sessionStorage;
    },
    location: {
      get href() {
        log.location += 1;
        return location;
      },
    },
    navigator,
  };
  const document = { ...target(listeners.document), referrer, hidden: false };

  // The collector's current view of one subject, as the real API reports it.
  function view(token) {
    const states = server.get(token) ?? {};
    const expires = {};
    const reported = {};
    for (const [purpose, state] of Object.entries(states)) {
      const deadline = expiries.get(token)?.[purpose];
      if (state === "granted" && deadline !== undefined && deadline <= time) {
        reported[purpose] = "expired";
      } else {
        reported[purpose] = state;
        if (state === "granted" && deadline !== undefined) {
          expires[purpose] = new Date(deadline).toISOString();
        }
      }
    }
    return { states: reported, expires_at: expires, server_time: new Date(time).toISOString() };
  }

  function respond(request) {
    const route = request.url.split("/").pop();
    const body = JSON.parse(request.body);
    if (route === "consent") {
      let token = body.subject_token;
      if (token && !server.has(token)) return json(422, { error: "unknown_subject" });
      let created = null;
      if (!token) {
        if (!Object.values(body.choices).includes("granted")) {
          return json(200, { subject_token: null, receipts: [], states: {}, expires_at: {} });
        }
        token = newToken();
        created = token;
        server.set(token, {});
        expiries.set(token, {});
      }
      for (const [purpose, state] of Object.entries(body.choices)) {
        server.get(token)[purpose] = state;
        if (state === "granted") expiries.get(token)[purpose] = time + YEAR;
      }
      return json(200, { subject_token: created, receipts: [], ...view(token) });
    }
    if (route === "consent-state") {
      const active = server.has(body.subject_token);
      return json(200, {
        status: active ? "active" : "unknown",
        ...(active ? view(body.subject_token) : { states: {}, expires_at: {} }),
        server_time: new Date(time).toISOString(),
      });
    }
    if (route === "erasure") {
      server.delete(body.subject_token);
      return json(202, { status: "received" });
    }
    return json(202, { status: "received" });
  }

  async function fetch(url, init) {
    const request = { url, ...init };
    log.requests.push(request);
    const index = scripted.findIndex((item) => request.url.endsWith(`/${item.route}`));
    if (index >= 0) {
      const [item] = scripted.splice(index, 1);
      return item.handler(request);
    }
    const hold = held.findIndex((item) => request.url.endsWith(`/${item.route}`) && !item.request);
    if (hold >= 0) {
      const item = held[hold];
      item.request = request;
      if (init?.signal) {
        if (init.signal.aborted) return Promise.reject(abortError());
        init.signal.addEventListener("abort", () => {
          item.aborted = true;
          item.reject(abortError());
        });
      }
      return item.promise;
    }
    return respond(request);
  }

  const environment = {
    window,
    document,
    fetch,
    crypto: webcrypto,
    now: () => time,
    random: () => 0.5,
    setTimeout(fn, ms) {
      timerId += 1;
      timers.set(timerId, { at: time + Math.max(0, ms), fn });
      return timerId;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  };

  async function settle() {
    for (let round = 0; round < 20; round += 1) {
      await new Promise((resolve) => setImmediate(resolve));
    }
  }

  return {
    environment,
    log,
    store,
    server,
    expiries,
    listeners,
    navigator,
    settle,
    now: () => time,
    pendingTimers: () => timers.size,
    // Advance the manual clock, running due timers in order.
    async advance(ms) {
      const end = time + ms;
      for (;;) {
        await settle();
        const due = [...timers.entries()]
          .filter(([, timer]) => timer.at <= end)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]);
        time = Math.max(time, due[1].at);
        due[1].fn();
      }
      time = end;
      await settle();
    },
    // Single-page navigation: later reads of location.href see the new URL.
    navigate(next) {
      location = next;
    },
    // Next request to route gets this handler (one use).
    script(route, handler) {
      scripted.push({ route, handler });
    },
    // Hold the next request to route until release(handler) is called; an abort signal on
    // the request rejects it with an AbortError, as a browser fetch would.
    hold(route) {
      let resolve;
      let reject;
      const item = { route, request: null, aborted: false };
      item.promise = new Promise((done, fail) => {
        resolve = done;
        reject = fail;
      });
      item.reject = reject;
      item.release = (handler = respond) => resolve(handler(item.request));
      held.push(item);
      return item;
    },
    // Grant expiry of one purpose of one subject, in milliseconds from now.
    expireIn(token, purpose, ms) {
      expiries.get(token)[purpose] = time + ms;
    },
    respond,
    json,
    requests: (route) => log.requests.filter((item) => item.url.endsWith(`/${route}`)),
    dispatch(scope, type, event) {
      for (const handler of listeners[scope][type] ?? []) handler(event);
    },
  };
}
