const TRANSIENT_DOCUMENT_PATTERN = /detached|context|navigation|execution context was destroyed|cannot find context with specified id|node with given id does not belong to the document|cannot adopt node/i;

export function isTransientDocumentError(error) {
  return TRANSIENT_DOCUMENT_PATTERN.test(String(error instanceof Error ? error.message : error));
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

export function uniqueVisibleEnabledControlIndex(items) {
  const matches = items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => item?.visible === true && item?.enabled === true);
  return matches.length === 1 ? matches[0].index : -1;
}
