// Parity of the browser minimizer with the Python contracts (specification 005, M2).
// Expected values in ../fixtures/parity.json come from the Python implementation; the backend
// suite (tests/test_tracker_parity.py) asserts the same file.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  Rejected,
  containsCardNumber,
  minimizePageUrl,
  neverCollectReason,
  originOnly,
  sanitizeFieldValue,
} from "../../src/minimize.js";

const fixtures = JSON.parse(
  readFileSync(new URL("../fixtures/parity.json", import.meta.url), "utf8"),
);

function outcome(callable) {
  try {
    return { value: callable() };
  } catch (error) {
    assert.ok(error instanceof Rejected, `unexpected error ${error}`);
    return { rejected: error.reason };
  }
}

test("page URLs minimize exactly like the Python contract", () => {
  assert.ok(fixtures.urls.length >= 30);
  for (const item of fixtures.urls) {
    const result = outcome(() => minimizePageUrl(item.url, new Set(item.granted)));
    if (item.rejected) {
      assert.deepEqual(result, { rejected: item.rejected }, item.url);
    } else {
      assert.equal(result.value?.url, item.expected, item.url);
      assert.deepEqual(result.value.dropped, item.dropped, item.url);
    }
  }
});

test("referrers keep only their origin", () => {
  for (const item of fixtures.referrers) {
    const result = outcome(() => originOnly(item.url));
    assert.deepEqual(result, item.rejected ? { rejected: item.rejected } : { value: item.expected });
  }
});

test("card numbers are detected across separators and scripts", () => {
  assert.ok(fixtures.cards.some((item) => item.card) && fixtures.cards.some((item) => !item.card));
  for (const item of fixtures.cards) {
    assert.equal(containsCardNumber(item.text), item.card, JSON.stringify(item.text));
  }
});

test("never-collect rules match for every field descriptor", () => {
  for (const item of fixtures.fields) {
    assert.equal(neverCollectReason(item.field), item.reason, JSON.stringify(item.field));
  }
});

test("registered field values keep only their 004 class", () => {
  for (const item of fixtures.values) {
    const kept = sanitizeFieldValue(item.field, item.value);
    assert.deepEqual(kept === undefined ? null : kept, item.expected, JSON.stringify(item));
  }
});
