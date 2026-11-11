// Regressions for the independent review of the Spec 005 corrections (2026-11-11, R005-12 to
// R005-17). Every case asserts what leaves the tracker at its transport boundary (requests and
// their bytes), the collector's resulting consent state, and the tracker's permission and
// queue state. The clock, timers and collector are deterministic and synthetic.
import assert from "node:assert/strict";
import { test } from "node:test";

import { LIMITS, createTracker } from "../../src/tracker.js";
import { COLLECTOR, PUBLIC_KEY, fakeEnvironment } from "../support/fake-environment.js";

const ANALYTICS = "analytics.first_party";
const ATTRIBUTION = "attribution";
const SALE = "sale_or_share";
const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;

function setup(options = {}) {
  const fake = fakeEnvironment(options);
  const tracker = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  return { fake, tracker };
}

const events = (fake) => fake.requests("events").map((item) => JSON.parse(item.body));
const tokenOf = (fake) => JSON.parse(fake.store.get(STORAGE_KEY)).token;
const unavailable = (fake) => () => fake.json(503, { error: "temporarily_unavailable" });
const withdrawals = (fake) =>
  fake
    .requests("consent")
    .map((item) => JSON.parse(item.body))
    .filter((body) => Object.values(body.choices).every((state) => state === "withdrawn"));

test("R005-12: a pending, failed or stale state read never re-enables a confirmed withdrawal", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const token = tokenOf(fake);
  // A state read that started before the withdrawal, answered with the old grant.
  const stale = fake.hold("consent-state");
  const refreshing = tracker.refresh();
  await fake.settle();
  const oldGrant = fake.respond(stale.request);
  assert.equal((await tracker.withdraw([ANALYTICS])).confirmed, true);
  assert.equal(fake.server.get(token)[ANALYTICS], "withdrawn");
  assert.equal(tracker.trackPageView().status, "blocked");
  // The host widens again; the state read is pending, then fails.
  const pending = fake.hold("consent-state");
  const resuming = tracker.resume({ [ANALYTICS]: "granted" });
  await fake.settle();
  assert.equal(tracker.trackPageView().status, "blocked", "pending read");
  pending.release(unavailable(fake));
  assert.equal((await resuming).status, "unavailable");
  assert.equal(tracker.trackPageView().status, "blocked", "failed read");
  stale.release(() => oldGrant);
  assert.equal(await refreshing, false);
  assert.equal(tracker.trackPageView().status, "blocked", "stale read");
  fake.script("consent-state", unavailable(fake));
  assert.equal((await tracker.resume({ [ANALYTICS]: "granted" })).status, "unavailable");
  assert.equal(tracker.trackPageView().status, "blocked", "second failed read");
  await fake.advance(10_000);
  assert.equal(fake.requests("events").length, 0);
  assert.deepEqual(tracker.state().purposes, []);
  assert.equal(fake.server.get(token)[ANALYTICS], "withdrawn");
  // A renewed grant that the collector confirms enables a fresh event again.
  assert.equal((await tracker.grant({ [ANALYTICS]: "granted" })).status, "granted");
  assert.equal(tracker.trackPageView().status, "queued");
  await fake.settle();
  assert.equal(fake.requests("events").length, 1);
  assert.equal(events(fake)[0].subject_token, token);
});

