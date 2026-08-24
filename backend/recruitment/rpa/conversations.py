import re


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
