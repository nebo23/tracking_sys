// End-to-end synthetic journey through a real browser and the real API (specification 005, E2E).
//
// Driven by backend/tests/integration/test_tracker_journey.py, which starts the API on loopback
// with a disposable database, prepares the client, link, verified synthetic domain and form,
// and asserts the stored rows afterwards. This script serves the destination site, follows the
// branded short link, acts as the visitor, and prints one JSON report of what the browser sent
// and could read. Usage: node journey.js '<json options>'.
import { randomUUID } from "node:crypto";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

process.env.PLAYWRIGHT_BROWSERS_PATH ??= "0";
const { chromium, firefox } = await import("playwright");

const options = JSON.parse(process.argv[2]);
const SOURCE = fileURLToPath(new URL("../../src/", import.meta.url));
const ANALYTICS = "analytics.first_party";

function page(collector) {
  const config = {
    collector,
    publicKey: options.publicKey,
    forms: options.forms,
    bindings: { links: "a[data-track]", forms: { lead: "#lead" } },
  };
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Offer</title></head>
<body>
<a id="out" data-track href="/thanks?from=link">Continue</a>
<form id="lead" action="/thanks" method="get">
  <input name="password" type="password" value="MARK-PASSWORD">
  <input name="card" autocomplete="cc-number" value="MARK-CARD">
  <input name="otp" autocomplete="one-time-code" value="MARK-OTP">
  <input name="contact" type="email" value="mark-person@example.test">
  <textarea name="notes">MARK-NOTES</textarea>
  <select name="plan"><option value="basic">Basic</option><option value="pro" selected>Pro</option></select>
  <input name="coupon" value="SPRING-26">
  <input name="qty" type="number" value="2">
  <button id="submit" type="submit">Send</button>
</form>
<button id="accept" type="button">Accept analytics</button>
<script type="module">
  import { createTracker } from "/src/tracker.js";
  window.tracker = createTracker(${JSON.stringify(config)});
  document.getElementById("accept").addEventListener("click", () => {
    window.__grant = window.tracker.grant({ "${ANALYTICS}": "granted" });
  });
  window.__ready = true;
</script></body></html>`;
}

function serve(port, routes) {
  const server = createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (url.pathname.startsWith("/src/")) {
      const name = url.pathname.slice(5);
      if (/^[a-z]+\.js$/.test(name)) {
        response.writeHead(200, { "Content-Type": "text/javascript", "Cache-Control": "no-store" });
        response.end(await readFile(SOURCE + name));
        return;
      }
    }
    const body = routes[url.pathname];
    response.writeHead(body ? 200 : 404, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
    response.end(body ?? "missing");
  });
  return new Promise((resolve) => server.listen(port, "127.0.0.1", () => resolve(server)));
}

const report = { steps: [], api: [], errors: [] };
const site = await serve(options.sitePort, {
  "/offer": page(options.collector),
  "/thanks": "<!doctype html><title>Thanks</title><h1>Thanks</h1>",
});
const stranger = await serve(options.strangerPort, { "/": "<!doctype html><title>Other site</title>" });
const browserType = { chromium, firefox }[options.browser];
const browser = await browserType.launch({
  headless: true,
  args: options.browser === "chromium" ? [`--host-resolver-rules=MAP ${options.brandedHost} 127.0.0.1`] : [],
  firefoxUserPrefs:
    options.browser === "firefox" ? { "network.dns.localDomains": options.brandedHost } : undefined,
});

try {
  const context = await browser.newContext();
  const tab = await context.newPage();
  tab.on("pageerror", (error) => report.errors.push(String(error)));
  tab.on("request", (request) => {
    const url = new URL(request.url());
    if (url.port === String(options.apiPort)) {
      report.api.push({
        method: request.method(),
        host: url.host,
        path: url.pathname,
        body: request.postData(),
        step: report.steps.length,
      });
    }
  });

  // 1. Follow the branded short link to the destination.
  const first = await tab.goto(options.brandedUrl);
  await tab.waitForFunction(() => window.__ready === true);
  const redirected = first.request().redirectedFrom();
  report.redirect = {
    status: redirected ? (await redirected.response()).status() : null,
    location: redirected ? (await redirected.response()).headers().location : null,
    landing: tab.url(),
  };
  report.brandedCookies = await context.cookies(`http://${options.brandedHost}:${options.apiPort}`);
  // 2. Before consent: wait, then record the page's storage (expected empty).
  await tab.waitForTimeout(500);
  report.steps.push("pre-consent");
  report.preConsentStorage = await tab.evaluate(() => Object.keys(sessionStorage));
  report.preConsentBlocked = await tab.evaluate(() => window.tracker.trackPageView().status);
  // 3. Explicit consent.
  await tab.click("#accept");
  await tab.waitForFunction(() => window.__grant !== undefined);
  report.grant = await tab.evaluate(() => window.__grant);
  report.steps.push("granted");
  report.storageRecord = await tab.evaluate((key) => sessionStorage.getItem(key), `ts:v1:${options.publicKey}`);
  // 4. Page view and form submission on the landing page (carry the link reference).
  const view = tab.waitForResponse((response) => response.url().endsWith("/events"));
  await tab.evaluate(() => window.tracker.trackPageView());
  report.viewStatus = (await view).status();
  const formEvent = tab.waitForRequest((request) => request.url().endsWith("/events"));
  await Promise.all([tab.waitForURL("**/thanks**"), tab.click("#submit")]);
  report.formEnvelope = (await formEvent).postData();
  report.afterSubmit = tab.url();
  // 5. A later page of the same session resumes and tracks a link click (no link reference).
  await tab.goto(`${options.siteOrigin}/offer`);
  await tab.waitForFunction(() => window.__ready === true);
  report.resume = await tab.evaluate(() => window.tracker.resume({ "analytics.first_party": "granted" }));
  const clickEvent = tab.waitForRequest((request) => request.url().endsWith("/events"));
  await Promise.all([tab.waitForURL("**/thanks?from=link"), tab.click("#out")]);
  report.clickEnvelope = (await clickEvent).postData();
  report.steps.push("collected");
  // 6. Withdraw, then confirm the tracker stays blocked and a replay is only acknowledged.
  await tab.goto(`${options.siteOrigin}/offer`);
  await tab.waitForFunction(() => window.__ready === true);
  await tab.evaluate(() => window.tracker.resume({ "analytics.first_party": "granted" }));
  report.withdraw = await tab.evaluate(() => window.tracker.withdraw());
  report.afterWithdraw = await tab.evaluate(() => window.tracker.trackPageView().status);
  const replay = (body) =>
    tab.evaluate(
      async ([url, payload]) => {
        const response = await fetch(url, {
          method: "POST",
          credentials: "omit",
          headers: { "Content-Type": "text/plain;charset=UTF-8" },
          body: payload,
        });
        return { status: response.status, body: await response.json() };
      },
      [`${options.collector}/collect/v1/${options.publicKey}/events`, body],
    );
  report.steps.push("withdrawn");
  const fresh = { ...JSON.parse(report.clickEnvelope), event_id: randomUUID(), occurred_at: new Date().toISOString() };
  report.withdrawnEventId = fresh.event_id;
  report.replayAfterWithdrawal = await replay(JSON.stringify(fresh));
  // 7. Erase the subject; replays stay generic and are not stored.
  const token = JSON.parse(report.formEnvelope).subject_token;
  report.erase = await tab.evaluate(() => window.tracker.erase());
  report.storageAfterErasure = await tab.evaluate(() => Object.keys(sessionStorage));
  report.steps.push("erased");
  report.replayAfterErasure = await replay(report.formEnvelope);
  report.stateAfterErasure = await tab.evaluate(
    async ([url, subject]) => {
      const response = await fetch(url, {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject_token: subject }),
      });
      return response.json();
    },
    [`${options.collector}/collect/v1/${options.publicKey}/consent-state`, token],
  );
  // 8. Retry-After is readable by the registered origin and nothing is readable elsewhere.
  report.retryAfter = await tab.evaluate(
    async ([url, subject]) => {
      for (let attempt = 0; attempt < 12; attempt += 1) {
        const response = await fetch(url, {
          method: "POST",
          credentials: "omit",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subject_token: subject }),
        });
        if (response.status === 429) return { status: 429, header: response.headers.get("Retry-After") };
      }
      return { status: "never_limited" };
    },
    [`${options.collector}/collect/v1/${options.publicKey}/consent-state`, token],
  );
  const other = await context.newPage();
  await other.goto(`http://127.0.0.1:${options.strangerPort}/`);
  report.stranger = await other.evaluate(async (url) => {
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "omit",
        headers: { "Content-Type": "text/plain" },
        body: JSON.stringify({ subject_token: `sbj_${"S".repeat(43)}` }),
      });
      return { readable: true, status: response.status };
    } catch (error) {
      return { readable: false, error: error.name };
    }
  }, `${options.collector}/collect/v1/${options.publicKey}/consent-state`);
  report.cookies = await context.cookies();
  await context.close();
} catch (error) {
  report.failure = String(error?.stack ?? error);
} finally {
  await browser.close();
  site.close();
  stranger.close();
}
process.stdout.write(JSON.stringify(report));
