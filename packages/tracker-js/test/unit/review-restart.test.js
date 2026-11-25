// Independent review of 8b03b1c (R0607-16): a retry scheduled before restart() must not send the
// old subject token afterwards (design section 8, JV23). Review regression; it fails on the
// reviewed implementation. Synthetic values only.
import assert from "node:assert/strict";
import { test } from "node:test";

import { createTracker } from "../../src/tracker.js";
import { COLLECTOR, PUBLIC_KEY, fakeEnvironment } from "../support/fake-environment.js";

const STORAGE_KEY = `ts:v1:${PUBLIC_KEY}`;

async function afterRestart(route, start) {
  const fake = fakeEnvironment();
  const tracker = createTracker({ collector: COLLECTOR, publicKey: PUBLIC_KEY }, fake.environment);
  await tracker.grant({ "analytics.first_party": "granted", identity_link: "granted" });
  const oldToken = JSON.parse(fake.store.get(STORAGE_KEY)).token;
  fake.script(route, () => fake.json(503, { error: "temporarily_unavailable" }));
  const pending = start(tracker);
  await fake.settle();
  const before = fake.log.requests.length;
  tracker.restart();
  await fake.advance(60_000);
  await pending;
  return fake.log.requests.slice(before).filter((item) => item.body.includes(oldToken));
}

test("a withdrawal retried after restart() never sends the old token", async () => {
  const leaked = await afterRestart("consent", (tracker) => tracker.withdraw(["identity_link"]));
  assert.deepEqual(leaked.map((item) => item.url.split("/").pop()), []);
});

test("an erasure retried after restart() never sends the old token", async () => {
  const leaked = await afterRestart("erasure", (tracker) => tracker.erase());
  assert.deepEqual(leaked.map((item) => item.url.split("/").pop()), []);
});
