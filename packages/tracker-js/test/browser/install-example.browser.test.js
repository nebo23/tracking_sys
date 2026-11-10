// The shipped installation example in real Chromium and Firefox (review finding R005-09).
// The committed examples/install.html and its module run unchanged under their own Content
// Security Policy; the example's collector origin is answered by an intercepted synthetic
// collector, so nothing leaves the loopback test environment.
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { launch, startServers } from "./harness.js";

const COLLECTOR = "https://collect.example.test";

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

    test("loads under its CSP, shows the banner, and collects only after a grant", async () => {
      const context = await browser.newContext();
      await context.addInitScript(() => {
        window.__violations = [];
        document.addEventListener("securitypolicyviolation", (event) => {
          window.__violations.push(`${event.violatedDirective} ${event.blockedURI}`);
        });
      });
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
        const now = new Date().toISOString();
        const body = request.url().endsWith("/consent")
          ? {
              subject_token: `sbj_${"E".repeat(43)}`,
              receipts: [],
              states: { "analytics.first_party": "granted" },
              expires_at: {
                "analytics.first_party": new Date(Date.now() + 86_400_000).toISOString(),
              },
              server_time: now,
            }
          : { status: "received" };
        await route.fulfill({
          status: request.url().endsWith("/consent") ? 200 : 202,
          contentType: "application/json",
          headers: cors,
          body: JSON.stringify(body),
        });
      });
      const errors = [];
      page.on("pageerror", (error) => errors.push(String(error)));
      await page.goto(`${origin}/examples/install.html`);
      await page.waitForSelector("#consent-banner:not([hidden])", { timeout: 5_000 });
      assert.ok(loaded.includes("/examples/install.js"), "the initializer module loads");
      assert.ok(loaded.some((path) => /\/assets\/tracker-[0-9.]+\/tracker\.js$/.test(path)));
      await page.waitForTimeout(300);
      assert.deepEqual(collected, [], "nothing is sent before consent");
      assert.deepEqual(await page.evaluate(() => window.__violations), []);
      await page.click("#accept");
      await page.waitForFunction(() => document.getElementById("consent-banner").hidden);
      const deadline = Date.now() + 5_000;
      while (collected.filter((item) => item.path.endsWith("/events")).length === 0) {
        assert.ok(Date.now() < deadline, "a page view follows the explicit grant");
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
      assert.deepEqual(
        collected.map((item) => item.path.split("/").pop()),
        ["consent", "events"],
      );
      assert.deepEqual(JSON.parse(collected[0].body), {
        choices: { "analytics.first_party": "granted" },
      });
      assert.equal(JSON.parse(collected[1].body).event_type, "page_view");
      assert.deepEqual(await page.evaluate(() => window.__violations), []);
      assert.deepEqual(errors, []);
      await context.close();
    });
  });
}
