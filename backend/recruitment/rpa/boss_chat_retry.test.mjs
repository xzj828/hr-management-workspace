import test from "node:test";
import assert from "node:assert/strict";

import { uniqueVisibleLeafMatchIndex } from "./boss_chat_retry.mjs";

test("chooses the visible leaf when nested spans repeat the same filter label", () => {
  const index = uniqueVisibleLeafMatchIndex([
    { text: "全部", visible: true, hasMatchingDescendant: true },
    { text: "全部", visible: true, hasMatchingDescendant: false },
    { text: "未读", visible: true, hasMatchingDescendant: false },
  ], "全部");

  assert.equal(index, 1);
});

test("ignores hidden duplicate filter labels", () => {
  const index = uniqueVisibleLeafMatchIndex([
    { text: "未读", visible: false, hasMatchingDescendant: false },
    { text: "未读", visible: true, hasMatchingDescendant: false },
  ], "未读");

  assert.equal(index, 1);
});

test("rejects multiple visible leaf matches", () => {
  const index = uniqueVisibleLeafMatchIndex([
    { text: "全部", visible: true, hasMatchingDescendant: false },
    { text: "全部", visible: true, hasMatchingDescendant: false },
  ], "全部");

  assert.equal(index, -1);
});
