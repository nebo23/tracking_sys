// Tracker consent state machine, storage policy and transport (specification 005-D, D-033).
import assert from "node:assert/strict";
import { test } from "node:test";

import { LIMITS, createTracker } from "../../src/tracker.js";
import { COLLECTOR, PUBLIC_KEY, fakeEnvironment } from "../support/fake-environment.js";

const ANALYTICS = "analytics.first_party";
const LINK = "00000000-0000-4000-8000-000000000123";
const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;

function setup(options = {}) {
  const fake = fakeEnvironment(options);
  const tracker = createTracker(
    { collector: COLLECTOR, publicKey: PUBLIC_KEY, ...options.config },
    fake.environment,
  );
  return { fake, tracker };
}

const bodies = (fake, route = "events") => fake.requests(route).map((item) => JSON.parse(item.body));

test("configuration is validated and never needs a private key", () => {
  const fake = fakeEnvironment();
  for (const config of [
    { collector: "https://collect.example.test/path", publicKey: PUBLIC_KEY },
    { collector: "ftp://collect.example.test", publicKey: PUBLIC_KEY },
    { collector: COLLECTOR, publicKey: "tsk_private" },
    { collector: COLLECTOR, publicKey: PUBLIC_KEY, forms: { lead: { fields: [{ name: "email", data_class: "contact.email" }] } } },
  ]) {
    assert.throws(() => createTracker(config, fake.environment), TypeError);
  }
  assert.equal(fake.log.requests.length, 0);
});

test("before consent nothing is read, stored, generated or sent", async () => {
  const { fake, tracker } = setup();
  for (const result of [
    tracker.trackPageView(),
    tracker.trackLinkClick({ href: "https://shop.example.test/x" }),
    tracker.trackForm("lead", { elements: {} }),
  ]) {
    assert.deepEqual(result, { status: "blocked" });
  }
  await fake.advance(120_000);
  assert.deepEqual(fake.log.storage, []);
  assert.equal(fake.log.location, 0);
  assert.equal(fake.log.requests.length, 0);
  assert.equal(tracker.state().queued, 0);
  const denied = await tracker.grant({ [ANALYTICS]: "denied" });
  assert.equal(denied.status, "nothing_granted");
  assert.deepEqual(fake.log.storage, []);
});

test("an explicit grant sends one request and stores only the token, purposes and fixed expiry", async () => {
  const { fake, tracker } = setup();
  const result = await tracker.grant({ [ANALYTICS]: "granted", attribution: "denied" });
  assert.equal(result.status, "granted");
  assert.deepEqual(result.purposes, [ANALYTICS]);
  const [request] = fake.requests("consent");
  assert.equal(fake.log.requests.length, 1);
  assert.equal(request.credentials, "omit");
  assert.equal(request.referrerPolicy, "no-referrer");
  assert.equal(request.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(request.body), { choices: { [ANALYTICS]: "granted", attribution: "denied" } });
  const record = JSON.parse(fake.store.get(STORAGE_KEY));
  assert.deepEqual(Object.keys(record).sort(), ["expiresAt", "purposes", "token", "v"]);
  assert.equal(record.expiresAt, fake.environment.now() + LIMITS.localLifetimeMs);
  assert.deepEqual(record.purposes, [ANALYTICS]);
  assert.equal(tracker.state().continuity, "session");
});

test("GPC refuses sale, sharing and advertising grants without granting anything else", async () => {
  const { fake, tracker } = setup({ gpc: true });
  const refused = await tracker.grant({ sale_or_share: "granted", "ads.measurement": "granted" });
  assert.equal(refused.status, "nothing_sent");
  assert.deepEqual(refused.refused, ["sale_or_share", "ads.measurement"]);
  assert.equal(fake.log.requests.length, 0);
  const mixed = await tracker.grant({ [ANALYTICS]: "granted", "ads.personalization": "granted" });
  assert.deepEqual(mixed.refused, ["ads.personalization"]);
  assert.deepEqual(JSON.parse(fake.requests("consent")[0].body).choices, { [ANALYTICS]: "granted" });
  const { fake: plain, tracker: other } = setup({ gpc: false });
  await other.grant({ [ANALYTICS]: "denied" });
  assert.equal(other.state().collecting, false);
  assert.equal(plain.requests("consent").length, 1);
});

