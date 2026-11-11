// Real-browser test harness (specification 005-D, verification matrix C1-C6, M1, M2, T1).
//
// Starts two loopback HTTP servers on different origins: a static customer site that self-hosts
// the tracker module, and a scripted collector that imitates the public collection routes
// (CORS for the site origin only, Retry-After exposure, per-token consent with per-purpose
// expiry and server time, as the real API reports them). Every request the
// collector receives is recorded with its raw body. An init script instruments storage,
// cookies, form-value getters, randomness and network APIs in the page. Synthetic values only;
// nothing leaves 127.0.0.1.
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";

process.env.PLAYWRIGHT_BROWSERS_PATH ??= "0";
const { chromium, firefox } = await import("playwright");

export const PUBLIC_KEY = `pk_${"B".repeat(43)}`;
export const BROWSERS = { chromium, firefox };
const SOURCE = fileURLToPath(new URL("../../src/", import.meta.url));
const FIXTURES = fileURLToPath(new URL("../fixtures/", import.meta.url));
const EXAMPLES = fileURLToPath(new URL("../../examples/", import.meta.url));

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

function readBody(request) {
  return new Promise((resolve) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
  });
}

let tokens = 0;
const YEAR_MS = 365 * 24 * 60 * 60 * 1000;

export async function startServers() {
  const site = { pages: new Map() };
  const collector = { requests: [], plans: new Map(), consent: new Map(), expiries: new Map(), held: [] };
  const siteServer = createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    // The shipped installation example, exactly as committed: its page and module from
    // examples/, and the tracker at the versioned asset path the example imports.
    const example = url.pathname.match(/^\/examples\/(install\.(?:html|js))$/);
    const asset = url.pathname.match(/^\/assets\/tracker-[0-9.]+\/((?:tracker|minimize)\.js)$/);
    if (example || asset) {
      const file = example ? EXAMPLES + example[1] : SOURCE + asset[1];
      const type = file.endsWith(".html") ? "text/html; charset=utf-8" : "text/javascript";
      response.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store" });
      response.end(await readFile(file));
      return;
    }
    if (url.pathname.startsWith("/src/") || url.pathname.startsWith("/fixtures/")) {
      const root = url.pathname.startsWith("/src/") ? SOURCE : FIXTURES;
      const name = url.pathname.split("/").pop();
      if (!/^[a-z-]+\.(js|json)$/.test(name)) {
        response.writeHead(404).end();
        return;
      }
      try {
        const content = await readFile(root + name);
        const type = name.endsWith(".js") ? "text/javascript" : "application/json";
        response.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store" });
        response.end(content);
      } catch {
        response.writeHead(404).end();
      }
      return;
    }
    const page = site.pages.get(url.pathname);
    response.writeHead(page ? 200 : 404, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    });
    response.end(page ?? "<!doctype html><title>Missing</title>");
  });
  site.port = await listen(siteServer);
  site.origin = `http://127.0.0.1:${site.port}`;
  site.page = (path, html) => site.pages.set(path, html);
  site.page("/next.html", "<!doctype html><title>Next</title><h1 id='next'>Next page</h1>");

  const corsHeaders = (origin) =>
    origin === site.origin
      ? { "Access-Control-Allow-Origin": origin, "Access-Control-Expose-Headers": "Retry-After", Vary: "Origin" }
      : { Vary: "Origin" };

  // The collector's view of one subject: states, the expiry of each granted purpose and the
  // server time.
  function view(token) {
    const states = { ...(collector.consent.get(token) ?? {}) };
    const expiries = collector.expiries.get(token) ?? {};
    const expires_at = {};
    for (const [purpose, state] of Object.entries(states)) {
      if (state === "granted") expires_at[purpose] = new Date(expiries[purpose]).toISOString();
    }
    return { states, expires_at, server_time: new Date().toISOString() };
  }

  function defaultResponse(route, body) {
    if (route === "consent") {
      let token = body.subject_token;
      if (token && !collector.consent.has(token)) return [422, { error: "unknown_subject" }];
      let created = null;
      if (!token) {
        if (!Object.values(body.choices).includes("granted")) {
          return [
            200,
            { subject_token: null, receipts: [], states: {}, expires_at: {}, server_time: new Date().toISOString() },
          ];
        }
        tokens += 1;
        token = `sbj_${String(tokens).padStart(43, "t")}`;
        created = token;
        collector.consent.set(token, {});
        collector.expiries.set(token, {});
      }
      Object.assign(collector.consent.get(token), body.choices);
      for (const [purpose, state] of Object.entries(body.choices)) {
        if (state === "granted") collector.expiries.get(token)[purpose] = Date.now() + YEAR_MS;
      }
      return [200, { subject_token: created, receipts: [], ...view(token) }];
    }
    if (route === "consent-state") {
      const active = collector.consent.has(body.subject_token);
      return [
        200,
        active
          ? { status: "active", ...view(body.subject_token) }
          : { status: "unknown", states: {}, expires_at: {}, server_time: new Date().toISOString() },
      ];
    }
    if (route === "erasure") {
      collector.consent.delete(body.subject_token);
      collector.expiries.delete(body.subject_token);
    }
    return [202, { status: "received" }];
  }

  const collectorServer = createServer(async (request, response) => {
    const origin = request.headers.origin;
    const route = new URL(request.url, "http://127.0.0.1").pathname.split("/").pop();
    if (request.method === "OPTIONS") {
      const allowed = origin === site.origin;
      response.writeHead(allowed ? 204 : 403, {
        ...corsHeaders(origin),
        ...(allowed
          ? { "Access-Control-Allow-Methods": "POST", "Access-Control-Allow-Headers": "Content-Type" }
          : {}),
      });
      response.end();
      return;
    }
    const raw = await readBody(request);
    const record = {
      route,
      method: request.method,
      origin,
      contentType: request.headers["content-type"],
      cookie: request.headers.cookie ?? null,
      referer: request.headers.referer ?? null,
      raw,
      at: Date.now(),
    };
    collector.requests.push(record);
    const plan = collector.plans.get(route)?.shift();
    if (plan?.hang) return; // never answer: a hung collector
    if (plan?.delay) await new Promise((resolve) => setTimeout(resolve, plan.delay));
    if (plan?.hold) await plan.hold;
    let status;
    let payload;
    let headers = {};
    if (plan?.status) {
      ({ status, headers = {} } = plan);
      payload = plan.body ?? { error: "scripted" };
    } else {
      [status, payload] = defaultResponse(route, JSON.parse(raw || "{}"));
    }
    if (response.destroyed) return;
    response.writeHead(status, {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      ...corsHeaders(origin),
      ...headers,
    });
    response.end(JSON.stringify(payload));
  });
  collector.port = await listen(collectorServer);
  collector.origin = `http://127.0.0.1:${collector.port}`;
  collector.plan = (route, ...steps) => {
    collector.plans.set(route, [...(collector.plans.get(route) ?? []), ...steps]);
  };
  collector.of = (route) => collector.requests.filter((item) => item.route === route);
  collector.reset = () => {
    collector.requests.length = 0;
    collector.plans.clear();
  };

  return {
    site,
    collector,
    close: async () => {
      siteServer.closeAllConnections();
      collectorServer.closeAllConnections();
      await new Promise((resolve) => siteServer.close(resolve));
      await new Promise((resolve) => collectorServer.close(resolve));
    },
  };
}

