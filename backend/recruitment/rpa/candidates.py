import re


def _clean(value):
    return " ".join(str(value or "").split()).strip()


def _split_tags(value):
    return [item.strip() for item in re.split(r"\s*/\s*|\s*、\s*", value or "") if item.strip()]


def _base_row(name):
    return {
        "external_id": "",
        "identity_quality": "fingerprint",
        "display_name": _clean(name),
        "current_title": "",
        "city": "",
        "experience": "",
        "education": "",
        "advantage": "",
        "tags": [],
        "contact_hint": "",
    }


def _city_from(value):
    first = re.split(r"\s*/\s*|\s*·\s*|\s+", _clean(value), maxsplit=1)[0]
    return first if first and len(first) <= 12 else ""


def _parse_recommend(output):
    rows = []
    current = None
    for line in output.splitlines():
        match = re.match(r"^\s*-\s*\d+\.\s*(.+)$", line)
        if match:
            parts = [part.strip() for part in match.group(1).split("｜") if part.strip()]
            if not parts or parts[0] == "暂无":
                current = None
                continue
            current = _base_row(parts[0].replace(" | 看过", ""))
            for part in parts[1:]:
                if ":" in part or "：" in part:
                    key, value = re.split(r"[:：]", part, maxsplit=1)
                    value = _clean(value)
                    if key == "信息":
                        current["city"] = _city_from(value)
                        current["education"] = value
                    elif key == "期望":
                        current["current_title"] = value
                    elif key == "经历":
                        current["experience"] = value
                elif "打招呼" in part or "沟通过" in part:
                    current["contact_hint"] = part
            rows.append(current)
            continue
        advantage = re.match(r"^\s*优势\s*[:：]\s*(.+)$", line)
        if advantage and current:
            value = _clean(advantage.group(1))
            current["advantage"] = value
            current["tags"] = _split_tags(value)
    return rows


def _parse_search(output):
    rows = []
    current = None
    for line in output.splitlines():
        match = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
        if match:
            parts = [part.strip() for part in match.group(2).split("｜") if part.strip()]
            current = _base_row(parts[0])
            for part in parts[1:]:
                if part.startswith("标签:") or part.startswith("标签："):
                    current["tags"] = _split_tags(re.split(r"[:：]", part, maxsplit=1)[1])
                elif not current["city"]:
                    current["city"] = _city_from(part)
            rows.append(current)
            continue
        detail = re.match(r"^\s*(摘要|亮点|经历|教育)\s*[:：]\s*(.+)$", line)
        if not detail or not current:
            continue
        key, value = detail.group(1), _clean(detail.group(2))
        if key == "摘要":
            current["current_title"] = value
        elif key == "亮点":
            current["advantage"] = value
            current["tags"] = _split_tags(value)
        elif key == "经历":
            current["experience"] = value
        elif key == "教育":
            current["education"] = value
    return rows


def _parse_deep_search(output):
    rows = []
    current = None
    for line in output.splitlines():
        match = re.match(r"^\s*(\d+)\.\s*(.+)$", line)
        if match:
            current = _base_row(match.group(2))
            rows.append(current)
            continue
        detail = re.match(r"^\s*(概要|经历|教育|推荐)\s*[:：]\s*(.+)$", line)
        if not detail or not current:
            continue
        key, value = detail.group(1), _clean(detail.group(2))
        if key == "概要":
            current["city"] = _city_from(value)
        elif key == "经历":
            current["experience"] = value
            current["current_title"] = value
        elif key == "教育":
            current["education"] = value
        elif key == "推荐":
            current["advantage"] = value
    return rows


def parse_candidate_output(output, *, source):
    if source == "recommend":
        return _parse_recommend(output)
    if source == "search":
        return _parse_search(output)
    if source == "deep_search":
        return _parse_deep_search(output)
    raise ValueError("不支持的候选人来源")


def deep_search_args(*, job="", core=None, bonus=None, match=False):
    args = ["deep-search"]
    if _clean(job):
        args.extend(["--job", _clean(job)])
    for value in core or []:
        if _clean(value):
            args.extend(["--core", _clean(value)])
    for value in bonus or []:
        if _clean(value):
            args.extend(["--bonus", _clean(value)])
    if match:
        args.append("--match")
    return args