test("resume reads state without granting, renewing or extending anything", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const stored = JSON.parse(fake.store.get(STORAGE_KEY));
  tracker.destroy();
  await fake.advance(60 * 60 * 1000);
  const reloaded = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  const resumed = await reloaded.resume({ [ANALYTICS]: "granted" });
  assert.equal(resumed.status, "resumed");
  assert.equal(fake.requests("consent").length, 1);
  assert.equal(fake.requests("consent-state").length, 1);
  assert.deepEqual(JSON.parse(fake.requests("consent-state")[0].body), { subject_token: stored.token });
  assert.equal(JSON.parse(fake.store.get(STORAGE_KEY)).expiresAt, stored.expiresAt);
  assert.equal(reloaded.trackPageView().status, "queued");
  const notWanted = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  assert.deepEqual(await notWanted.resume({ [ANALYTICS]: "denied" }), { status: "blocked" });
});

test("resume stays blocked for unknown, withdrawn or locally expired consent", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const token = JSON.parse(fake.store.get(STORAGE_KEY)).token;
  fake.server.get(token)[ANALYTICS] = "withdrawn";
  const withdrawn = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  assert.equal((await withdrawn.resume({ [ANALYTICS]: "granted" })).status, "needs_grant");
  assert.equal(withdrawn.trackPageView().status, "blocked");
  fake.server.delete(token);
  const erased = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  assert.equal((await erased.resume({ [ANALYTICS]: "granted" })).status, "needs_grant");
  assert.equal(fake.store.has(STORAGE_KEY), false);
  const before = fake.requests("consent").length;
  assert.equal(fake.requests("consent").length, before);
  const { fake: aged, tracker: first } = setup();
  await first.grant({ [ANALYTICS]: "granted" });
  await aged.advance(LIMITS.localLifetimeMs + 1);
  const late = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, aged.environment);
  const requests = aged.log.requests.length;
  assert.equal((await late.resume({ [ANALYTICS]: "granted" })).status, "needs_grant");
  assert.equal(aged.log.requests.length, requests);
  assert.equal(first.trackPageView().status, "blocked");
});

test("capture is blocked once a state refresh is due and a remote withdrawal stops it", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  fake.environment.document.hidden = true;
  await fake.advance(LIMITS.refreshMs + 1);
  assert.equal(tracker.trackPageView().status, "blocked");
  await fake.settle();
  assert.equal(fake.requests("consent-state").length, 1);
  assert.equal(tracker.trackPageView().status, "queued");
  const token = JSON.parse(fake.store.get(STORAGE_KEY)).token;
  fake.server.get(token)[ANALYTICS] = "withdrawn";
  await fake.advance(LIMITS.refreshMs + 1);
  tracker.trackPageView();
  await fake.settle();
  assert.equal(tracker.trackPageView().status, "blocked");
  assert.equal(tracker.state().collecting, false);
});

test("a withdrawal during a pending grant wins and is sent for the late token", async () => {
  const { fake, tracker } = setup();
  const pending = fake.hold("consent");
  const granting = tracker.grant({ [ANALYTICS]: "granted" });
  await fake.settle();
  const withdrawing = tracker.withdraw();
  assert.equal(tracker.trackPageView().status, "blocked");
  pending.release();
  assert.equal((await granting).status, "superseded");
  const withdrawn = await withdrawing;
  assert.equal(withdrawn.confirmed, true);
  const [, ...later] = bodies(fake, "consent");
  assert.ok(later.length >= 1);
  const token = later[0].subject_token;
  assert.match(token, /^sbj_/);
  assert.ok(later.every((body) => body.subject_token === token));
  assert.ok(later.every((body) => Object.values(body.choices).every((state) => state === "withdrawn")));
  assert.equal(fake.server.get(token)[ANALYTICS], "withdrawn");
  assert.equal(fake.store.has(STORAGE_KEY), false);
  assert.equal(tracker.trackPageView().status, "blocked");
  assert.equal(fake.requests("events").length, 0);
});

