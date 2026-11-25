// Real Chromium and Firefox checks of the specification 006 tracker additions (D-075, JV23):
// identityHandoff(challenge) and restart(). The tracker talks to the scripted collector over
// real loopback HTTP on a second origin; the collector records the raw body of every request.
// Synthetic values only; nothing leaves 127.0.0.1.
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { PUBLIC_KEY, launch, openPage, startServers, trackerPage, until } from "./harness.js";

const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;
const CHALLENGE = "Zm9vYmFyYmF6cXV4cXV1eGNvcmdl";

for (const name of ["chromium", "firefox"]) {
  describe(name, () => {
    let browser;
    let servers;
    let site;
    let collector;

    before(async () => {
      servers = await startServers();
      ({ site, collector } = servers);
      site.page("/shop.html", trackerPage(collector.origin));
      browser = await launch(name);
    });

    after(async () => {
      await browser?.close();
      await servers?.close();
    });

    async function granted(page) {
      return page.evaluate(async () => {
        const result = await window.tracker.grant({
          "analytics.first_party": "granted",
          identity_link: "granted",
        });
        return result.status;
      });
    }

    test("a handoff code travels only in bodies and is never stored", async () => {
      collector.reset();
      const { page, context, errors } = await openPage(browser, `${site.origin}/shop.html`);
      assert.equal(await granted(page), "granted");
      const issued = await page.evaluate((value) => window.tracker.identityHandoff(value), CHALLENGE);
      assert.equal(issued.status, "issued");
      const [request] = collector.of("identity-handoff");
      assert.equal(JSON.parse(request.raw).challenge, CHALLENGE);
      assert.equal(request.cookie, null);
      assert.equal(request.referer, null);
      const stored = await page.evaluate(() => JSON.stringify({ ...sessionStorage, ...localStorage }));
      assert.ok(!stored.includes(issued.code) && !stored.includes(CHALLENGE));
      assert.ok(!page.url().includes(issued.code));
      assert.deepEqual(errors, []);
      await context.close();
    });

    test("restart ignores a late handoff and never sends the old token again", async () => {
      collector.reset();
      const { page, context, errors } = await openPage(browser, `${site.origin}/shop.html`);
      assert.equal(await granted(page), "granted");
      const oldToken = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).token, STORAGE_KEY);
      let release;
      collector.plan("identity-handoff", { holdReply: new Promise((resolve) => (release = resolve)) });
      await page.evaluate((value) => {
        window.__late = window.tracker.identityHandoff(value);
      }, CHALLENGE);
      await until(() => collector.of("identity-handoff").length === 1);
      const restarted = await page.evaluate(() => window.tracker.restart());
      assert.deepEqual(restarted, { status: "restarted" });
      release();
      assert.deepEqual(await page.evaluate(() => window.__late), { status: "unavailable" });
      assert.equal(await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY), null);
      assert.equal(await page.evaluate(() => window.tracker.trackPageView().status), "blocked");
      const before = collector.requests.length;
      assert.equal(
        await page.evaluate(async () => (await window.tracker.grant({ "analytics.first_party": "granted" })).status),
        "granted",
      );
      const later = collector.requests.slice(before);
      assert.ok(later.length >= 1);
      assert.ok(later.every((item) => !item.raw.includes(oldToken)));
      assert.equal(JSON.parse(later[0].raw).subject_token, undefined);
      const newToken = await page.evaluate((key) => JSON.parse(sessionStorage.getItem(key)).token, STORAGE_KEY);
      assert.notEqual(newToken, oldToken);
      assert.deepEqual(errors, []);
      await context.close();
    });

    test("a subject created by a grant answered after restart is never adopted", async () => {
      collector.reset();
      const { page, context, errors } = await openPage(browser, `${site.origin}/shop.html`);
      let release;
      collector.plan("consent", { holdReply: new Promise((resolve) => (release = resolve)) });
      await page.evaluate(() => {
        window.__grant = window.tracker.grant({ "analytics.first_party": "granted", identity_link: "granted" });
      });
      await until(() => collector.of("consent").length === 1);
      await page.evaluate(() => window.tracker.restart());
      release();
      assert.equal((await page.evaluate(() => window.__grant)).status, "superseded");
      assert.equal(await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY), null);
      assert.deepEqual(await page.evaluate(() => window.tracker.state().purposes), []);
      assert.deepEqual(await page.evaluate((value) => window.tracker.identityHandoff(value), CHALLENGE), {
        status: "blocked",
      });
      assert.equal(collector.of("identity-handoff").length, 0);
      assert.deepEqual(errors, []);
      await context.close();
    });
  });
}