test("R005-12: a server state confirmed before the host widened a purpose cannot enable it", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  assert.equal((await tracker.resume({ [ANALYTICS]: "granted" })).status, "resumed");
  // The collector still reports attribution granted, but only a read after the widening counts.
  const pending = fake.hold("consent-state");
  const resuming = tracker.resume({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  await fake.settle();
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  pending.release();
  assert.equal((await resuming).status, "resumed");
  assert.deepEqual(tracker.state().purposes, [ANALYTICS, ATTRIBUTION]);
});

test("R005-13: a state answer delivered after the grant's expiry never permits capture", async () => {
  for (const path of ["grant", "resume", "refresh"]) {
    const { fake, tracker } = setup();
    await tracker.grant({ [ANALYTICS]: "granted" });
    const token = tokenOf(fake);
    const held = fake.hold(path === "grant" ? "consent" : "consent-state");
    let current = tracker;
    let pending;
    if (path === "grant") {
      pending = tracker.grant({ [ATTRIBUTION]: "granted" });
    } else if (path === "resume") {
      tracker.destroy();
      current = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
      pending = current.resume({ [ANALYTICS]: "granted" });
    } else {
      pending = tracker.refresh();
    }
    await fake.settle();
    // The collector answers with one second left on the analytics grant...
    fake.expireIn(token, ANALYTICS, 1_000);
    const answer = fake.respond(held.request);
    // ...and the answer reaches the browser 2.5 seconds later.
    await fake.advance(2_500);
    held.release(() => answer);
    await pending;
    assert.ok(!current.state().purposes.includes(ANALYTICS), path);
    assert.equal(current.trackPageView().status, "blocked", path);
    await fake.advance(5_000);
    assert.equal(fake.requests("events").length, 0, path);
  }
});

test("R005-13: a late answer ends attribution on time for new events and queued retries", async () => {
  const { fake, tracker } = setup({ href: "https://shop.example.test/p?gclid=c1&utm_source=ad" });
  await tracker.grant({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  const token = tokenOf(fake);
  fake.script("events", () => fake.json(503, {}, { "Retry-After": "4" }));
  tracker.trackPageView();
  await fake.settle();
  assert.match(fake.requests("events")[0].body, /gclid=c1/);
  const held = fake.hold("consent-state");
  const refreshing = tracker.refresh();
  await fake.settle();
  fake.expireIn(token, ATTRIBUTION, 1_000);
  const answer = fake.respond(held.request);
  await fake.advance(2_500);
  held.release(() => answer);
  assert.equal(await refreshing, true);
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  assert.equal(tracker.state().queued, 0, "the retry carrying gclid is discarded");
  tracker.trackPageView();
  await fake.advance(10_000);
  const sent = fake.requests("events").map((item) => item.body);
  assert.equal(sent.length, 2);
  assert.ok(!sent[1].includes("gclid"));
  assert.equal(JSON.parse(sent[1]).payload.url, "https://shop.example.test/p?utm_source=ad");
});

test("R005-13: a grant reported without a valid expiry or server time is not effective", async () => {
  const variants = [
    { expires_at: {} },
    { expires_at: { [ANALYTICS]: "not-a-time" } },
    { server_time: "not-a-time" },
    { server_time: undefined },
  ];
  for (const variant of variants) {
    const { fake, tracker } = setup();
    await tracker.grant({ [ANALYTICS]: "granted" });
    fake.script("consent-state", () =>
      fake.json(200, {
        status: "active",
        states: { [ANALYTICS]: "granted" },
        expires_at: { [ANALYTICS]: new Date(fake.now() + 3_600_000).toISOString() },
        server_time: new Date(fake.now()).toISOString(),
        ...variant,
      }),
    );
    assert.equal(await tracker.refresh(), true);
    assert.deepEqual(tracker.state().purposes, [], JSON.stringify(variant));
    assert.equal(tracker.trackPageView().status, "blocked");
    await fake.settle();
    assert.equal(fake.requests("events").length, 0);
  }
});

test("R005-14: after a full withdrawal no background request carries the subject token", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const token = tokenOf(fake);
  assert.equal((await tracker.withdraw()).confirmed, true);
  const before = fake.log.requests.length;
  fake.dispatch("window", "pageshow", { persisted: true });
  fake.environment.document.hidden = true;
  fake.dispatch("document", "visibilitychange", {});
  fake.environment.document.hidden = false;
  fake.dispatch("document", "visibilitychange", {});
  await fake.advance(LIMITS.refreshMs * 3);
  fake.dispatch("window", "pageshow", { persisted: true });
  fake.dispatch("document", "visibilitychange", {});
  assert.equal(await tracker.refresh(), false);
  await fake.advance(LIMITS.refreshMs);
  assert.deepEqual(fake.log.requests.slice(before), [], "no background traffic");
  assert.equal(fake.pendingTimers(), 0);
  // An explicit erasure still reaches the same subject.
  assert.deepEqual(await tracker.erase(), { status: "erased", confirmed: true });
  const [erasure] = fake.requests("erasure");
  assert.equal(JSON.parse(erasure.body).subject_token, token);
  assert.equal(fake.server.has(token), false);
});

test("R005-15: GPC reconciliation resumes after transient withdrawal failures", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [SALE]: "granted" });
  const token = tokenOf(fake);
  fake.navigator.globalPrivacyControl = true;
  for (let attempt = 0; attempt < 3; attempt += 1) fake.script("consent", unavailable(fake));
  assert.equal(await tracker.refresh(), true);
  await fake.advance(10_000);
  assert.equal(fake.server.get(token)[SALE], "granted");
  assert.deepEqual(tracker.state().purposes, [ANALYTICS], "GPC applies locally throughout");
  assert.equal(tracker.stats().unconfirmed_withdrawals, 1);
  // The collector recovers; the next state read still reports the prohibited grant.
  assert.equal(await tracker.refresh(), true);
  await fake.advance(10_000);
  assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted", [SALE]: "withdrawn" });
  assert.equal(await tracker.refresh(), true);
  await fake.advance(10_000);
  const sent = withdrawals(fake);
  assert.equal(sent.length, 4, "three failed attempts and one confirmed withdrawal");
  for (const body of sent) {
    assert.deepEqual(body, { subject_token: token, choices: { [SALE]: "withdrawn" } });
  }
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  assert.equal(tracker.trackPageView().status, "queued");
});