// Page instrumentation, installed before any page script runs.
export const INSTRUMENT = `(() => {
  const log = [];
  Object.defineProperty(window, "__log", { value: log });
  const wrap = (owner, name, label) => {
    const original = owner[name];
    owner[name] = function (...args) {
      log.push([label, name, String(args[0] ?? "")]);
      return original.apply(this, args);
    };
  };
  for (const name of ["getItem", "setItem", "removeItem", "clear", "key"]) {
    wrap(Storage.prototype, name, "storage");
  }
  const cookie = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
  Object.defineProperty(Document.prototype, "cookie", {
    get() { log.push(["cookie", "get", ""]); return cookie.get.call(this); },
    set(value) { log.push(["cookie", "set", ""]); cookie.set.call(this, value); },
  });
  for (const type of [HTMLInputElement, HTMLSelectElement, HTMLTextAreaElement]) {
    const value = Object.getOwnPropertyDescriptor(type.prototype, "value");
    Object.defineProperty(type.prototype, "value", {
      get() { log.push(["value", this.name, ""]); return value.get.call(this); },
      set(next) { value.set.call(this, next); },
    });
  }
  const radio = Object.getOwnPropertyDescriptor(RadioNodeList.prototype, "value");
  Object.defineProperty(RadioNodeList.prototype, "value", {
    get() { log.push(["value", "radio-list", ""]); return radio.get.call(this); },
    set(next) { radio.set.call(this, next); },
  });
  wrap(Crypto.prototype, "getRandomValues", "random");
  if (Crypto.prototype.randomUUID) wrap(Crypto.prototype, "randomUUID", "random");
  wrap(window, "fetch", "network");
  if (navigator.sendBeacon) wrap(Navigator.prototype, "sendBeacon", "network");
})();`;

