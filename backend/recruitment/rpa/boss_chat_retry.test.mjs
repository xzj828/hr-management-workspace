import test from "node:test";
import assert from "node:assert/strict";

import {
  conversationEmptyScopeStableMs,
  isTransientConversationOpenError,
  uniqueVisibleIdentityMatchIndex,
  uniqueVisibleLeafMatchIndex,
} from "./boss_chat_retry.mjs";

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

test("chooses the visible conversation when a hidden SPA copy has the same identity", () => {
  const index = uniqueVisibleIdentityMatchIndex([
    { externalId: "93469926-0", jobTitle: "前置部署工程师", visible: false },
    { externalId: "93469926-0", jobTitle: "前置部署工程师", visible: true },
  ], "93469926-0", "前置部署工程师");

  assert.equal(index, 1);
});

test("rejects multiple visible conversations with the same identity", () => {
  const index = uniqueVisibleIdentityMatchIndex([
    { externalId: "93469926-0", jobTitle: "前置部署工程师", visible: true },
    { externalId: "93469926-0", jobTitle: "前置部署工程师", visible: true },
  ], "93469926-0", "前置部署工程师");

  assert.equal(index, -1);
});

test("waits longer before accepting an empty All scope than an empty unread scope", () => {
  assert.equal(conversationEmptyScopeStableMs(false), 5000);
  assert.equal(conversationEmptyScopeStableMs(true), 1500);
});

test("only treats frozen-scope conversation lookup races as retryable opens", () => {
  assert.equal(isTransientConversationOpenError(new Error("所选职位范围内无法唯一定位批准的 BOSS 会话")), true);
  assert.equal(isTransientConversationOpenError(new Error("点击前无法唯一定位批准的 BOSS 会话")), true);
  assert.equal(isTransientConversationOpenError(new Error("打开后的 BOSS 会话身份与批准目标不一致")), false);
});
