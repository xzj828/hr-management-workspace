const TRANSIENT_DOCUMENT_PATTERN = /detached|context|navigation|execution context was destroyed|cannot find context with specified id|node with given id does not belong to the document|cannot adopt node/i;

export function isTransientDocumentError(error) {
  return TRANSIENT_DOCUMENT_PATTERN.test(String(error instanceof Error ? error.message : error));
}

export function isTransientConversationOpenError(error) {
  return /所选职位范围内无法唯一定位批准的 BOSS 会话|点击前无法唯一定位批准的 BOSS 会话/.test(
    String(error instanceof Error ? error.message : error),
  );
}

export function conversationEmptyScopeStableMs(unread) {
  return unread ? 1500 : 5000;
}

export function uniqueVisibleLeafMatchIndex(items, expected) {
  const label = String(expected ?? "").replace(/\s+/g, "").trim();
  const matches = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item?.visible === true
      && item?.hasMatchingDescendant !== true
      && String(item?.text ?? "").replace(/\s+/g, "").trim() === label);
  return matches.length === 1 ? matches[0].index : -1;
}

export function uniqueVisibleIdentityMatchIndex(items, expectedExternalId, expectedJobTitle) {
  const externalId = String(expectedExternalId ?? "").trim();
  const jobTitle = String(expectedJobTitle ?? "").replace(/\s+/g, " ").trim();
  const matches = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item?.visible === true
      && String(item?.externalId ?? "").trim() === externalId
      && String(item?.jobTitle ?? "").replace(/\s+/g, " ").trim() === jobTitle);
  return matches.length === 1 ? matches[0].index : -1;
}

export function uniqueVisibleEnabledControlIndex(items) {
  const matches = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item?.visible === true && item?.enabled === true);
  return matches.length === 1 ? matches[0].index : -1;
}
