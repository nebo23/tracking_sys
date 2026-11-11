// Regressions for the independent review of tracker 0.5.2 (2026-11-11, R005-19 to R005-22):
// queued consent work that a newer host decision made obsolete, state reads that overlap a
// consent write, and Global Privacy Control reconciliation of known server grants. Every case
// asserts the requests that leave the tracker, the collector's resulting consent state and
// the tracker's own permission state. The clock, timers and collector are deterministic and
// synthetic.
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { test } from "node:test";

import { LIMITS, createTracker } from "../../src/tracker.js";
import { COLLECTOR, PUBLIC_KEY, fakeEnvironment } from "../support/fake-environment.js";

const ANALYTICS = "analytics.first_party";
const ATTRIBUTION = "attribution";
const SALE = "sale_or_share";
const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;
const HOUR = 60 * 60 * 1000;

function setup(options = {}) {
  const fake = fakeEnvironment(options);
  const tracker = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  return { fake, tracker };
}

const events = (fake) => fake.requests("events").map((item) => JSON.parse(item.body));
const tokenOf = (fake) => JSON.parse(fake.store.get(STORAGE_KEY)).token;
const routes = (requests) => requests.map((item) => item.url.split("/").pop());
const unavailable = (fake) => () => fake.json(503, { error: "temporarily_unavailable" });
const withdrawals = (fake) =>
  fake
    .requests("consent")
    .map((item) => JSON.parse(item.body))
    .filter((body) => Object.values(body.choices).every((state) => state === "withdrawn"));

// A known subject whose analytics grant was withdrawn and confirmed; its token stays in memory.
async function withdrawnSubject() {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const token = tokenOf(fake);
  assert.equal((await tracker.withdraw()).confirmed, true);
  assert.equal(fake.server.get(token)[ANALYTICS], "withdrawn");
  return { fake, tracker, token };
}

// Start a state read as the page would and wait until its answer has been handled.
async function stateRead(fake, tracker, trigger) {
  if (trigger === "restored page") fake.dispatch("window", "pageshow", { persisted: true });
  else tracker.refresh();
  await fake.settle();
}

// The collector grants a purpose without this tracker (another tab of the same subject).
function grantElsewhere(fake, token, purpose) {
  fake.server.get(token)[purpose] = "granted";
  fake.expiries.get(token)[purpose] = fake.now() + HOUR;
}

test("R005-19: a queued resume sends no subject token after a newer host denial", async () => {
  const { fake, tracker, token } = await withdrawnSubject();
  // A host-confirmed resume is on the wire and a second one waits behind it.
  const first = fake.hold("consent-state");
  const resuming = tracker.resume({ [ANALYTICS]: "granted" });
  await fake.settle();
  assert.deepEqual(JSON.parse(first.request.body), { subject_token: token });
  const queued = tracker.resume({ [ANALYTICS]: "granted" });
  await fake.settle();
  // In a later turn the host supplies a newer decision that denies analytics.
  assert.deepEqual(await tracker.resume({ [ANALYTICS]: "denied" }), { status: "blocked" });
  const requests = fake.log.requests.length;
  const storage = fake.log.storage.length;
  first.release();
  const outcomes = [await resuming, await queued];
  await fake.advance(LIMITS.refreshMs * 3);
  assert.deepEqual(routes(fake.log.requests.slice(requests)), [], "no request after the denial");
  assert.deepEqual(fake.log.storage.slice(storage), [], "no storage access after the denial");
  assert.deepEqual(outcomes, [{ status: "superseded" }, { status: "superseded" }]);
  assert.equal(tracker.trackPageView().status, "blocked");
  assert.equal(fake.pendingTimers(), 0);
  // A later valid resume reads the state exactly once and resumes the same subject.
  grantElsewhere(fake, token, ANALYTICS);
  const resumed = await tracker.resume({ [ANALYTICS]: "granted" });
  assert.equal(resumed.status, "resumed");
  assert.deepEqual(resumed.purposes, [ANALYTICS]);
  const later = fake.log.requests.slice(requests);
  assert.deepEqual(routes(later), ["consent-state"]);
  assert.deepEqual(JSON.parse(later[0].body), { subject_token: token });
  const fresh = tracker.trackPageView();
  assert.equal(fresh.status, "queued");
  await fake.settle();
  assert.deepEqual(
    events(fake).map((body) => [body.event_id, body.subject_token]),
    [[fresh.event_id, token]],
  );
  // An explicit erasure still reaches the subject.
  assert.deepEqual(await tracker.erase(), { status: "erased", confirmed: true });
  assert.deepEqual(JSON.parse(fake.requests("erasure")[0].body), { subject_token: token });
  assert.equal(fake.server.has(token), false);
});

