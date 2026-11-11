// Real Chromium and Firefox check of R005-23 (final review of PR 4, 2026-11-11): a consent
// grant queued while Global Privacy Control was off must not send a restricted grant once the
// signal has become active. The tracker module talks to the scripted collector over real
// loopback HTTP on a second origin; the collector records the raw body of every request.
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { PUBLIC_KEY, SWITCHABLE_GPC, launch, openPage, startServers, trackerPage, until } from "./harness.js";

const ANALYTICS = "analytics.first_party";
const ATTRIBUTION = "attribution";
const RESTRICTED = ["sale_or_share", "ads.measurement", "ads.personalization"];
const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;

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

    const bodies = (requests) => requests.map((item) => [item.route, JSON.parse(item.raw)]);
    // Grants for a GPC-restricted purpose among the recorded requests.
    const prohibitedGrants = (requests) =>
      requests
        .filter((item) => item.route === "consent")
        .flatMap((item) => Object.entries(JSON.parse(item.raw).choices))
        .filter(([purpose, state]) => state === "granted" && RESTRICTED.includes(purpose));

    // GPC off: an explicit analytics grant whose answer the collector holds, a second grant
    // queued behind it, then (optionally) the signal switched on with no further tracker call.
    async function queuedGrant(choices, { activate }) {
      collector.reset();
      const opened = await openPage(browser, `${site.origin}/shop.html`, { init: [SWITCHABLE_GPC] });
      const { page } = opened;
      assert.equal(await page.evaluate(() => navigator.globalPrivacyControl), false);
      let release;
      collector.plan("consent", {
        hold: new Promise((resolve) => {
          release = resolve;
        }),
      });
      await page.evaluate(() => {
        window.__first = window.tracker.grant({ "analytics.first_party": "granted" });
      });
      await until(() => collector.of("consent").length === 1);
      assert.deepEqual(JSON.parse(collector.of("consent")[0].raw), { choices: { [ANALYTICS]: "granted" } });
      await page.evaluate((queued) => {
        window.__second = window.tracker.grant(queued);
      }, choices);
      await page.waitForTimeout(250);
      assert.equal(collector.requests.length, 1, "the second grant is queued, not started");
      if (activate) {
        await page.evaluate(() => {
          window.__gpc = true;
        });
        assert.equal(await page.evaluate(() => navigator.globalPrivacyControl), true);
      }
      const mark = collector.requests.length;
      release();
      const first = await page.evaluate(() => window.__first);
      assert.equal(first.status, "granted");
      const second = await page.evaluate(() => window.__second);
      await page.waitForTimeout(750);
      const stored = await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY);
      const { token } = JSON.parse(stored);
      const state = await page.evaluate(() => window.tracker.state());
      return { ...opened, token, second, state, later: collector.requests.slice(mark) };
    }

    test("R005-23: a queued grant sends no restricted grant once GPC has become active", async () => {
      for (const purpose of RESTRICTED) {
        const run = await queuedGrant({ [purpose]: "granted" }, { activate: true });
        assert.deepEqual(bodies(run.later), [], `${purpose}: nothing is sent after activation`);
        assert.deepEqual(prohibitedGrants(run.later), [], `${purpose}: no restricted grant on the wire`);
        assert.deepEqual(run.second, { status: "nothing_sent", refused: [purpose] }, purpose);
        assert.deepEqual(run.state.purposes, [ANALYTICS], purpose);
        assert.deepEqual(collector.consent.get(run.token), { [ANALYTICS]: "granted" }, purpose);
        assert.deepEqual(run.errors, [], purpose);
        await run.context.close();
      }
    });

    test("R005-23: a mixed queued grant keeps its permitted choice and drops the restricted ones", async () => {
      const run = await queuedGrant(
        { [ATTRIBUTION]: "granted", sale_or_share: "granted", "ads.personalization": "granted" },
        { activate: true },
      );
      assert.deepEqual(prohibitedGrants(run.later), []);
      assert.deepEqual(bodies(run.later), [
        ["consent", { choices: { [ATTRIBUTION]: "granted" }, subject_token: run.token }],
      ]);
      assert.equal(run.second.status, "granted");
      assert.deepEqual(run.second.purposes, [ANALYTICS, ATTRIBUTION]);
      assert.deepEqual(run.second.refused, ["sale_or_share", "ads.personalization"]);
      assert.deepEqual(run.state.purposes, [ANALYTICS, ATTRIBUTION]);
      assert.deepEqual(collector.consent.get(run.token), { [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
      // Analytics keeps working, and an explicit withdrawal and erasure still reach the subject.
      assert.equal(await run.page.evaluate(() => window.tracker.trackPageView().status), "queued");
      await until(() => collector.of("events").length === 1);
      assert.equal((await run.page.evaluate(() => window.tracker.withdraw(["attribution"]))).confirmed, true);
      assert.equal(collector.consent.get(run.token)[ATTRIBUTION], "withdrawn");
      assert.deepEqual(await run.page.evaluate(() => window.tracker.erase()), { status: "erased", confirmed: true });
      assert.equal(collector.consent.has(run.token), false);
      assert.deepEqual(run.errors, []);
      await run.context.close();
    });

    test("R005-23: a queued grant still succeeds while GPC stays off", async () => {
      const run = await queuedGrant({ sale_or_share: "granted" }, { activate: false });
      assert.deepEqual(bodies(run.later), [
        ["consent", { choices: { sale_or_share: "granted" }, subject_token: run.token }],
      ]);
      assert.equal(run.second.status, "granted");
      assert.deepEqual(run.second.refused, []);
      assert.deepEqual(run.state.purposes, [ANALYTICS, "sale_or_share"]);
      assert.deepEqual(collector.consent.get(run.token), { [ANALYTICS]: "granted", sale_or_share: "granted" });
      assert.deepEqual(run.errors, []);
      await run.context.close();
    });
  });
}
