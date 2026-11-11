// The shipped installation example in real Chromium and Firefox (review findings R005-09 and
// R005-18). The committed examples/install.html and its module run unchanged under their own
// Content Security Policy, with session storage available, with access to it blocked, and with
// its writes failing. The example's collector origin is answered by an intercepted synthetic
// collector, so nothing leaves the loopback test environment.
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { FAILING_STORAGE_WRITES, NO_SESSION_STORAGE, launch, startServers } from "./harness.js";

const COLLECTOR = "https://collect.example.test";
const TOKEN = `sbj_${"E".repeat(43)}`;
const PURPOSES = [
  "analytics.first_party",
  "attribution",
  "identity_link",
  "ads.measurement",
  "ads.personalization",
  "sale_or_share",
];
const STORAGE_MODES = {
  available: [],
  "access blocked": [NO_SESSION_STORAGE],
  "writes failing": [FAILING_STORAGE_WRITES],
};

for (const name of ["chromium", "firefox"]) {
  describe(`${name}: installation example`, () => {
    let browser;
    let servers;

    before(async () => {
      servers = await startServers();
      browser = await launch(name);
    });

    after(async () => {
      await browser?.close();
      await servers?.close();
    });

    for (const [mode, init] of Object.entries(STORAGE_MODES)) {
      test(`storage ${mode}: banner, consent, withdrawal and erasure work under the CSP`, async () => {
        const context = await browser.newContext();
        await context.addInitScript(() => {
          window.__violations = [];
          document.addEventListener("securitypolicyviolation", (event) => {
            window.__violations.push(`${event.violatedDirective} ${event.blockedURI}`);
          });
        });
        for (const script of init) await context.addInitScript(script);
        const page = await context.newPage();
        const origin = servers.site.origin;
        const collected = [];
        const loaded = [];
        page.on("request", (request) => {
          if (request.url().startsWith(origin)) loaded.push(new URL(request.url()).pathname);
        });
        await page.route(`${COLLECTOR}/**`, async (route) => {
          const request = route.request();
          const cors = { "Access-Control-Allow-Origin": origin, Vary: "Origin" };
          if (request.method() === "OPTIONS") {
            await route.fulfill({
              status: 204,
              headers: {
                ...cors,
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "Content-Type",
              },
            });
            return;
          }
          collected.push({ path: new URL(request.url()).pathname, body: request.postData() });
          const consent = request.url().endsWith("/consent");
          const body = consent
            ? {
                subject_token: TOKEN,
                receipts: [],
                states: { "analytics.first_party": "granted" },
                expires_at: {
                  "analytics.first_party": new Date(Date.now() + 86_400_000).toISOString(),
                },
                server_time: new Date().toISOString(),
              }
            : { status: "received" };
          await route.fulfill({
            status: consent ? 200 : 202,
            contentType: "application/json",
            headers: cors,
            body: JSON.stringify(body),
          });
        });
        const errors = [];
        page.on("pageerror", (error) => errors.push(String(error)));
        const routes = () => collected.map((item) => item.path.split("/").pop());
        const waitFor = async (count, label) => {
          const deadline = Date.now() + 5_000;
          while (collected.length < count) {
            assert.ok(Date.now() < deadline, label);
            await new Promise((resolve) => setTimeout(resolve, 25));
          }
        };

        await page.goto(`${origin}/examples/install.html`);
        await page.waitForSelector("#consent-banner:not([hidden])", { timeout: 5_000 });
        assert.ok(loaded.includes("/examples/install.js"), "the initializer module loads");
        assert.ok(loaded.some((path) => /\/assets\/tracker-[0-9.]+\/tracker\.js$/.test(path)));
        await page.waitForTimeout(300);
        assert.deepEqual(collected, [], "nothing is sent before consent");
        // Explicit grant, then a page view.
        await page.click("#accept");
        await page.waitForFunction(() => document.getElementById("consent-banner").hidden);
        await waitFor(2, "a page view follows the explicit grant");
        assert.deepEqual(routes(), ["consent", "events"]);
        assert.deepEqual(JSON.parse(collected[0].body), {
          choices: { "analytics.first_party": "granted" },
        });
        const view = JSON.parse(collected[1].body);
        assert.equal(view.event_type, "page_view");
        assert.equal(view.subject_token, TOKEN);
        // Withdrawal reaches the tracker and the collector whatever storage does.
        await page.click("#withdraw");
        await waitFor(3, "the withdrawal is sent");
        assert.deepEqual(JSON.parse(collected[2].body), {
          subject_token: TOKEN,
          choices: Object.fromEntries(PURPOSES.map((purpose) => [purpose, "withdrawn"])),
        });
        // Erasure reaches the same subject.
        await page.click("#erase");
        await waitFor(4, "the erasure is sent");
        assert.deepEqual(routes(), ["consent", "events", "consent", "erasure"]);
        assert.deepEqual(JSON.parse(collected[3].body), { subject_token: TOKEN });
        await page.waitForTimeout(300);
        assert.equal(collected.length, 4, "nothing else is sent");
        assert.deepEqual(await page.evaluate(() => window.__violations), []);
        assert.deepEqual(errors, []);
        await context.close();
      });
    }
  });
}
