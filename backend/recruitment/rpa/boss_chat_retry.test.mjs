import test from "node:test";
import assert from "node:assert/strict";

import {
  uniqueVisibleEnabledControlIndex,
  uniqueVisibleLeafMatchIndex,
} from "./boss_chat_retry.mjs";

test("chooses the visible leaf when nested spans repeat the same filter label", () => {
  assert.equal(uniqueVisibleLeafMatchIndex([
    { text: "全部", visible: true, hasMatchingDescendant: true },
    { text: "全部", visible: true, hasMatchingDescendant: false },
    { text: "未读", visible: true, hasMatchingDescendant: false },
  ], "全部"), 1);
});

test("ignores hidden duplicate filter labels", () => {
  assert.equal(uniqueVisibleLeafMatchIndex([
    { text: "未读", visible: false, hasMatchingDescendant: false },
    { text: "未读", visible: true, hasMatchingDescendant: false },
  ], "未读"), 1);
});

test("rejects multiple visible leaf matches", () => {
  assert.equal(uniqueVisibleLeafMatchIndex([
    { text: "全部", visible: true, hasMatchingDescendant: false },
    { text: "全部", visible: true, hasMatchingDescendant: false },
  ], "全部"), -1);
});

test("chooses one visible enabled send control and rejects ambiguous controls", () => {
  assert.equal(uniqueVisibleEnabledControlIndex([
    { visible: false, enabled: true },
    { visible: true, enabled: true },
    { visible: true, enabled: false },
  ]), 1);
  assert.equal(uniqueVisibleEnabledControlIndex([
    { visible: true, enabled: true },
    { visible: true, enabled: true },
  ]), -1);
  assert.equal(uniqueVisibleEnabledControlIndex([
    { visible: true, enabled: false },
  ]), -1);
});
