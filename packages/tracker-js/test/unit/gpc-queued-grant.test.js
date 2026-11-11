// Regressions for the final review of PR 4 (2026-11-11, R005-23): a consent grant that waits
// in the tracker's queue must apply the Global Privacy Control restrictions in force when its
// request is issued, not the ones in force when grant() was called. Every case asserts the raw
// bodies that leave the tracker after the signal became active, the tracker's effective
// permissions and the collector's consent state. The clock, timers and collector are
// deterministic and synthetic.
import assert from "node:assert/strict";
import { test } from "node:test";

import { GPC_PURPOSES, createTracker } from "../../src/tracker.js";
import { COLLECTOR, PUBLIC_KEY, fakeEnvironment } from "../support/fake-environment.js";

const ANALYTICS = "analytics.first_party";
const ATTRIBUTION = "attribution";
const SALE = "sale_or_share";
const ADS_MEASUREMENT = "ads.measurement";
const ADS_PERSONALIZATION = "ads.personalization";
const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;

function setup(options = {}) {
  const fake = fakeEnvironment(options);
  const tracker = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  return { fake, tracker };
}

const tokenOf = (fake) => JSON.parse(fake.store.get(STORAGE_KEY)).token;
const sent = (requests) => requests.map((item) => [item.url.split("/").pop(), JSON.parse(item.body)]);
const consentBodies = (requests) =>
  sent(requests)
    .filter(([route]) => route === "consent")
    .map(([, body]) => body);
// Grants for a GPC-restricted purpose among the given requests: the prohibited transmissions.
const prohibitedGrants = (requests) =>
  consentBodies(requests).flatMap((body) =>
    Object.entries(body.choices).filter(
      ([purpose, state]) => state === "granted" && GPC_PURPOSES.includes(purpose),
    ),
  );

// GPC is off. An explicit analytics grant is on the wire with its answer held, and a second
// grant waits behind it in the consent queue with its request not started.
async function queuedBehindAnalytics(fake, tracker, choices) {
  const held = fake.hold("consent");
  const first = tracker.grant({ [ANALYTICS]: "granted" });
  await fake.settle();
  assert.deepEqual(JSON.parse(held.request.body), { choices: { [ANALYTICS]: "granted" } });
  const queued = tracker.grant(choices);
  await fake.settle();
  assert.equal(fake.requests("consent").length, 1, "the second grant is queued, not started");
  return { held, first, queued };
}

test("R005-23: a queued grant sends no restricted grant once GPC has become active", async () => {
  assert.deepEqual([...GPC_PURPOSES].sort(), [ADS_MEASUREMENT, ADS_PERSONALIZATION, SALE].sort());
  for (const purpose of GPC_PURPOSES) {
    const { fake, tracker } = setup();
    const { held, first, queued } = await queuedBehindAnalytics(fake, tracker, { [purpose]: "granted" });
    // The signal becomes active without any further grant, resume or withdrawal call.
    fake.navigator.globalPrivacyControl = true;
    const mark = fake.log.requests.length;
    held.release();
    assert.equal((await first).status, "granted", purpose);
    const result = await queued;
    await fake.advance(30_000);
    const later = fake.log.requests.slice(mark);
    assert.deepEqual(prohibitedGrants(later), [], `${purpose}: no restricted grant leaves the tracker`);
    assert.deepEqual(sent(later), [], `${purpose}: nothing at all is sent after activation`);
    assert.deepEqual(result, { status: "nothing_sent", refused: [purpose] }, purpose);
    const token = tokenOf(fake);
    assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted" }, purpose);
    assert.deepEqual(tracker.state().purposes, [ANALYTICS], purpose);
    assert.equal(tracker.stats().unconfirmed_withdrawals, 0, purpose);
    // Turning the signal off again does not revive the refused choice.
    fake.navigator.globalPrivacyControl = false;
    assert.deepEqual(tracker.state().purposes, [ANALYTICS], purpose);
    assert.equal(await tracker.refresh(), true, purpose);
    assert.deepEqual(tracker.state().purposes, [ANALYTICS], purpose);
    assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted" }, purpose);
  }
});