test("R005-15: GPC reconciliation stays bounded while the collector keeps failing", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [SALE]: "granted" });
  const token = tokenOf(fake);
  fake.navigator.globalPrivacyControl = true;
  for (let attempt = 0; attempt < 30; attempt += 1) fake.script("consent", unavailable(fake));
  for (let round = 0; round < 6; round += 1) {
    assert.equal(await tracker.refresh(), true);
    await fake.advance(10_000);
  }
  assert.equal(withdrawals(fake).length, LIMITS.gpcRounds * LIMITS.maxAttempts);
  assert.equal(fake.server.get(token)[SALE], "granted");
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
});

test("R005-15: a newer grant is withdrawn again when GPC returns", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [SALE]: "granted" });
  const token = tokenOf(fake);
  fake.navigator.globalPrivacyControl = true;
  assert.equal(await tracker.refresh(), true);
  await fake.settle();
  assert.equal(fake.server.get(token)[SALE], "withdrawn");
  fake.navigator.globalPrivacyControl = false;
  const regranted = await tracker.grant({ [SALE]: "granted" });
  assert.deepEqual(regranted.purposes, [ANALYTICS, SALE]);
  assert.equal(fake.server.get(token)[SALE], "granted");
  fake.navigator.globalPrivacyControl = true;
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  assert.equal(await tracker.refresh(), true);
  await fake.settle();
  assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted", [SALE]: "withdrawn" });
  assert.deepEqual(
    fake.requests("consent").map((item) => JSON.parse(item.body).choices),
    [
      { [ANALYTICS]: "granted", [SALE]: "granted" },
      { [SALE]: "withdrawn" },
      { [SALE]: "granted" },
      { [SALE]: "withdrawn" },
    ],
  );
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
});

test("R005-16: an in-flight event narrowed by a withdrawal is never retried after a regrant", async () => {
  const { fake, tracker } = setup({ href: "https://shop.example.test/p?gclid=c1" });
  await tracker.grant({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  const held = fake.hold("events");
  const original = tracker.trackPageView().event_id;
  await fake.settle();
  assert.match(held.request.body, /gclid=c1/);
  assert.equal((await tracker.withdraw([ATTRIBUTION])).confirmed, true);
  assert.equal((await tracker.grant({ [ATTRIBUTION]: "granted" })).status, "granted");
  held.release(() => fake.json(503, {}, { "Retry-After": "1" }));
  await fake.advance(10_000);
  assert.deepEqual(
    events(fake).map((body) => body.event_id),
    [original],
    "the pre-withdrawal event is transmitted exactly once",
  );
  assert.equal(tracker.state().queued, 0);
  // A fresh event after the confirmed regrant is delivered; its own retry keeps its bytes.
  fake.script("events", () => fake.json(503, {}, { "Retry-After": "1" }));
  const fresh = tracker.trackPageView().event_id;
  await fake.advance(5_000);
  const [, failed, retried] = fake.requests("events");
  assert.equal(JSON.parse(failed.body).event_id, fresh);
  assert.equal(retried.body, failed.body);
  assert.match(retried.body, /gclid=c1/);
  assert.equal(tracker.stats().acknowledged, 1);
});

test("R005-17: a stalled state read cannot keep an expired event or block fresh traffic", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  // A hidden page skips the scheduled refresh, so the retry needs a fresh state read.
  fake.environment.document.hidden = true;
  await fake.advance(57_000);
  fake.script("events", () => fake.json(503, {}, { "Retry-After": "5" }));
  const expired = tracker.trackPageView().event_id;
  await fake.settle();
  // From here every state read stalls until it is released or aborted.
  const holds = Array.from({ length: 16 }, () => fake.hold("consent-state"));
  await fake.advance(LIMITS.eventTtlMs + 1_000);
  assert.equal(tracker.state().queued, 0, "the expired payload is removed");
  assert.equal(tracker.stats().dropped_ttl, 1);
  assert.deepEqual(events(fake).map((body) => body.event_id), [expired]);
  // A stalled read is outstanding while an explicit grant confirms the current state.
  const reading = tracker.refresh();
  await fake.settle();
  const outstanding = holds.find((item) => item.request && !item.aborted);
  assert.ok(outstanding, "a state read is still pending");
  assert.equal((await tracker.grant({ [ANALYTICS]: "granted" })).status, "granted");
  const fresh = tracker.trackPageView().event_id;
  await fake.settle();
  assert.deepEqual(events(fake).map((body) => body.event_id), [expired, fresh]);
  // The stalled read answers late with a stale "unknown" state, which is ignored.
  outstanding.release(() =>
    fake.json(200, {
      status: "unknown",
      states: {},
      expires_at: {},
      server_time: new Date(fake.now()).toISOString(),
    }),
  );
  assert.equal(await reading, false);
  assert.equal(tracker.state().collecting, true);
  assert.equal(tracker.trackPageView().status, "queued");
  await fake.settle();
  assert.equal(fake.requests("events").length, 3);
  assert.equal(tracker.state().queued, 0);
});