export const GPC = `Object.defineProperty(Navigator.prototype, "globalPrivacyControl", { get: () => true });`;
export const NO_SESSION_STORAGE = `Object.defineProperty(window, "sessionStorage", {
  get() { throw new DOMException("Blocked for this test", "SecurityError"); },
});`;

// Storage that can be read but whose writes and removals fail (a full or locked store).
export const FAILING_STORAGE_WRITES = `(() => {
  for (const name of ["setItem", "removeItem"]) {
    Storage.prototype[name] = function () {
      throw new DOMException("Synthetic storage write failure", "QuotaExceededError");
    };
  }
})();`;

export const FORM_CONFIG = {
  lead: {
    fields: [
      { name: "password", data_class: "form.code" },
      { name: "session_token", data_class: "form.code" },
      { name: "card_holder_number", data_class: "form.code" },
      { name: "verification", data_class: "form.code" },
      { name: "otp_box", data_class: "form.code" },
      { name: "contact", data_class: "form.code" },
      { name: "notes", data_class: "form.code" },
      { name: "plan", data_class: "form.option", options: ["basic", "pro"] },
      { name: "size", data_class: "form.option", options: ["s", "m"] },
      { name: "coupon", data_class: "form.code" },
      { name: "qty", data_class: "form.quantity" },
      { name: "disguised", data_class: "form.code" },
    ],
  },
};

// Values that must never leave the browser, and the field names whose values must not be read.
export const FORBIDDEN_VALUES = [
  "MARK-PASSWORD",
  "MARK-HIDDEN",
  "MARK-CARDNUMBER",
  "MARK-CSC",
  "MARK-OTP",
  "mark-email@example.test",
  "MARK-NOTES",
  "MARK-UNKNOWN",
  "4111 1111 1111 1111",
];
export const FORBIDDEN_READS = [
  "password",
  "session_token",
  "card_holder_number",
  "verification",
  "otp_box",
  "contact",
  "notes",
  "unknown_field",
];

export function trackerPage(collectorOrigin, { publicKey = PUBLIC_KEY, extra = "" } = {}) {
  const config = {
    collector: collectorOrigin,
    publicKey,
    forms: FORM_CONFIG,
    bindings: { links: "a[data-track]", forms: { lead: "#lead" } },
  };
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Synthetic shop</title></head>
<body>
<a id="out" data-track href="/next.html?from=link">Continue</a>
<form id="lead" action="/next.html" method="get">
  <input name="password" type="password" value="MARK-PASSWORD">
  <input name="session_token" type="hidden" value="MARK-HIDDEN">
  <input name="card_holder_number" autocomplete="cc-number" value="MARK-CARDNUMBER">
  <input name="verification" autocomplete="cc-csc" value="MARK-CSC">
  <input name="otp_box" autocomplete="one-time-code" value="MARK-OTP">
  <input name="contact" type="email" value="mark-email@example.test">
  <textarea name="notes">MARK-NOTES</textarea>
  <input name="unknown_field" value="MARK-UNKNOWN">
  <select name="plan"><option value="basic">Basic</option><option value="pro" selected>Pro</option></select>
  <label><input type="radio" name="size" value="s"> S</label>
  <label><input type="radio" name="size" value="m" checked> M</label>
  <input name="coupon" value="SPRING-26">
  <input name="qty" type="number" value="3">
  <input name="disguised" value="4111 1111 1111 1111">
  <button id="submit" type="submit">Send</button>
</form>
<button id="accept" type="button">Accept analytics</button>
<script type="module">
  import { createTracker } from "/src/tracker.js";
  const tracker = createTracker(${JSON.stringify(config)});
  window.tracker = tracker;
  document.getElementById("accept").addEventListener("click", () => {
    window.__grant = tracker.grant({ "analytics.first_party": "granted" });
  });
  ${extra}
  window.__ready = true;
</script>
</body></html>`;
}

export async function launch(name) {
  return BROWSERS[name].launch({ headless: true });
}

export async function openPage(browser, url, { init = [] } = {}) {
  const context = await browser.newContext();
  for (const script of [INSTRUMENT, ...init]) await context.addInitScript(script);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.goto(url);
  await page.waitForFunction(() => window.__ready === true);
  return { context, page, errors };
}

export const until = async (check, timeout = 10_000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await check()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error("Condition not met in time.");
};