test("an erasure during a pending grant erases the late subject", async () => {
  const { fake, tracker } = setup();
  const pending = fake.hold("consent");
  const granting = tracker.grant({ [ANALYTICS]: "granted" });
  await fake.settle();
  const erasing = tracker.erase();
  pending.release();
  await granting;
  assert.deepEqual(await erasing, { status: "erased", confirmed: true });
  assert.equal(fake.server.size, 0);
  assert.equal(fake.store.has(STORAGE_KEY), false);
  assert.equal(tracker.trackPageView().status, "blocked");
});

test("a stale state response cannot re-enable collection after withdrawal", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const held = fake.hold("consent-state");
  const refreshing = tracker.refresh();
  await fake.settle();
  await tracker.withdraw([ANALYTICS]);
  held.release(() => fake.json(200, { status: "active", states: { [ANALYTICS]: "granted" } }));
  assert.equal(await refreshing, false);
  assert.equal(tracker.trackPageView().status, "blocked");
  assert.equal(tracker.state().collecting, false);
});

test("withdrawal discards queued and retrying events and reports unconfirmed delivery", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  fake.script("events", () => fake.json(503, { error: "temporarily_unavailable" }, { "Retry-After": "2" }));
  tracker.trackPageView();
  tracker.trackPageView();
  await fake.settle();
  assert.equal(tracker.state().queued, 2);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    fake.script("consent", () => {
      throw new TypeError("offline");
    });
  }
  const withdrawn = tracker.withdraw();
  assert.equal(tracker.state().queued, 0);
  await fake.advance(10_000);
  assert.deepEqual(await withdrawn, { status: "withdrawn", confirmed: false });
  assert.equal(tracker.stats().unconfirmed_withdrawals, 1);
  assert.equal(fake.requests("events").length, 1);
  assert.equal(tracker.trackPageView().status, "blocked");
});

test("retries keep the exact envelope and honor Retry-After, attempts and TTL", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  fake.script("events", () => fake.json(503, { error: "x" }, { "Retry-After": "2" }));
  tracker.trackPageView();
  await fake.advance(1_999);
  assert.equal(fake.requests("events").length, 1);
  await fake.advance(2);
  const [first, second] = fake.requests("events");
  assert.equal(second.body, first.body);
  assert.equal(second.credentials, "omit");
  assert.equal(second.headers["Content-Type"], "text/plain;charset=UTF-8");
  assert.equal(tracker.stats().acknowledged, 1);
  fake.script("events", () => fake.json(429, { error: "rate_limited" }, { "Retry-After": "120" }));
  tracker.trackPageView();
  await fake.advance(1_000);
  assert.equal(tracker.stats().failed, 1);
  assert.equal(fake.requests("events").length, 3);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    fake.script("events", () => {
      throw new TypeError("offline");
    });
  }
  tracker.trackPageView();
  await fake.advance(799);
  assert.equal(fake.requests("events").length, 4);
  await fake.advance(10_000);
  const offline = fake.requests("events").slice(3);
  assert.equal(offline.length, 3);
  assert.equal(new Set(offline.map((item) => item.body)).size, 1);
  assert.equal(tracker.stats().failed, 2);
  fake.script("events", () => fake.json(400, { error: "validation_failed" }));
  tracker.trackPageView();
  await fake.advance(10_000);
  assert.equal(fake.requests("events").length, 7);
  assert.equal(tracker.stats().rejected, 1);
});

test("the queue keeps at most 20 events and drops the oldest", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const held = fake.hold("events");
  const ids = [];
  for (let index = 0; index < 25; index += 1) ids.push(tracker.trackPageView().event_id);
  await fake.settle();
  assert.equal(tracker.stats().dropped_overflow, 5);
  held.release();
  await fake.advance(5_000);
  const sent = bodies(fake).map((body) => body.event_id);
  assert.equal(sent.length, 20);
  assert.deepEqual(sent.slice(1), ids.slice(6));
  assert.equal(new Set(sent).size, 20);
});

