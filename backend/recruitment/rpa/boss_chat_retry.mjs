const TRANSIENT_DOCUMENT_PATTERN = /detached|context|navigation|execution context was destroyed|cannot find context with specified id|node with given id does not belong to the document|cannot adopt node/i;

export function isTransientDocumentError(error) {
  return TRANSIENT_DOCUMENT_PATTERN.test(String(error instanceof Error ? error.message : error));
}
