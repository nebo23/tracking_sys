// Regressions for the independent review of 2026-11-11 (R005-01 to R005-08). Every case
// asserts what leaves the tracker at its transport boundary, the collector's resulting consent
// state, or the tracker's own permission state.
import assert from "node:assert/strict";
import { test } from "node:test";

import { LIMITS, createTracker } from "../../src/tracker.js";
import { COLLECTOR, PUBLIC_KEY, fakeEnvironment } from "../support/fake-environment.js";

const ANALYTICS = "analytics.first_party";
const ATTRIBUTION = "attribution";
const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;
const LINK_A = "00000000-0000-4000-8000-00000000000a";
const LINK_B = "00000000-0000-4000-8000-00000000000b";

function setup(options = {}) {
  const fake = fakeEnvironment(options);
  const tracker = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  return { fake, tracker };
}

const events = (fake) => fake.requests("events").map((item) => JSON.parse(item.body));
const tokenOf = (fake) => JSON.parse(fake.store.get(STORAGE_KEY)).token;

test("R005-01: a confirmed attribution withdrawal drops queued retries carrying click IDs", async () => {
  const { fake, tracker } = setup({ href: "https://shop.example.test/p?gclid=c1&utm_source=ad" });
  await tracker.grant({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  fake.script("events", () => fake.json(503, {}, { "Retry-After": "2" }));
  tracker.trackPageView();
  await fake.settle();
  assert.match(fake.requests("events")[0].body, /gclid=c1/);
  const withdrawn = await tracker.withdraw([ATTRIBUTION]);
  assert.equal(withdrawn.confirmed, true);
  await fake.advance(10_000);
  assert.equal(fake.requests("events").length, 1, "the retry with gclid must not be sent");
  assert.equal(tracker.stats().dropped_permission, 1);
  tracker.trackPageView();
  await fake.settle();
  const [, fresh] = fake.requests("events");
  assert.ok(!fresh.body.includes("gclid"));
  assert.match(JSON.parse(fresh.body).payload.url, /utm_source=ad/);
});

test("R005-01: eligible retries keep their event ID and exact bytes", async () => {
  const { fake, tracker } = setup({ href: "https://shop.example.test/p?gclid=c1" });
  await tracker.grant({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  fake.script("events", () => fake.json(503, {}, { "Retry-After": "1" }));
  tracker.trackPageView();
  await fake.advance(2_000);
  const [first, retry] = fake.requests("events");
  assert.equal(retry.body, first.body);
});

test("R005-02: a host denial on an active tracker stops new and queued events at once", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const held = fake.hold("events");
  tracker.trackPageView();
  tracker.trackPageView();
  await fake.settle();
  assert.deepEqual(await tracker.resume({ [ANALYTICS]: "denied" }), { status: "blocked" });
  assert.equal(tracker.trackPageView().status, "blocked");
  assert.equal(tracker.state().queued, 1, "only the request already on the wire remains");
  held.release();
  await fake.advance(10_000);
  assert.equal(fake.requests("events").length, 1);
  assert.equal(tracker.state().collecting, false);
});

test("R005-02: a narrower host choice holds while a state read is pending or unavailable", async () => {
  const { fake, tracker } = setup({ href: "https://shop.example.test/p?gclid=c1" });
  await tracker.grant({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  const pending = fake.hold("consent-state");
  const resuming = tracker.resume({ [ANALYTICS]: "granted", [ATTRIBUTION]: "denied" });
  tracker.trackPageView();
  await fake.settle();
  assert.ok(!events(fake)[0].payload.url.includes("gclid"));
  pending.release();
  await resuming;
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  fake.script("consent-state", () => fake.json(503, { error: "temporarily_unavailable" }));
  const unavailable = await tracker.resume({ [ANALYTICS]: "denied" });
  assert.equal(unavailable.status, "blocked");
  assert.equal(tracker.trackPageView().status, "blocked");
  await fake.advance(5_000);
  assert.equal(fake.requests("events").length, 1);
});

test("R005-03: an analytics grant expiring before the next refresh stops capture", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const token = tokenOf(fake);
  fake.expireIn(token, ANALYTICS, 1_000);
  await tracker.refresh();
  await fake.advance(2_000);
  assert.equal(tracker.trackPageView().status, "blocked");
  await fake.settle();
  assert.equal(fake.requests("events").length, 0);
});

test("R005-03: a fresh grant and a resume establish earlier per-purpose deadlines", async () => {
  for (const path of ["grant", "resume"]) {
    const { fake, tracker } = setup();
    await tracker.grant({ [ANALYTICS]: "granted" });
    const token = tokenOf(fake);
    fake.expireIn(token, ANALYTICS, 1_000);
    let current = tracker;
    if (path === "grant") {
      await tracker.grant({ [ATTRIBUTION]: "granted" });
    } else {
      tracker.destroy();
      current = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
      assert.equal((await current.resume({ [ANALYTICS]: "granted" })).status, "resumed");
    }
    await fake.advance(2_000);
    assert.equal(current.trackPageView().status, "blocked", path);
    await fake.settle();
    assert.equal(fake.requests("events").length, 0, path);
  }
});

test("R005-03: an expired attribution grant removes click IDs from new and queued events", async () => {
  const { fake, tracker } = setup({ href: "https://shop.example.test/p?gclid=c1&utm_source=ad" });
  await tracker.grant({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  fake.expireIn(tokenOf(fake), ATTRIBUTION, 1_000);
  await tracker.refresh();
  fake.script("events", () => fake.json(503, {}, { "Retry-After": "2" }));
  tracker.trackPageView();
  await fake.advance(3_000);
  assert.equal(fake.requests("events").length, 1, "the retry carrying gclid is dropped");
  tracker.trackPageView();
  await fake.settle();
  const fresh = events(fake).at(-1);
  assert.equal(fresh.payload.url, "https://shop.example.test/p?utm_source=ad");
});

test("R005-04: background reads never send a token past the local lifetime", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const token = tokenOf(fake);
  fake.environment.document.hidden = true;
  await fake.advance(LIMITS.localLifetimeMs + 1_000);
  fake.environment.document.hidden = false;
  fake.dispatch("document", "visibilitychange", {});
  fake.dispatch("window", "pageshow", { persisted: true });
  await tracker.refresh();
  await fake.advance(5 * 60_000);
  assert.equal(fake.requests("consent-state").length, 0);
  assert.equal(fake.store.has(STORAGE_KEY), false);
  assert.equal(tracker.state().collecting, false);
  assert.equal(fake.pendingTimers(), 0);
  const erased = await tracker.erase();
  assert.deepEqual(erased, { status: "erased", confirmed: true });
  assert.equal(JSON.parse(fake.requests("erasure")[0].body).subject_token, token);
});

test("R005-05: withdrawing one purpose during a pending grant keeps the others", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const token = tokenOf(fake);
  const held = fake.hold("consent");
  const granting = tracker.grant({ [ATTRIBUTION]: "granted" });
  await fake.settle();
  const withdrawing = tracker.withdraw([ATTRIBUTION]);
  held.release();
  await granting;
  assert.equal((await withdrawing).confirmed, true);
  assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted", [ATTRIBUTION]: "withdrawn" });
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  assert.equal(tracker.trackPageView().status, "queued");
  await fake.settle();
  assert.equal(fake.requests("events").length, 1);
});

test("R005-06: GPC narrows an existing subject's grants locally and on the server", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", sale_or_share: "granted" });
  const token = tokenOf(fake);
  assert.deepEqual(tracker.state().purposes, [ANALYTICS, "sale_or_share"]);
  fake.navigator.globalPrivacyControl = true;
  const result = await tracker.grant({ [ANALYTICS]: "granted", sale_or_share: "granted" });
  assert.deepEqual(result.refused, ["sale_or_share"]);
  assert.ok(!result.purposes.includes("sale_or_share"));
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  await fake.settle();
  assert.equal(fake.server.get(token).sale_or_share, "withdrawn");
  assert.equal(fake.server.get(token)[ANALYTICS], "granted");
  const reloaded = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  fake.server.get(token)["ads.measurement"] = "granted";
  await reloaded.resume({ [ANALYTICS]: "granted", "ads.measurement": "granted" });
  await fake.settle();
  assert.deepEqual(reloaded.state().purposes, [ANALYTICS]);
  assert.equal(fake.server.get(token)["ads.measurement"], "withdrawn");
});

test("R005-07: each page view carries the current route's link reference", async () => {
  const { fake, tracker } = setup({ href: "https://shop.example.test/home" });
  await tracker.grant({ [ANALYTICS]: "granted" });
  for (const href of [
    "https://shop.example.test/home",
    `https://shop.example.test/a?ts_link=${LINK_A}`,
    `https://shop.example.test/b?ts_link=${LINK_B}`,
    "https://shop.example.test/plain",
  ]) {
    fake.navigate(href);
    tracker.trackPageView();
    await fake.settle();
  }
  assert.deepEqual(
    events(fake).map((body) => body.link_id ?? null),
    [null, LINK_A, LINK_B, null],
  );
  fake.navigate(`https://shop.example.test/a?ts_link=${LINK_A}`);
  fake.script("events", () => fake.json(503, {}, { "Retry-After": "1" }));
  tracker.trackPageView();
  await fake.settle();
  fake.navigate(`https://shop.example.test/b?ts_link=${LINK_B}`);
  await fake.advance(2_000);
  const [failed, retried] = fake.requests("events").slice(-2);
  assert.equal(retried.body, failed.body);
  assert.equal(JSON.parse(retried.body).link_id, LINK_A);
});

test("R005-08: a stalled request is aborted at its lifetime and fresh events continue", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const stalled = fake.hold("events");
  const first = tracker.trackPageView().event_id;
  const second = tracker.trackPageView().event_id;
  await fake.advance(LIMITS.eventTtlMs + 1_000);
  assert.equal(stalled.aborted, true);
  assert.equal(tracker.state().queued, 0);
  assert.equal(tracker.stats().failed + tracker.stats().dropped_ttl, 2);
  const fresh = tracker.trackPageView().event_id;
  await fake.settle();
  const sent = events(fake).map((body) => body.event_id);
  assert.deepEqual(sent, [first, fresh]);
  assert.ok(!sent.includes(second));
  assert.equal(tracker.stats().acknowledged, 1);
});
