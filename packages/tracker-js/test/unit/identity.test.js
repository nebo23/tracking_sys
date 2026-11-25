// Specification 006 tracker additions (D-075): identityHandoff(challenge) and restart().
// Every case asserts what leaves the tracker at its transport boundary, what it stores and what
// it returns to the host page. Synthetic values only.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createTracker } from "../../src/tracker.js";
import { COLLECTOR, PUBLIC_KEY, fakeEnvironment } from "../support/fake-environment.js";

const ANALYTICS = "analytics.first_party";
const IDENTITY = "identity_link";
const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;
const CHALLENGE = "c".repeat(32);

function setup(options = {}) {
  const fake = fakeEnvironment(options);
  const tracker = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  return { fake, tracker };
}

const bodies = (fake, route) => fake.requests(route).map((item) => JSON.parse(item.body));
const allBodies = (fake) => fake.log.requests.map((item) => item.body).join("\n");

test("identityHandoff needs an effective identity_link and keeps values out of URLs and storage", async () => {
  const { fake, tracker } = setup();
  assert.deepEqual(await tracker.identityHandoff(CHALLENGE), { status: "blocked" });
  await tracker.grant({ [ANALYTICS]: "granted" });
  assert.deepEqual(await tracker.identityHandoff(CHALLENGE), { status: "blocked" });
  assert.equal(fake.requests("identity-handoff").length, 0);
  await tracker.grant({ [IDENTITY]: "granted" });
  const issued = await tracker.identityHandoff(CHALLENGE);
  assert.equal(issued.status, "issued");
  assert.match(issued.code, /^ihc_/);
  const [request] = fake.requests("identity-handoff");
  assert.ok(!request.url.includes(CHALLENGE) && !request.url.includes(issued.code));
  assert.equal(request.credentials, "omit");
  assert.equal(JSON.parse(request.body).challenge, CHALLENGE);
  const stored = [...fake.store.values()].join("\n");
  assert.ok(!stored.includes(CHALLENGE) && !stored.includes(issued.code));
  await assert.rejects(tracker.identityHandoff("short"), TypeError);
  await assert.rejects(tracker.identityHandoff("x".repeat(22) + "/"), TypeError);
});

test("a handoff answered after withdrawal or restart is never returned", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [IDENTITY]: "granted" });
  const held = fake.hold("identity-handoff");
  const pending = tracker.identityHandoff(CHALLENGE);
  await fake.settle();
  tracker.withdraw([IDENTITY]);
  held.release();
  assert.deepEqual(await pending, { status: "unavailable" });
  await tracker.grant({ [IDENTITY]: "granted" });
  const second = fake.hold("identity-handoff");
  const late = tracker.identityHandoff(CHALLENGE);
  await fake.settle();
  tracker.restart();
  second.release();
  assert.deepEqual(await late, { status: "unavailable" });
});

test("restart clears the old session at once and aborts in-flight events", async () => {
  const { fake, tracker } = setup();
  await tracker.grant({ [ANALYTICS]: "granted", [IDENTITY]: "granted" });
  const oldToken = JSON.parse(fake.store.get(STORAGE_KEY)).token;
  const held = fake.hold("events");
  tracker.trackPageView();
  await fake.settle();
  assert.equal(fake.requests("events").length, 1);
  assert.deepEqual(tracker.restart(), { status: "restarted" });
  assert.equal(held.aborted, true);
  assert.equal(fake.store.has(STORAGE_KEY), false);
  assert.deepEqual(tracker.state().purposes, []);
  assert.equal(tracker.trackPageView().status, "blocked");
  await fake.settle(); // the aborted request settles and leaves the queue
  assert.equal(tracker.state().queued, 0);
  assert.deepEqual(await tracker.identityHandoff(CHALLENGE), { status: "blocked" });
  await fake.advance(120_000);
  assert.equal(fake.requests("events").length, 1, "no retry of the old session's event");
  // The next explicit grant creates a new subject; the old token never travels again.
  const before = fake.log.requests.length;
  await tracker.grant({ [ANALYTICS]: "granted" });
  const consent = bodies(fake, "consent").at(-1);
  assert.equal(consent.subject_token, undefined);
  const newToken = JSON.parse(fake.store.get(STORAGE_KEY)).token;
  assert.notEqual(newToken, oldToken);
  const after = fake.log.requests.slice(before).map((item) => item.body).join("\n");
  assert.ok(!after.includes(oldToken));
  assert.equal(fake.server.get(oldToken)[IDENTITY], "granted", "server consent stays recorded");
});

test("queued consent work and late answers of the old session are ignored", async () => {
  const { fake, tracker } = setup();
  // A first grant whose answer arrives after restart: its new token is never adopted.
  const held = fake.hold("consent");
  const first = tracker.grant({ [ANALYTICS]: "granted" });
  await fake.settle();
  const queued = tracker.grant({ [IDENTITY]: "granted" });
  tracker.restart();
  held.release();
  assert.equal((await first).status, "superseded");
  assert.equal((await queued).status, "superseded");
  assert.equal(fake.requests("consent").length, 1, "the queued grant never starts");
  assert.equal(fake.store.has(STORAGE_KEY), false);
  assert.deepEqual(tracker.state().purposes, []);
  // A withdrawal queued behind a held request of the old session does not start either.
  await tracker.grant({ [ANALYTICS]: "granted", [IDENTITY]: "granted" });
  const token = JSON.parse(fake.store.get(STORAGE_KEY)).token;
  const slow = fake.hold("consent");
  const regrant = tracker.grant({ [ANALYTICS]: "granted" });
  await fake.settle();
  const withdrawal = tracker.withdraw([IDENTITY]);
  tracker.restart();
  slow.release();
  await regrant;
  assert.deepEqual(await withdrawal, { status: "superseded", confirmed: false });
  const sent = fake.log.requests.slice(-1)[0];
  assert.ok(JSON.parse(sent.body).choices[IDENTITY] === undefined);
  assert.ok(!allBodies(fake).split("\n").slice(-1)[0].includes("withdrawn"));
  assert.ok(token);
});
