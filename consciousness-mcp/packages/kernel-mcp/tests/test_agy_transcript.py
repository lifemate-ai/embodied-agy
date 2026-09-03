"""The transcript is the only place agy records what the hook payload omits.

The fixture lines are shortened copies of a real
`transcript_full.jsonl` written by agy 1.1.25 during a print-mode run.
"""

from __future__ import annotations

import json
from pathlib import Path

from kernel_mcp.agy_transcript import (
    last_assistant_message,
    last_user_prompt,
    read_transcript,
    tool_result,
    user_prompt_text,
)

STEPS = [
    {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "content": (
            "<USER_REQUEST>\nRun echo probe-ok and reply DONE.\n</USER_REQUEST>\n"
            "<ADDITIONAL_METADATA>\nThe absolute URI of the USER's workspace is: x\n"
            "</ADDITIONAL_METADATA>"
        ),
    },
    {
        "step_index": 1,
        "source": "SYSTEM_SDK",
        "type": "EPHEMERAL_MESSAGE",
        "content": "PROBE-EPHEMERAL",
    },
    {
        "step_index": 2,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "tool_calls": [{"name": "run_command", "args": {"CommandLine": "echo probe-ok"}}],
    },
    {
        "step_index": 3,
        "source": "MODEL",
        "type": "GENERIC",
        "content": (
            "Created At: 2026-09-03T21:32:53+09:00\nCompleted At: 2026-09-03T21:32:53+09:00\n\n"
            "The command exited with code 0.\nOutput:\nprobe-ok\r\n\n"
        ),
    },
    {
        "step_index": 5,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "content": "DONE [CONTINUE: look outside]",
    },
]


def _write(path: Path, steps: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(step, ensure_ascii=False) + "\n" for step in steps),
        encoding="utf-8",
    )
    return path


def test_read_transcript_tolerates_missing_and_partial_files(tmp_path: Path) -> None:
    assert read_transcript(None) == []
    assert read_transcript(tmp_path / "absent.jsonl") == []
    partial = tmp_path / "partial.jsonl"
    partial.write_text('{"step_index": 0, "type": "USER_INPUT", "content": "hi"}\n{"trunc', "utf-8")
    steps = read_transcript(partial)
    assert [step["step_index"] for step in steps] == [0]


def test_user_prompt_is_unwrapped() -> None:
    assert last_user_prompt(STEPS) == "Run echo probe-ok and reply DONE."
    assert user_prompt_text("plain text\n<ADDITIONAL_METADATA>\nx\n</ADDITIONAL_METADATA>") == (
        "plain text"
    )
    assert user_prompt_text("just this") == "just this"


def test_last_assistant_message_skips_tool_only_steps(tmp_path: Path) -> None:
    assert last_assistant_message(STEPS) == "DONE [CONTINUE: look outside]"
    assert last_assistant_message(STEPS[:3]) is None


def test_tool_result_is_looked_up_by_the_hooks_step_index() -> None:
    result = tool_result(STEPS, 3)
    assert result is not None
    assert result.startswith("The command exited with code 0.")
    assert "Created At" not in result
    assert tool_result(STEPS, 2) is None  # the planner step, not a result
    assert tool_result(STEPS, 99) is None
    assert tool_result(STEPS, None) is None


def test_round_trip_through_a_file(tmp_path: Path) -> None:
    steps = read_transcript(_write(tmp_path / "t.jsonl", STEPS))
    assert last_user_prompt(steps) == "Run echo probe-ok and reply DONE."
    assert tool_result(steps, 3).startswith("The command exited")