test("events older than the TTL are discarded instead of sent", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const held = fake.hold("events");
  tracker.trackPageView();
  tracker.trackPageView();
  await fake.advance(LIMITS.eventTtlMs + 1_000);
  held.release(() => fake.json(503, {}, { "Retry-After": "1" }));
  await fake.advance(5_000);
  assert.equal(fake.requests("events").length, 1);
  assert.equal(tracker.stats().failed, 1);
  assert.equal(tracker.stats().dropped_ttl, 1);
  assert.equal(tracker.state().queued, 0);
});

test("ts_link becomes the envelope link reference and never stays in the URL", async () => {
  const href = `https://shop.example.test/offer?utm_source=site&ts_link=${LINK}&email=a@b.co#x`;
  const { fake, tracker } = setup({ href, referrer: "https://ref.example.test/path?q=1" });
  await tracker.grant({ [ANALYTICS]: "granted" });
  tracker.trackPageView();
  await fake.settle();
  const [envelope] = bodies(fake);
  assert.equal(envelope.link_id, LINK);
  assert.deepEqual(envelope.payload, {
    url: "https://shop.example.test/offer?utm_source=site",
    referrer_origin: "https://ref.example.test",
  });
  assert.equal(envelope.schema_version, 1);
  assert.equal("internal" in envelope, false);
  assert.match(envelope.event_id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  const { fake: other, tracker: plain } = setup({ href: "https://shop.example.test/?ts_link=not-a-uuid" });
  await plain.grant({ [ANALYTICS]: "granted" });
  plain.trackPageView();
  await other.settle();
  assert.equal("link_id" in bodies(other)[0], false);
});

test("oversized envelopes are rejected locally", async () => {
  // Four-byte characters keep each URL within 2048 code points but the body above 16 KiB.
  const wide = String.fromCodePoint(0x1f600).repeat(2020);
  const href = `https://shop.example.test/${wide}`;
  const { fake, tracker } = setup({ href });
  await tracker.grant({ [ANALYTICS]: "granted" });
  const link = { href: `https://shop.example.test/${wide}` };
  assert.deepEqual(tracker.trackLinkClick(link), { status: "rejected", reason: "too_large" });
  assert.equal(tracker.stats().dropped_size, 1);
  assert.equal(tracker.trackLinkClick({ href: "javascript:alert(1)" }).reason, "url_not_allowed");
  await fake.settle();
  assert.equal(fake.requests("events").length, 0);
});

test("blocked or full session storage falls back to memory only", async () => {
  for (const storage of ["blocked", "full"]) {
    const { fake, tracker } = setup({ storage });
    const result = await tracker.grant({ [ANALYTICS]: "granted" });
    assert.equal(result.status, "granted");
    assert.equal(result.continuity, "memory");
    assert.equal(tracker.trackPageView().status, "queued");
    assert.equal(fake.store.size, 0);
  }
});

test("a back/forward cache restore needs a fresh state read before sending", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const token = JSON.parse(fake.store.get(STORAGE_KEY)).token;
  fake.server.get(token)[ANALYTICS] = "withdrawn";
  fake.dispatch("window", "pageshow", { persisted: true });
  await fake.settle();
  assert.equal(fake.requests("consent-state").length, 1);
  assert.equal(tracker.trackPageView().status, "blocked");
  assert.equal(fake.requests("events").length, 0);
});

test("erase clears local state and sends the erasure once", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  tracker.trackPageView();
  const result = await tracker.erase();
  assert.deepEqual(result, { status: "erased", confirmed: true });
  assert.equal(fake.store.has(STORAGE_KEY), false);
  assert.equal(fake.requests("erasure").length, 1);
  assert.equal(tracker.trackPageView().status, "blocked");
  const again = await tracker.grant({ [ANALYTICS]: "granted" });
  assert.equal(again.status, "granted");
  assert.notEqual(JSON.parse(fake.store.get(STORAGE_KEY)).token, undefined);
});