test("R005-23: a mixed queued grant keeps its permitted choices and drops the restricted ones", async () => {
  const { fake, tracker } = setup();
  const { held, first, queued } = await queuedBehindAnalytics(fake, tracker, {
    [ATTRIBUTION]: "granted",
    [SALE]: "granted",
    [ADS_MEASUREMENT]: "granted",
    [ADS_PERSONALIZATION]: "denied",
  });
  fake.navigator.globalPrivacyControl = true;
  const mark = fake.log.requests.length;
  held.release();
  await first;
  const result = await queued;
  await fake.advance(30_000);
  const token = tokenOf(fake);
  const later = fake.log.requests.slice(mark);
  assert.deepEqual(prohibitedGrants(later), []);
  assert.deepEqual(sent(later), [
    [
      "consent",
      { choices: { [ATTRIBUTION]: "granted", [ADS_PERSONALIZATION]: "denied" }, subject_token: token },
    ],
  ]);
  assert.equal(result.status, "granted");
  assert.deepEqual(result.purposes, [ANALYTICS, ATTRIBUTION]);
  assert.deepEqual(result.refused, [SALE, ADS_MEASUREMENT]);
  assert.deepEqual(fake.server.get(token), {
    [ANALYTICS]: "granted",
    [ATTRIBUTION]: "granted",
    [ADS_PERSONALIZATION]: "denied",
  });
  assert.deepEqual(tracker.state().purposes, [ANALYTICS, ATTRIBUTION]);
  assert.equal(tracker.trackPageView().status, "queued");
});

test("R005-23: a queued permitted analytics grant with a restricted grant reaches the collector alone", async () => {
  const { fake, tracker } = setup();
  // The queue is busy with an attribution-only grant, so the queued request carries analytics.
  const held = fake.hold("consent");
  const first = tracker.grant({ [ATTRIBUTION]: "granted" });
  await fake.settle();
  const queued = tracker.grant({ [ANALYTICS]: "granted", [SALE]: "granted" });
  await fake.settle();
  assert.equal(fake.requests("consent").length, 1);
  fake.navigator.globalPrivacyControl = true;
  const mark = fake.log.requests.length;
  held.release();
  await first;
  const result = await queued;
  const token = tokenOf(fake);
  const later = fake.log.requests.slice(mark);
  assert.deepEqual(prohibitedGrants(later), []);
  assert.deepEqual(sent(later), [["consent", { choices: { [ANALYTICS]: "granted" }, subject_token: token }]]);
  assert.equal(result.status, "granted");
  assert.deepEqual(result.refused, [SALE]);
  assert.deepEqual(result.purposes, [ANALYTICS, ATTRIBUTION]);
  assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
});

test("R005-23: filtering every grant creates no subject and sends no empty consent write", async () => {
  for (const choices of [
    { [SALE]: "granted" },
    { [SALE]: "granted", [ADS_PERSONALIZATION]: "granted" },
    { [ADS_MEASUREMENT]: "granted", [ANALYTICS]: "denied" },
  ]) {
    const label = JSON.stringify(choices);
    const { fake, tracker } = setup();
    // The first grant fails at the collector, so no subject exists when the queued one runs.
    const held = fake.hold("consent");
    const first = tracker.grant({ [ANALYTICS]: "granted" });
    await fake.settle();
    const queued = tracker.grant(choices);
    await fake.settle();
    fake.navigator.globalPrivacyControl = true;
    const mark = fake.log.requests.length;
    held.release(() => fake.json(503, { error: "temporarily_unavailable" }));
    assert.equal((await first).status, "rejected", label);
    const result = await queued;
    await fake.advance(3 * 60_000);
    assert.deepEqual(sent(fake.log.requests.slice(mark)), [], label);
    assert.deepEqual(
      result.refused,
      Object.keys(choices).filter((purpose) => choices[purpose] === "granted"),
      label,
    );
    const expected = Object.values(choices).includes("denied") ? "nothing_granted" : "nothing_sent";
    assert.equal(result.status, expected, label);
    assert.equal(fake.server.size, 0, "no subject was created");
    assert.equal(fake.store.size, 0, label);
    assert.deepEqual(tracker.state().purposes, [], label);
    assert.equal(tracker.trackPageView().status, "blocked", label);
    assert.equal(fake.pendingTimers(), 0, label);
  }
});

