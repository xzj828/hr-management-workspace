import re
from datetime import datetime


def parse_conversation_list(output):
    rows = []
    for line in str(output or "").splitlines():
        match = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
        if not match:
            continue
        index = int(match.group(1))
        parts = [part.strip() for part in re.split(r"[｜|]", match.group(2))]
        name = " ".join(parts[0].split()).strip()
        if not name:
            continue
        preview = ""
        external_id = ""
        fingerprint = ""
        job_title = ""
        for part in parts[1:]:
            if not part:
                continue
            if re.match(r"^(?:external[_ -]?id|候选人ID|平台ID)\s*[:：=]\s*", part, re.I):
                external_id = re.sub(
                    r"^(?:external[_ -]?id|候选人ID|平台ID)\s*[:：=]\s*", "", part, flags=re.I
                ).strip()
            elif re.match(r"^(?:fingerprint|指纹)\s*[:：=]\s*", part, re.I):
                fingerprint = re.sub(
                    r"^(?:fingerprint|指纹)\s*[:：=]\s*", "", part, flags=re.I
                ).strip()
            elif re.match(r"^消息[:：]", part):
                preview = " ".join(re.sub(r"^消息[:：]\s*", "", part).split()).strip()
            elif part.startswith("未读") or part.startswith("已读"):
                continue
            elif not job_title:
                job_title = part
        row = {
            "index": index,
            "name": name,
            "unread": "未读" in line,
        }
        if preview:
            row["preview"] = preview
        if external_id:
            row["external_id"] = external_id
        if fingerprint:
            row["fingerprint"] = fingerprint
        if job_title:
            row["job_title"] = job_title
        rows.append(row)
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
