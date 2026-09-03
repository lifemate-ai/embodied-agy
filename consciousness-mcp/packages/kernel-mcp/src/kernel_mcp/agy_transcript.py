"""Read what Antigravity CLI hooks do not carry from the conversation transcript.

Claude Code hands its hooks the user's prompt, the tool's response, and the
last assistant message in the payload. Antigravity CLI hands them a
`transcriptPath` instead: a JSONL file under
`~/.gemini/antigravity-cli/brain/<conversationId>/.system_generated/logs/`
with one step per line. Measured against agy 1.1.25:

    {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
     "content": "<USER_REQUEST>\\n...\\n</USER_REQUEST>\\n<ADDITIONAL...>"}
    {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE",
     "tool_calls": [{"name": "run_command", "args": {...}}]}
    {"step_index": 3, "source": "MODEL", "type": "GENERIC",
     "content": "Created At: ...\\nCompleted At: ...\\n<tool result>"}
    {"step_index": 5, "source": "MODEL", "type": "PLANNER_RESPONSE",
     "content": "DONE"}

The `stepIdx` a PreToolUse/PostToolUse hook receives is the index of the
result step, so `tool_result(steps, step_idx)` is a direct lookup. Everything
here is best-effort: a missing or half-written file yields `None`, never an
exception, because a hook that cannot read the transcript must still gate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_USER_REQUEST = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)
_TRAILING_BLOCK = re.compile(r"\s*<[A-Z_]+>.*\Z", re.DOTALL)
_RESULT_HEADER = re.compile(r"^(Created At|Completed At):[^\n]*\n?", re.MULTILINE)


def read_transcript(path: str | Path | None) -> list[dict[str, Any]]:
    """Return the transcript steps, tolerating a missing or partial file."""

    if not path:
        return []
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    steps: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            steps.append(value)
    return steps


def user_prompt_text(content: str) -> str:
    """Strip the `<USER_REQUEST>` wrapper and any trailing system block."""

    match = _USER_REQUEST.search(content)
    if match:
        return match.group(1).strip()
    return _TRAILING_BLOCK.sub("", content).strip()


def last_user_prompt(steps: list[dict[str, Any]]) -> str | None:
    for step in reversed(steps):
        if step.get("type") == "USER_INPUT":
            content = step.get("content")
            return user_prompt_text(content) if isinstance(content, str) else None
    return None


def last_assistant_message(steps: list[dict[str, Any]]) -> str | None:
    for step in reversed(steps):
        if step.get("source") != "MODEL" or step.get("type") != "PLANNER_RESPONSE":
            continue
        content = step.get("content")
        if isinstance(content, str) and content.strip():
            return content
    return None


def tool_result(steps: list[dict[str, Any]], step_idx: int | None) -> str | None:
    """The recorded result of the tool step `step_idx`, without its timestamps."""

    if step_idx is None:
        return None
    for step in steps:
        if step.get("step_index") != step_idx:
            continue
        if step.get("type") == "PLANNER_RESPONSE":
            return None
        content = step.get("content")
        if isinstance(content, str):
            return _RESULT_HEADER.sub("", content).strip()
        return None
    return None