test("R005-19: a queued resume behind a withdrawal or an erasure sends only that request", async () => {
  for (const action of ["withdraw", "erase"]) {
    const { fake, tracker } = setup();
    await tracker.grant({ [ANALYTICS]: "granted" });
    const token = tokenOf(fake);
    const first = fake.hold("consent-state");
    const resuming = tracker.resume({ [ANALYTICS]: "granted" });
    await fake.settle();
    const queued = tracker.resume({ [ANALYTICS]: "granted" });
    await fake.settle();
    const acting = tracker[action]();
    const before = fake.log.requests.length;
    first.release();
    const outcomes = [(await resuming).status, (await queued).status];
    assert.equal((await acting).confirmed, true, action);
    await fake.advance(LIMITS.refreshMs * 3);
    const later = fake.log.requests.slice(before);
    assert.deepEqual(routes(later), [action === "erase" ? "erasure" : "consent"], action);
    assert.equal(JSON.parse(later[0].body).subject_token, token, action);
    assert.deepEqual(outcomes, ["superseded", "superseded"], action);
    assert.equal(tracker.trackPageView().status, "blocked", action);
  }
});

test("R005-19: a queued resume the host still stands by reads the state as before", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted" });
  const first = fake.hold("consent-state");
  const resuming = tracker.resume({ [ANALYTICS]: "granted" });
  await fake.settle();
  const queued = tracker.resume({ [ANALYTICS]: "granted" });
  first.release();
  await resuming;
  assert.equal((await queued).status, "resumed");
  assert.equal(fake.requests("consent-state").length, 2);
  assert.equal(tracker.trackPageView().status, "queued");
});

test("R005-20: a state read answered before a pending grant commits never hides the grant", async () => {
  for (const trigger of ["refresh", "restored page"]) {
    const { fake, tracker, token } = await withdrawnSubject();
    // The collector receives the explicit grant but has not applied it yet.
    const held = fake.hold("consent");
    const granting = tracker.grant({ [ANALYTICS]: "granted" });
    await fake.settle();
    assert.deepEqual(JSON.parse(held.request.body).choices, { [ANALYTICS]: "granted" });
    // A state read starts later and truthfully reports the older withdrawn state.
    await stateRead(fake, tracker, trigger);
    assert.equal(fake.requests("consent-state").length, 1, trigger);
    assert.equal(fake.server.get(token)[ANALYTICS], "withdrawn", trigger);
    assert.equal(tracker.trackPageView().status, "blocked", trigger);
    // The grant now commits and its successful answer is delivered.
    held.release();
    const result = await granting;
    assert.equal(result.status, "granted", trigger);
    assert.deepEqual(result.purposes, [ANALYTICS], trigger);
    assert.equal(fake.server.get(token)[ANALYTICS], "granted", trigger);
    assert.deepEqual(tracker.state().purposes, [ANALYTICS], trigger);
    assert.equal(tracker.state().collecting, true, trigger);
    assert.equal(fake.pendingTimers(), 1, "the next state refresh is scheduled");
    const fresh = tracker.trackPageView();
    assert.equal(fresh.status, "queued", trigger);
    await fake.settle();
    assert.deepEqual(
      events(fake).map((body) => [body.event_id, body.subject_token]),
      [[fresh.event_id, token]],
      trigger,
    );
    assert.equal(fake.requests("consent-state").length, 1, "the grant's own answer is adopted");
    // Collection keeps running across the following refresh intervals.
    await fake.advance(LIMITS.refreshMs * 2);
    assert.equal(tracker.state().collecting, true, trigger);
    assert.equal(tracker.trackPageView().status, "queued", trigger);
  }
});

