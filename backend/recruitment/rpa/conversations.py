import re
from datetime import datetime


def parse_conversation_list(output):
    rows = []
    for line in str(output or "").splitlines():
        match = re.match(r"^\s*(\d+)\.\s*([^｜|]+)(?:[｜|].*)?$", line)
        if not match:
            continue
        preview_match = re.search(r"(?:^|[｜|])消息[:：]([^｜|]+)", line)
        rows.append({
            "index": int(match.group(1)),
            "name": " ".join(match.group(2).split()).strip(),
            "unread": "未读" in line,
            **({"preview": " ".join(preview_match.group(1).split()).strip()} if preview_match else {}),
        })
    return rows


ROLE_DIRECTIONS = {"candidate": "candidate", "you": "hr", "system": "system"}
MESSAGE_LINE = re.compile(r"^\[(candidate|you|system)\]\s*(.*)$")
ABSOLUTE_TIME = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})(?:\s+|$)(.*)$")


def parse_chat_messages(output):
    messages = []
    in_messages = False
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip()
        if line == "完整聊天消息：":
            in_messages = True
            continue
        if not in_messages or not line:
            continue
        matched = MESSAGE_LINE.match(line)
        if not matched:
            continue
        role, remainder = matched.groups()
        time_match = ABSOLUTE_TIME.match(remainder)
        sent_at = ""
        content = remainder
        if time_match:
            raw_time, content = time_match.groups()
            sent_at = datetime.strptime(raw_time, "%Y-%m-%d %H:%M").isoformat()
        messages.append({
            "external_id": "",
            "direction": ROLE_DIRECTIONS[role],
            "content": content.strip(),
            "sent_at": sent_at,
        })
    return messages