test("R005-23: a queued restricted regrant of a known server grant is withdrawn, never granted", async () => {
  const { fake, tracker } = setup();
  assert.deepEqual((await tracker.grant({ [SALE]: "granted" })).purposes, [SALE]);
  const token = tokenOf(fake);
  const held = fake.hold("consent");
  const first = tracker.grant({ [ANALYTICS]: "granted" });
  await fake.settle();
  const queued = tracker.grant({ [SALE]: "granted" });
  await fake.settle();
  assert.equal(fake.requests("consent").length, 2);
  fake.navigator.globalPrivacyControl = true;
  const mark = fake.log.requests.length;
  held.release();
  await first;
  assert.deepEqual(await queued, { status: "nothing_sent", refused: [SALE] });
  await fake.advance(30_000);
  const later = fake.log.requests.slice(mark);
  assert.deepEqual(prohibitedGrants(later), []);
  // The existing bounded reconciliation withdraws the grant the collector already held.
  assert.deepEqual(sent(later), [["consent", { subject_token: token, choices: { [SALE]: "withdrawn" } }]]);
  assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted", [SALE]: "withdrawn" });
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  assert.equal(tracker.stats().unconfirmed_withdrawals, 0);
});

test("R005-23: a queued grant still succeeds while GPC stays off", async () => {
  for (const purpose of GPC_PURPOSES) {
    const { fake, tracker } = setup();
    const { held, first, queued } = await queuedBehindAnalytics(fake, tracker, { [purpose]: "granted" });
    const mark = fake.log.requests.length;
    held.release();
    await first;
    const result = await queued;
    const token = tokenOf(fake);
    assert.deepEqual(sent(fake.log.requests.slice(mark)), [
      ["consent", { choices: { [purpose]: "granted" }, subject_token: token }],
    ]);
    assert.equal(result.status, "granted", purpose);
    assert.deepEqual(result.refused, [], purpose);
    assert.deepEqual(result.purposes.sort(), [ANALYTICS, purpose].sort(), purpose);
    assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted", [purpose]: "granted" }, purpose);
    assert.deepEqual(tracker.state().purposes, [ANALYTICS, purpose].sort(), purpose);
  }
});

test("R005-23: queued withdrawal, erasure and GPC reconciliation still reach the collector", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [SALE]: "granted", [ADS_MEASUREMENT]: "granted" });
  const token = tokenOf(fake);
  // An explicit withdrawal queued before the signal became active is still sent afterwards.
  const held = fake.hold("consent");
  const first = tracker.grant({ [ATTRIBUTION]: "granted" });
  await fake.settle();
  const withdrawing = tracker.withdraw([SALE]);
  await fake.settle();
  fake.navigator.globalPrivacyControl = true;
  const mark = fake.log.requests.length;
  held.release();
  await first;
  assert.deepEqual(await withdrawing, { status: "withdrawn", confirmed: true });
  await fake.advance(30_000);
  const later = fake.log.requests.slice(mark);
  assert.deepEqual(prohibitedGrants(later), []);
  // The explicit withdrawal, then the reconciliation of every restricted grant that the
  // collector reported in the answer it gave before that withdrawal arrived.
  assert.deepEqual(consentBodies(later), [
    { subject_token: token, choices: { [SALE]: "withdrawn" } },
    { subject_token: token, choices: { [SALE]: "withdrawn", [ADS_MEASUREMENT]: "withdrawn" } },
  ]);
  assert.deepEqual(fake.server.get(token), {
    [ANALYTICS]: "granted",
    [ATTRIBUTION]: "granted",
    [SALE]: "withdrawn",
    [ADS_MEASUREMENT]: "withdrawn",
  });
  assert.deepEqual(tracker.state().purposes, [ANALYTICS, ATTRIBUTION]);
  // A queued erasure behind a pending grant still erases the subject.
  const pending = fake.hold("consent");
  const regrant = tracker.grant({ [ATTRIBUTION]: "granted" });
  await fake.settle();
  const erasing = tracker.erase();
  pending.release();
  await regrant;
  assert.deepEqual(await erasing, { status: "erased", confirmed: true });
  assert.deepEqual(JSON.parse(fake.requests("erasure")[0].body), { subject_token: token });
  assert.equal(fake.server.has(token), false);
  assert.equal(tracker.trackPageView().status, "blocked");
});
