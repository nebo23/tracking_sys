// Real Chromium and Firefox behavior of the tracker (specification 005-D): pre-consent silence,
// consent continuity and races, storage policy, GPC, form-value exclusion, minimization parity,
// and navigation independence from telemetry failures.
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import {
  FORBIDDEN_READS,
  FORBIDDEN_VALUES,
  GPC,
  NO_SESSION_STORAGE,
  PUBLIC_KEY,
  launch,
  openPage,
  startServers,
  trackerPage,
  until,
} from "./harness.js";

const ANALYTICS = "analytics.first_party";
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

    const shop = (query = "") => `${site.origin}/shop.html${query}`;
    const logOf = (page) => page.evaluate(() => window.__log.map((entry) => [...entry]));
    const grant = async (page) => {
      await page.click("#accept");
      await page.waitForFunction(() => window.__grant !== undefined);
      return page.evaluate(() => window.__grant);
    };

    test("before consent nothing is stored, read, generated or sent, and navigation works", async () => {
      collector.reset();
      const { context, page, errors } = await openPage(browser, shop("?utm_source=ad&email=a@b.co"));
      const results = await page.evaluate(() => [
        window.tracker.trackPageView(),
        window.tracker.trackLinkClick(document.getElementById("out")),
        window.tracker.trackForm("lead", document.getElementById("lead")),
        window.tracker.state(),
      ]);
      assert.deepEqual(results.slice(0, 3), [{ status: "blocked" }, { status: "blocked" }, { status: "blocked" }]);
      assert.equal(results[3].continuity, "none");
      assert.deepEqual(await logOf(page), []);
      await Promise.all([page.waitForURL("**/next.html?from=link"), page.click("#out")]);
      await page.goBack();
      await page.waitForFunction(() => window.__ready === true);
      await Promise.all([page.waitForURL("**/next.html?**"), page.click("#submit")]);
      await page.waitForTimeout(300);
      assert.equal(collector.requests.length, 0);
      assert.deepEqual(await context.cookies(), []);
      assert.deepEqual(errors, []);
      await context.close();
    });

    test("after a grant only mapped, permitted values leave the browser", async () => {
      collector.reset();
      const { context, page, errors } = await openPage(browser, shop("?utm_source=ad&gclid=c1&email=a@b.co"));
      const granted = await grant(page);
      assert.equal(granted.status, "granted");
      assert.deepEqual(granted.purposes, [ANALYTICS]);
      await page.evaluate(() => window.tracker.trackPageView());
      await until(() => collector.of("events").length === 1);
      await Promise.all([page.waitForURL("**/next.html?**"), page.click("#submit")]);
      await until(() => collector.of("events").length === 2);
      const [consent] = collector.of("consent");
      assert.equal(consent.contentType, "application/json");
      assert.deepEqual(JSON.parse(consent.raw), { choices: { [ANALYTICS]: "granted" } });
      const [view, form] = collector.of("events").map((item) => JSON.parse(item.raw));
      assert.equal(view.payload.url, `${site.origin}/shop.html?utm_source=ad`);
      assert.equal(form.event_type, "form_submit");
      assert.deepEqual(form.payload.fields, { plan: "pro", size: "m", coupon: "SPRING-26", qty: 3 });
      for (const item of collector.requests) {
        assert.equal(item.cookie, null);
        assert.equal(item.referer, null);
        for (const value of FORBIDDEN_VALUES) assert.ok(!item.raw.includes(value), value);
        assert.ok(!item.raw.includes("a@b.co") && !item.raw.includes("gclid"));
      }
      assert.equal(collector.of("events")[0].contentType, "text/plain;charset=UTF-8");
      assert.deepEqual(errors, []);
      await context.close();
    });

    test("prohibited controls are excluded before their values are read", async () => {
      collector.reset();
      const { context, page } = await openPage(browser, shop());
      await grant(page);
      await page.evaluate(() => window.__log.splice(0));
      await page.evaluate(() => window.tracker.trackForm("lead", document.getElementById("lead")));
      const reads = (await logOf(page)).filter(([kind]) => kind === "value").map(([, field]) => field);
      for (const field of FORBIDDEN_READS) assert.ok(!reads.includes(field), field);
      assert.deepEqual([...new Set(reads)].sort(), ["coupon", "disguised", "plan", "qty", "size"]);
      await until(() => collector.of("events").length === 1);
      const fields = JSON.parse(collector.of("events")[0].raw).payload.fields;
      assert.equal("disguised" in fields, false);
      await context.close();
    });

    test("reload resumes from the server state without a new grant or a renewed expiry", async () => {
      collector.reset();
      const { context, page } = await openPage(browser, shop());
      await grant(page);
      const first = await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY);
      const stored = JSON.parse(first);
      assert.deepEqual(Object.keys(stored).sort(), ["expiresAt", "purposes", "token", "v"]);
      assert.ok(stored.expiresAt - Date.now() <= 24 * 60 * 60 * 1000);
      await page.reload();
      await page.waitForFunction(() => window.__ready === true);
      assert.deepEqual(await logOf(page), []);
      const resumed = await page.evaluate(() => window.tracker.resume({ "analytics.first_party": "granted" }));
      assert.equal(resumed.status, "resumed");
      assert.equal(collector.of("consent").length, 1);
      assert.equal(collector.of("consent-state").length, 1);
      assert.deepEqual(JSON.parse(collector.of("consent-state")[0].raw), { subject_token: stored.token });
      assert.equal(await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY), first);
      assert.equal((await page.evaluate(() => window.tracker.trackPageView())).status, "queued");
      await until(() => collector.of("events").length === 1);
      const kinds = new Set((await logOf(page)).map(([kind, method]) => `${kind}:${method}`));
      assert.ok(![...kinds].some((kind) => kind.startsWith("cookie")));
      const local = await page.evaluate(() => localStorage.length);
      assert.equal(local, 0);
      assert.deepEqual(await context.cookies(), []);
      await context.close();
    });

    test("withdrawal during a pending grant and stale state reads never re-enable capture", async () => {
      collector.reset();
      let release;
      collector.plan("consent", { hold: new Promise((resolve) => { release = resolve; }) });
      const { context, page } = await openPage(browser, shop());
      await page.click("#accept");
      await until(() => collector.of("consent").length === 1);
      const withdrawing = page.evaluate(() => window.tracker.withdraw());
      assert.equal((await page.evaluate(() => window.tracker.trackPageView())).status, "blocked");
      release();
      const outcome = await withdrawing;
      assert.equal(outcome.confirmed, true);
      assert.equal((await page.evaluate(() => window.__grant)).status, "superseded");
      const withdrawals = collector.of("consent").slice(1).map((item) => JSON.parse(item.raw));
      assert.ok(withdrawals.length >= 1);
      assert.ok(withdrawals.every((body) => body.choices[ANALYTICS] === "withdrawn"));
      assert.equal(await page.evaluate((key) => sessionStorage.getItem(key), STORAGE_KEY), null);
      assert.equal((await page.evaluate(() => window.tracker.trackPageView())).status, "blocked");
      // A state read answered after a newer withdrawal is ignored.
      const second = await openPage(browser, shop());
      await grant(second.page);
      let releaseState;
      collector.plan("consent-state", { hold: new Promise((resolve) => { releaseState = resolve; }) });
      const refreshing = second.page.evaluate(() => window.tracker.refresh());
      await until(() => collector.of("consent-state").length === 1);
      await second.page.evaluate(() => window.tracker.withdraw(["analytics.first_party"]));
      releaseState();
      assert.equal(await refreshing, false);
      assert.equal((await second.page.evaluate(() => window.tracker.trackPageView())).status, "blocked");
      // A page restored from the back/forward cache confirms state before collecting again.
      const third = await openPage(browser, shop());
      await grant(third.page);
      const before = collector.of("consent-state").length;
      await third.page.evaluate(() =>
        window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true })),
      );
      await until(() => collector.of("consent-state").length === before + 1);
      assert.equal(collector.of("events").length, 0);
      await Promise.all([context.close(), second.context.close(), third.context.close()]);
    });

    test("blocked session storage falls back to memory and keys stay per source", async () => {
      collector.reset();
      const blocked = await openPage(browser, shop(), { init: [NO_SESSION_STORAGE] });
      const result = await grant(blocked.page);
      assert.equal(result.status, "granted");
      assert.equal(result.continuity, "memory");
      assert.equal((await blocked.page.evaluate(() => window.tracker.trackPageView())).status, "queued");
      await until(() => collector.of("events").length === 1);
      const other = `pk_${"C".repeat(43)}`;
      site.page("/other.html", trackerPage(collector.origin, { publicKey: other }));
      const { context, page } = await openPage(browser, shop());
      await grant(page);
      await page.goto(`${site.origin}/other.html`);
      await page.waitForFunction(() => window.__ready === true);
      const keys = await page.evaluate(() => Object.keys(sessionStorage));
      assert.deepEqual(keys, [STORAGE_KEY]);
      const resumed = await page.evaluate(() => window.tracker.resume({ "analytics.first_party": "granted" }));
      assert.equal(resumed.status, "needs_grant");
      await Promise.all([blocked.context.close(), context.close()]);
    });

    test("noopener windows start without a copy of the consent record", async () => {
      collector.reset();
      const { context, page } = await openPage(browser, shop());
      await grant(page);
      const isolated = context.waitForEvent("page");
      await page.evaluate(() => window.open("/next.html", "_blank", "noopener"));
      const fresh = await isolated;
      await fresh.waitForLoadState();
      assert.deepEqual(await fresh.evaluate(() => Object.keys(sessionStorage)), []);
      // Without noopener, both engines copy session storage into the new window (observed in
      // Chromium and Firefox); the tracker documents this instead of promising tab isolation.
      const opened = context.waitForEvent("page");
      await page.evaluate(() => window.open("/next.html", "_blank"));
      const child = await opened;
      await child.waitForLoadState();
      const copied = await child.evaluate((key) => sessionStorage.getItem(key) !== null, STORAGE_KEY);
      assert.equal(copied, true);
      await context.close();
    });

    test("Global Privacy Control refuses sale and advertising grants only", async () => {
      collector.reset();
      const { context, page } = await openPage(browser, shop(), { init: [GPC] });
      const result = await page.evaluate(() =>
        window.tracker.grant({
          "analytics.first_party": "granted",
          sale_or_share: "granted",
          "ads.personalization": "granted",
        }),
      );
      assert.deepEqual(result.refused, ["sale_or_share", "ads.personalization"]);
      assert.deepEqual(JSON.parse(collector.of("consent")[0].raw).choices, { [ANALYTICS]: "granted" });
      const none = await page.evaluate(() => window.tracker.grant({ sale_or_share: "granted" }));
      assert.equal(none.status, "nothing_sent");
      assert.equal(collector.of("consent").length, 1);
      await context.close();
    });

    test("navigation and submission continue while the collector hangs, fails or limits", async () => {
      collector.reset();
      const { context, page, errors } = await openPage(browser, shop());
      await grant(page);
      collector.plan("events", { hang: true });
      await Promise.all([page.waitForURL("**/next.html?from=link"), page.click("#out")]);
      await page.goBack();
      await page.waitForFunction(() => window.__ready === true);
      await page.evaluate(() => window.tracker.resume({ "analytics.first_party": "granted" }));
      collector.plan("events", { status: 503, headers: { "Retry-After": "1" } });
      await page.evaluate(() => window.tracker.trackPageView());
      await until(() => collector.of("events").length >= 3, 15_000);
      const [, retried, again] = collector.of("events");
      assert.equal(again.raw, retried.raw);
      assert.ok(again.at - retried.at >= 900);
      collector.plan("events", { status: 429, headers: { "Retry-After": "120" } });
      await page.evaluate(() => window.tracker.trackPageView());
      await until(() => collector.of("events").length === 4);
      await page.waitForTimeout(1_500);
      assert.equal(collector.of("events").length, 4);
      assert.equal((await page.evaluate(() => window.tracker.stats())).failed, 1);
      await Promise.all([page.waitForURL("**/next.html?**"), page.click("#submit")]);
      assert.deepEqual(errors, []);
      await context.close();
      const offline = await openPage(browser, shop());
      await offline.page.route(`${collector.origin}/**`, (route) => route.abort("connectionrefused"));
      await grant(offline.page);
      await Promise.all([offline.page.waitForURL("**/next.html?**"), offline.page.click("#submit")]);
      assert.deepEqual(offline.errors, []);
      await offline.context.close();
    });

    test("review sequences R005-01 to R005-03 hold at the real transport", async () => {
      collector.reset();
      // R005-01: a retry carrying gclid is dropped after a confirmed attribution withdrawal.
      const one = await openPage(browser, shop("?gclid=g1&utm_source=ad"));
      await one.page.evaluate(() =>
        window.tracker.grant({ "analytics.first_party": "granted", attribution: "granted" }),
      );
      collector.plan("events", { status: 503, headers: { "Retry-After": "1" } });
      await one.page.evaluate(() => window.tracker.trackPageView());
      await until(() => collector.of("events").length === 1);
      assert.match(collector.of("events")[0].raw, /gclid=g1/);
      const withdrawn = await one.page.evaluate(() => window.tracker.withdraw(["attribution"]));
      assert.equal(withdrawn.confirmed, true);
      await one.page.waitForTimeout(2_500);
      assert.equal(collector.of("events").length, 1);
      await one.page.evaluate(() => window.tracker.trackPageView());
      await until(() => collector.of("events").length === 2);
      assert.ok(!collector.of("events")[1].raw.includes("gclid"));
      // R005-02: a host denial on an active tracker stops collection at once.
      assert.deepEqual(
        await one.page.evaluate(() => window.tracker.resume({ "analytics.first_party": "denied" })),
        { status: "blocked" },
      );
      assert.equal((await one.page.evaluate(() => window.tracker.trackPageView())).status, "blocked");
      // R005-03: a server expiry shorter than the refresh interval ends capture.
      const two = await openPage(browser, shop());
      await grant(two.page);
      const soon = new Date(Date.now() + 1_000).toISOString();
      collector.plan("consent-state", {
        status: 200,
        body: {
          status: "active",
          states: { [ANALYTICS]: "granted" },
          expires_at: { [ANALYTICS]: soon },
          server_time: new Date().toISOString(),
        },
      });
      assert.equal(await two.page.evaluate(() => window.tracker.refresh()), true);
      await two.page.waitForTimeout(1_500);
      const before = collector.of("events").length;
      assert.equal((await two.page.evaluate(() => window.tracker.trackPageView())).status, "blocked");
      await two.page.waitForTimeout(300);
      assert.equal(collector.of("events").length, before);
      await Promise.all([one.context.close(), two.context.close()]);
    });

    test("the browser engine minimizes the shared fixtures exactly like Python", async () => {
      const { context, page } = await openPage(browser, shop());
      const mismatches = await page.evaluate(async () => {
        const minimize = await import("/src/minimize.js");
        const fixtures = await (await fetch("/fixtures/parity.json")).json();
        const failures = [];
        for (const item of fixtures.urls) {
          let result;
          try {
            result = minimize.minimizePageUrl(item.url, new Set(item.granted));
          } catch (error) {
            result = { rejected: error.reason };
          }
          const canonical = (value) =>
            JSON.stringify(value.rejected ?? [value.url, Object.entries(value.dropped).sort()]);
          const expected = item.rejected ? { rejected: item.rejected } : { url: item.expected, dropped: item.dropped };
          if (canonical(result) !== canonical(expected)) failures.push(item.url);
        }
        for (const item of fixtures.cards) {
          if (minimize.containsCardNumber(item.text) !== item.card) failures.push(item.text);
        }
        return failures;
      });
      assert.deepEqual(mismatches, []);
      await context.close();
    });
  });
}
