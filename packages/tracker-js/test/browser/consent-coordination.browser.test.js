// Real Chromium and Firefox races from the independent review of tracker 0.5.2 (2026-11-11):
// R005-19, a queued resume after a newer host denial, and R005-20, a state read overlapping
// an explicit grant. The published tracker module talks to the scripted collector over real
// loopback HTTP on a second origin; every request the collector receives is recorded.
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { PUBLIC_KEY, launch, openPage, startServers, trackerPage, until } from "./harness.js";

const ANALYTICS = "analytics.first_party";
const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;
const HOUR_MS = 60 * 60 * 1000;

function gate() {
  let open;
  const closed = new Promise((resolve) => {
    open = resolve;
  });
  return { closed, open };
}

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

    // A page whose subject granted analytics and then confirmed a full withdrawal: the token
    // stays in the tracker's memory and the collector reports analytics withdrawn.
    async function withdrawnSubject() {
      collector.reset();
      const opened = await openPage(browser, `${site.origin}/shop.html`);
      const { page } = opened;
      await page.click("#accept");
      await page.waitForFunction(() => window.__grant !== undefined);
      assert.equal((await page.evaluate(() => window.__grant)).status, "granted");
      const stored = await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY);
      const { token } = JSON.parse(stored);
      assert.equal((await page.evaluate(() => window.tracker.withdraw())).confirmed, true);
      assert.equal(collector.consent.get(token)[ANALYTICS], "withdrawn");
      return { ...opened, token };
    }

    const bodies = (requests) => requests.map((item) => [item.route, JSON.parse(item.raw)]);
    const view = (page) => page.evaluate(() => window.tracker.trackPageView().status);

    test("R005-19: a queued resume sends no subject token after a newer host denial", async () => {
      const { context, page, errors, token } = await withdrawnSubject();
      // A host-confirmed resume whose state response the collector holds.
      const state = gate();
      collector.plan("consent-state", { hold: state.closed });
      await page.evaluate(() => {
        window.__first = window.tracker.resume({ "analytics.first_party": "granted" });
      });
      await until(() => collector.of("consent-state").length === 1);
      assert.deepEqual(JSON.parse(collector.of("consent-state")[0].raw), { subject_token: token });
      // A second resume waits behind it.
      await page.evaluate(() => {
        window.__second = window.tracker.resume({ "analytics.first_party": "granted" });
      });
      // In a later browser turn the host supplies a newer decision denying analytics.
      const denied = await page.evaluate(() => window.tracker.resume({ "analytics.first_party": "denied" }));
      assert.deepEqual(denied, { status: "blocked" });
      const mark = collector.requests.length;
      state.open();
      const outcomes = [await page.evaluate(() => window.__first), await page.evaluate(() => window.__second)];
      await page.waitForTimeout(750);
      assert.deepEqual(bodies(collector.requests.slice(mark)), [], "no request after the denial");
      assert.deepEqual(outcomes, [{ status: "superseded" }, { status: "superseded" }]);
      assert.equal(await view(page), "blocked");
      assert.equal(collector.of("events").length, 0);
      // The subject grants again elsewhere: a later valid resume reads the state exactly once.
      collector.consent.get(token)[ANALYTICS] = "granted";
      collector.expiries.get(token)[ANALYTICS] = Date.now() + HOUR_MS;
      const resumed = await page.evaluate(() => window.tracker.resume({ "analytics.first_party": "granted" }));
      assert.equal(resumed.status, "resumed");
      assert.deepEqual(resumed.purposes, [ANALYTICS]);
      assert.deepEqual(bodies(collector.requests.slice(mark)), [["consent-state", { subject_token: token }]]);
      assert.equal(await view(page), "queued");
      await until(() => collector.of("events").length === 1);
      assert.equal(JSON.parse(collector.of("events")[0].raw).subject_token, token);
      // An explicit erasure still reaches the same subject.
      assert.deepEqual(await page.evaluate(() => window.tracker.erase()), { status: "erased", confirmed: true });
      assert.deepEqual(bodies(collector.of("erasure")), [["erasure", { subject_token: token }]]);
      assert.equal(collector.consent.has(token), false);
      assert.deepEqual(errors, []);
      await context.close();
    });

    // One overlap of a pending explicit grant with a state read. order: which of the two the
    // collector processes first; the read's answer always reaches the page first. trigger: an
    // explicit refresh or a page restored from the back/forward cache. withdraw: the visitor
    // withdraws again before the grant's answer arrives.
    async function overlap({ order, trigger, withdraw = false }) {
      const label = `${order}, ${trigger}${withdraw ? ", newer withdrawal" : ""}`;
      const { context, page, errors, token } = await withdrawnSubject();
      const consent = gate();
      collector.plan("consent", order === "read first" ? { hold: consent.closed } : { holdReply: consent.closed });
      await page.evaluate(() => {
        window.__late = window.tracker.grant({ "analytics.first_party": "granted" });
      });
      await until(() => collector.of("consent").length === 3);
      assert.deepEqual(JSON.parse(collector.of("consent")[2].raw), {
        subject_token: token,
        choices: { [ANALYTICS]: "granted" },
      });
      const committed = order === "read first" ? "withdrawn" : "granted";
      await until(() => collector.consent.get(token)[ANALYTICS] === committed);
      // The state read starts after the grant and is answered while the grant is pending.
      await page.evaluate(async (restored) => {
        if (restored) window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
        await window.tracker.refresh();
      }, trigger === "restored page");
      assert.equal(collector.of("consent-state").length, 1, label);
      assert.deepEqual(JSON.parse(collector.of("consent-state")[0].raw), { subject_token: token }, label);
      if (withdraw) {
        await page.evaluate(() => {
          window.__withdrawal = window.tracker.withdraw(["analytics.first_party"]);
        });
        assert.equal(await view(page), "blocked", label);
      }
      const reads = collector.of("consent-state").length;
      // The grant commits (or its delayed answer is released) and reaches the page.
      consent.open();
      const late = await page.evaluate(() => window.__late);
      if (withdraw) {
        assert.equal(late.status, "superseded", label);
        assert.equal((await page.evaluate(() => window.__withdrawal)).confirmed, true, label);
        await page.waitForTimeout(500);
        assert.equal(collector.consent.get(token)[ANALYTICS], "withdrawn", label);
        assert.deepEqual((await page.evaluate(() => window.tracker.state())).purposes, [], label);
        assert.equal(await view(page), "blocked", label);
        assert.equal(collector.of("events").length, 0, label);
        assert.equal(collector.of("consent-state").length, reads, "no state read after the withdrawal");
      } else {
        assert.equal(late.status, "granted", label);
        assert.deepEqual(late.purposes, [ANALYTICS], label);
        assert.equal(collector.consent.get(token)[ANALYTICS], "granted", label);
        const state = await page.evaluate(() => window.tracker.state());
        assert.deepEqual(state.purposes, [ANALYTICS], label);
        assert.equal(state.collecting, true, label);
        assert.equal(await view(page), "queued", label);
        await until(() => collector.of("events").length === 1);
        const sent = JSON.parse(collector.of("events")[0].raw);
        assert.equal(sent.event_type, "page_view", label);
        assert.equal(sent.subject_token, token, label);
        assert.equal(collector.consent.get(token)[ANALYTICS], "granted", label);
      }
      assert.deepEqual(errors, [], label);
      await context.close();
    }

    test("R005-20: a state read answered before a pending grant commits never hides the grant", async () => {
      await overlap({ order: "read first", trigger: "refresh" });
      await overlap({ order: "read first", trigger: "restored page" });
    });

    test("R005-20: a state read processed after the grant committed leaves the grant in place", async () => {
      await overlap({ order: "grant first", trigger: "refresh" });
      await overlap({ order: "grant first", trigger: "restored page" });
    });

    test("R005-20: a newer local withdrawal still wins over the late grant in either order", async () => {
      await overlap({ order: "read first", trigger: "refresh", withdraw: true });
      await overlap({ order: "grant first", trigger: "restored page", withdraw: true });
    });
  });
}