test("R005-20: a state read processed after the grant committed leaves the grant in place", async () => {
  for (const trigger of ["refresh", "restored page"]) {
    const { fake, tracker, token } = await withdrawnSubject();
    const held = fake.hold("consent");
    const granting = tracker.grant({ [ANALYTICS]: "granted" });
    await fake.settle();
    // The collector commits the grant; its answer is still on the way when a state read,
    // processed afterwards, is answered first.
    const answer = fake.respond(held.request);
    assert.equal(fake.server.get(token)[ANALYTICS], "granted", trigger);
    await stateRead(fake, tracker, trigger);
    assert.equal(fake.requests("consent-state").length, 1, trigger);
    held.release(() => answer);
    const result = await granting;
    assert.equal(result.status, "granted", trigger);
    assert.deepEqual(result.purposes, [ANALYTICS], trigger);
    assert.equal(fake.server.get(token)[ANALYTICS], "granted", trigger);
    assert.deepEqual(tracker.state().purposes, [ANALYTICS], trigger);
    assert.equal(tracker.state().collecting, true, trigger);
    const fresh = tracker.trackPageView();
    assert.equal(fresh.status, "queued", trigger);
    await fake.settle();
    assert.deepEqual(
      events(fake).map((body) => [body.event_id, body.subject_token]),
      [[fresh.event_id, token]],
      trigger,
    );
  }
});

test("R005-20: a newer local withdrawal still wins over the late grant in either order", async () => {
  for (const order of ["read first", "grant first"]) {
    const { fake, tracker, token } = await withdrawnSubject();
    const held = fake.hold("consent");
    const granting = tracker.grant({ [ANALYTICS]: "granted" });
    await fake.settle();
    const answer = order === "grant first" ? fake.respond(held.request) : null;
    await stateRead(fake, tracker, "refresh");
    // The visitor withdraws again while the grant's answer is still outstanding.
    const withdrawing = tracker.withdraw([ANALYTICS]);
    assert.equal(tracker.trackPageView().status, "blocked", order);
    const reads = fake.requests("consent-state").length;
    held.release(answer ? () => answer : undefined);
    assert.equal((await granting).status, "superseded", order);
    assert.equal((await withdrawing).confirmed, true, order);
    await fake.advance(LIMITS.refreshMs * 3);
    assert.equal(fake.server.get(token)[ANALYTICS], "withdrawn", order);
    assert.deepEqual(tracker.state().purposes, [], order);
    assert.equal(tracker.trackPageView().status, "blocked", order);
    assert.equal(fake.requests("events").length, 0, order);
    assert.equal(fake.requests("consent-state").length, reads, "no state read after the withdrawal");
    assert.equal(fake.pendingTimers(), 0, order);
  }
});

test("R005-20: a grant whose answer is lost is learned from one repeated state read", async () => {
  const { fake, tracker, token } = await withdrawnSubject();
  const held = fake.hold("consent");
  const granting = tracker.grant({ [ANALYTICS]: "granted" });
  await fake.settle();
  assert.equal(await tracker.refresh(), false, "a read overlapping the write is not adopted");
  assert.equal(await tracker.refresh(), false);
  assert.equal(fake.requests("consent-state").length, 1, "one read at most while the write is pending");
  // The collector commits the grant, but its answer never reaches the browser.
  fake.respond(held.request);
  held.reject(new TypeError("Synthetic network failure"));
  assert.equal((await granting).status, "unavailable");
  await fake.settle();
  assert.equal(fake.requests("consent-state").length, 2, "the discarded read is repeated once");
  assert.equal(fake.server.get(token)[ANALYTICS], "granted");
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  assert.equal(tracker.trackPageView().status, "queued");
  await fake.settle();
  assert.equal(events(fake).at(-1).subject_token, token);
  await fake.advance(LIMITS.refreshMs * 2);
  assert.equal(tracker.state().collecting, true);
});

test("R005-20: a state read dropped by a local change is repeated so collection continues", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [ATTRIBUTION]: "granted" });
  const token = tokenOf(fake);
  // The scheduled refresh is on the wire when the visitor withdraws attribution only.
  const held = fake.hold("consent-state");
  await fake.advance(LIMITS.refreshMs - LIMITS.refreshLeadMs);
  assert.ok(held.request, "the scheduled refresh started");
  assert.equal((await tracker.withdraw([ATTRIBUTION])).confirmed, true);
  held.release();
  await fake.settle();
  assert.equal(fake.requests("consent-state").length, 2, "the dropped read is repeated once");
  assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted", [ATTRIBUTION]: "withdrawn" });
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  await fake.advance(LIMITS.refreshLeadMs + 2_000);
  assert.equal(tracker.state().collecting, true);
  assert.equal(tracker.trackPageView().status, "queued");
  await fake.settle();
  assert.equal(fake.requests("events").length, 1);
});

