"""Parse JSON 'lỏng' từ output của LLM (có thể kèm ```json fence hoặc lời dẫn)."""
from __future__ import annotations

import json
import re
from typing import Any


def parse_json_loose(text: str) -> Any | None:
    """Trả về object JSON đầu tiên tìm thấy trong text, hoặc None nếu không parse được."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # Tìm khối {...} hoặc [...] cân bằng đầu tiên
    for opener, closer in (("{", "}"), ("[", "]")):
        start = t.find(opener)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(t)):
                ch = t[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(t[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = t.find(opener, start + 1)
    return None
