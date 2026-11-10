// Deterministic, instrumented browser stand-in for the tracker's Node unit tests: a manual
// clock and timers, a fake collector that keeps per-token consent, and access logs for
// storage, location and network use. Synthetic values only.
import { webcrypto } from "node:crypto";

export const COLLECTOR = "https://collect.example.test";
export const PUBLIC_KEY = `pk_${"A".repeat(43)}`;
const START = Date.UTC(2026, 10, 10, 12, 0, 0);

let counter = 0;
const newToken = () => `sbj_${String(++counter).padStart(43, "x")}`;

function json(status, body, headers = {}) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function fakeEnvironment({
  href = "https://shop.example.test/landing?utm_source=site",
  referrer = "",
  storage = "ok",
  gpc = false,
} = {}) {
  let time = START;
  let timerId = 0;
  const timers = new Map();
  const log = { storage: [], location: 0, requests: [] };
  const store = new Map();
  const server = new Map(); // token -> { purpose: state }
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
        return href;
      },
    },
    navigator: { globalPrivacyControl: gpc },
  };
  const document = { ...target(listeners.document), referrer, hidden: false };

  function respond(request) {
    const route = request.url.split("/").pop();
    const body = JSON.parse(request.body);
    if (route === "consent") {
      let token = body.subject_token;
      if (token && !server.has(token)) return json(422, { error: "unknown_subject" });
      if (!token) {
        if (!Object.values(body.choices).includes("granted")) {
          return json(200, { subject_token: null, receipts: [], states: {} });
        }
        token = newToken();
        server.set(token, {});
      }
      Object.assign(server.get(token), body.choices);
      return json(200, {
        subject_token: body.subject_token ? null : token,
        receipts: [],
        states: { ...server.get(token) },
      });
    }
    if (route === "consent-state") {
      const states = server.get(body.subject_token);
      return json(200, {
        status: states ? "active" : "unknown",
        states: states ?? {},
        expires_at: {},
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
      held[hold].request = request;
      return held[hold].promise;
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
    listeners,
    settle,
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
    // Next request to route gets this handler (one use).
    script(route, handler) {
      scripted.push({ route, handler });
    },
    // Hold the next request to route until release(handler) is called.
    hold(route) {
      let resolve;
      const item = { route, request: null };
      item.promise = new Promise((done) => {
        resolve = done;
      });
      item.release = (handler = respond) => resolve(handler(item.request));
      held.push(item);
      return item;
    },
    respond,
    json,
    requests: (route) => log.requests.filter((item) => item.url.endsWith(`/${route}`)),
    dispatch(scope, type, event) {
      for (const handler of listeners[scope][type] ?? []) handler(event);
    },
  };
}