test("R005-21: a GPC-only choice withdraws the known subject's existing server grant", async () => {
  for (const path of ["grant", "resume"]) {
    const { fake, tracker } = setup();
    assert.deepEqual((await tracker.grant({ [SALE]: "granted" })).purposes, [SALE]);
    const token = tokenOf(fake);
    assert.deepEqual(fake.server.get(token), { [SALE]: "granted" });
    fake.navigator.globalPrivacyControl = true;
    const before = fake.log.requests.length;
    // The host supplies the same choice again; GPC filters every requested purpose.
    const result = await tracker[path]({ [SALE]: "granted" });
    if (path === "grant") assert.deepEqual(result, { status: "nothing_sent", refused: [SALE] });
    else assert.deepEqual(result, { status: "blocked" });
    assert.deepEqual(tracker.state().purposes, [], path);
    assert.equal(tracker.trackPageView().status, "blocked", path);
    await fake.advance(3 * 60_000);
    const later = fake.log.requests.slice(before);
    assert.deepEqual(routes(later), ["consent"], path);
    assert.deepEqual(JSON.parse(later[0].body), { subject_token: token, choices: { [SALE]: "withdrawn" } });
    assert.deepEqual(fake.server.get(token), { [SALE]: "withdrawn" }, path);
    assert.deepEqual(tracker.state().purposes, [], path);
    assert.equal(tracker.trackPageView().status, "blocked", path);
    assert.equal(fake.requests("events").length, 0, path);
    assert.equal(tracker.stats().unconfirmed_withdrawals, 0, path);
    // Supplying the choice once more finds nothing left to withdraw.
    await tracker[path]({ [SALE]: "granted" });
    await fake.advance(60_000);
    assert.equal(fake.log.requests.length, before + 1, path);
  }
});

test("R005-21: the GPC-only withdrawal stays bounded while the collector keeps failing", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [SALE]: "granted" });
  const token = tokenOf(fake);
  fake.navigator.globalPrivacyControl = true;
  for (let attempt = 0; attempt < 30; attempt += 1) fake.script("consent", unavailable(fake));
  for (let round = 0; round < 6; round += 1) {
    const result = await tracker.grant({ [SALE]: "granted" });
    assert.equal(result.status, "nothing_sent");
    await fake.advance(10_000);
  }
  const sent = withdrawals(fake);
  assert.equal(sent.length, LIMITS.gpcRounds * LIMITS.maxAttempts);
  for (const body of sent) {
    assert.deepEqual(body, { subject_token: token, choices: { [SALE]: "withdrawn" } });
  }
  assert.equal(fake.server.get(token)[SALE], "granted");
  assert.deepEqual(tracker.state().purposes, [], "the empty local permission set still blocks");
  assert.equal(tracker.trackPageView().status, "blocked");
  assert.equal(fake.requests("consent-state").length, 0);
  assert.equal(fake.requests("events").length, 0);
});

test("R005-21: a GPC-only choice from a new visitor creates no subject, identifier or request", async () => {
  const fake = fakeEnvironment({ gpc: true });
  let randomValues = 0;
  fake.environment.crypto = {
    getRandomValues(array) {
      randomValues += 1;
      return webcrypto.getRandomValues(array);
    },
  };
  const tracker = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  assert.deepEqual(await tracker.grant({ [SALE]: "granted" }), { status: "nothing_sent", refused: [SALE] });
  assert.deepEqual(await tracker.resume({ [SALE]: "granted" }), { status: "blocked" });
  assert.equal(tracker.trackPageView().status, "blocked");
  await fake.advance(3 * 60_000);
  assert.deepEqual(fake.log.requests, [], "no consent, state or tracking request");
  assert.deepEqual(fake.log.storage, [], "no storage access");
  assert.equal(fake.log.location, 0);
  assert.equal(fake.store.size, 0);
  assert.equal(fake.server.size, 0, "no subject was created");
  assert.equal(randomValues, 0, "no identifier was generated");
  assert.equal(fake.pendingTimers(), 0);
  assert.deepEqual(tracker.state(), { purposes: [], collecting: false, continuity: "none", queued: 0 });
});

