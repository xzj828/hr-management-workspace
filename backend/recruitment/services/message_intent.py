import re
from enum import StrEnum


class MessageIntent(StrEnum):
    IGNORE = "ignore"
    RESUME_RECEIVED = "resume_received"
    REJECTED = "rejected"
    OBSERVING = "observing"
    REQUEST_RESUME = "request_resume"


REJECTION_PATTERNS = [
    r"不考虑", r"没兴趣", r"不感兴趣", r"不合适", r"暂时不找", r"已经入职", r"不想聊",
]
OBSERVING_PATTERNS = [
    r"(?:想|希望|需要|先|再).{0,8}了解.{0,8}(?:公司|岗位|职位)",
    r"了解一下.{0,8}(?:公司|岗位|职位)",
    r"(?:先|再).{0,5}(?:考虑|看看)",
    r"还在观望",
]


def _matches(patterns, text):
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def classify_candidate_message(content, *, has_resume_attachment=False):
    text = " ".join(str(content or "").split()).strip()
    if has_resume_attachment:
        return MessageIntent.RESUME_RECEIVED
    if not text:
        return MessageIntent.IGNORE
    if _matches(REJECTION_PATTERNS, text):
        return MessageIntent.REJECTED
    if _matches(OBSERVING_PATTERNS, text):
        return MessageIntent.OBSERVING
    return MessageIntent.REQUEST_RESUME