// Exhaust the bounded reconciliation rounds of the current sale/share grant during an outage.
async function exhaustRounds(fake, tracker) {
  for (let attempt = 0; attempt < LIMITS.gpcRounds * LIMITS.maxAttempts; attempt += 1) {
    fake.script("consent", unavailable(fake));
  }
  for (let round = 0; round < LIMITS.gpcRounds; round += 1) {
    assert.equal(await tracker.refresh(), true);
    await fake.advance(10_000);
  }
}

test("R005-22: a distinct new grant gets its own bounded GPC reconciliation budget", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [SALE]: "granted" });
  const token = tokenOf(fake);
  fake.navigator.globalPrivacyControl = true;
  await exhaustRounds(fake, tracker);
  const cap = LIMITS.gpcRounds * LIMITS.maxAttempts;
  assert.equal(withdrawals(fake).length, cap);
  assert.equal(fake.server.get(token)[SALE], "granted");
  // The collector recovers. Routine refreshes of the unchanged grant keep the exhausted cap.
  for (let round = 0; round < 3; round += 1) {
    assert.equal(await tracker.refresh(), true);
    await fake.advance(10_000);
  }
  assert.equal(withdrawals(fake).length, cap, "the same grant gets no further attempt");
  assert.equal(fake.server.get(token)[SALE], "granted");
  // GPC is turned off; an explicit withdrawal reaches the collector, then a new explicit grant.
  fake.navigator.globalPrivacyControl = false;
  assert.equal((await tracker.withdraw([SALE])).confirmed, true);
  assert.equal(fake.server.get(token)[SALE], "withdrawn");
  const regranted = await tracker.grant({ [SALE]: "granted" });
  assert.equal(regranted.status, "granted");
  assert.deepEqual(regranted.purposes, [ANALYTICS, SALE]);
  assert.equal(fake.server.get(token)[SALE], "granted");
  assert.equal(withdrawals(fake).length, cap + 1, "only the explicit withdrawal so far");
  // GPC returns: the distinct new grant is withdrawn with its own budget.
  fake.navigator.globalPrivacyControl = true;
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  assert.equal(await tracker.refresh(), true);
  await fake.advance(2 * 60_000);
  const sent = withdrawals(fake);
  assert.equal(sent.length, cap + 2, "one reconciliation request for the new grant");
  assert.deepEqual(sent.at(-1), { subject_token: token, choices: { [SALE]: "withdrawn" } });
  assert.deepEqual(fake.server.get(token), { [ANALYTICS]: "granted", [SALE]: "withdrawn" });
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  assert.equal(tracker.trackPageView().status, "queued");
});

test("R005-22: the new grant's own budget is bounded and a routine refresh never resets it", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [SALE]: "granted" });
  const token = tokenOf(fake);
  fake.navigator.globalPrivacyControl = true;
  await exhaustRounds(fake, tracker);
  const cap = LIMITS.gpcRounds * LIMITS.maxAttempts;
  assert.equal(withdrawals(fake).length, cap);
  // The subject grants sale/share again elsewhere: the collector now holds a distinct grant.
  grantElsewhere(fake, token, SALE);
  for (let attempt = 0; attempt < 30; attempt += 1) fake.script("consent", unavailable(fake));
  for (let round = 0; round < 6; round += 1) {
    assert.equal(await tracker.refresh(), true);
    await fake.advance(10_000);
  }
  assert.equal(withdrawals(fake).length, cap * 2, "the new grant gets exactly one more budget");
  assert.equal(fake.server.get(token)[SALE], "granted");
  assert.deepEqual(tracker.state().purposes, [ANALYTICS]);
  // The collector recovers, but refreshing the unchanged grant does not reopen its budget.
  fake.script("consent", () => {
    throw new Error("No further withdrawal may be attempted for an exhausted grant.");
  });
  for (let round = 0; round < 3; round += 1) {
    assert.equal(await tracker.refresh(), true);
    await fake.advance(60_000);
  }
  assert.equal(withdrawals(fake).length, cap * 2);
  assert.equal(fake.server.get(token)[SALE], "granted");
});
