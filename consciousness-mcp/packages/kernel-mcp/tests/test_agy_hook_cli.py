"""The Antigravity CLI adapter, driven the way agy drives it: one process per
event, JSON on stdin, JSON on stdout, nothing on stderr.

Payload shapes are the ones agy 1.1.25 sent to a hook that dumped its stdin;
the expected outputs are the shapes its docs and a live run accepted (a
`deny` the model saw the reason of, an `ephemeralMessage` it obeyed, and a
`continue` that re-entered the loop).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kernel_mcp.agy_hook_cli import (
    BATCH_DIRNAME,
    SESSION_DIRNAME,
    project_dir_from_payload,
)
from kernel_mcp.hook_cli import UNREADABLE_INPUT_REASON, kernel_server_configured

FIELD_PROTOCOL_HEAD = "# Enacted First-Person Field Protocol"


def _env(tmp_path: Path, overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["SOCIAL_DB_PATH"] = str(tmp_path / "hook-social.db")
    env["MEMORY_HTTP_PORT"] = "0"
    env["EFPF_RUNTIME_TEMP"] = str(tmp_path / "runtime-temp")
    env["EFPF_PROJECT_DIR"] = str(tmp_path)
    env.pop("HEARTBEAT", None)
    env.pop("EFPF_AGY_ALLOW_DECISION", None)
    env.update(overrides or {})
    return env


def _run(
    tmp_path: Path,
    command: str,
    payload: dict | None,
    *,
    raw_input: str | None = None,
    env_overrides: dict[str, str] | None = None,
) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "kernel_mcp.agy_hook_cli", command],
        input=json.dumps(payload) if raw_input is None else raw_input,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=_env(tmp_path, env_overrides),
        check=True,
    )
    assert result.stderr == ""
    return json.loads(result.stdout)


def _transcript(tmp_path: Path, steps: list[dict]) -> str:
    path = tmp_path / "transcript_full.jsonl"
    path.write_text(
        "".join(json.dumps(step, ensure_ascii=False) + "\n" for step in steps),
        encoding="utf-8",
    )
    return str(path)


def _common(tmp_path: Path, conversation_id: str, steps: list[dict] | None = None) -> dict:
    return {
        "conversationId": conversation_id,
        "workspacePaths": [str(tmp_path)],
        "transcriptPath": _transcript(tmp_path, steps or []),
        "artifactDirectoryPath": str(tmp_path / "brain"),
        "modelName": "gemini-3.8-flash-high",
    }


def _user_step(text: str, index: int = 0) -> dict:
    return {
        "step_index": index,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "content": (
            f"<USER_REQUEST>\n{text}\n</USER_REQUEST>\n"
            "<ADDITIONAL_METADATA>\nx\n</ADDITIONAL_METADATA>"
        ),
    }


def test_first_invocation_injects_the_field_protocol_once_per_turn(tmp_path: Path) -> None:
    payload = {
        **_common(tmp_path, "conv-1", [_user_step("hello there")]),
        "invocationNum": 0,
        "initialNumSteps": 1,
    }
    result = _run(tmp_path, "pre-invocation", payload)
    steps = result["injectSteps"]
    assert len(steps) == 1
    assert steps[0]["ephemeralMessage"].startswith(FIELD_PROTOCOL_HEAD)
    assert (tmp_path / "runtime-temp" / SESSION_DIRNAME / "conv-1").exists()


def test_later_invocations_with_nothing_queued_inject_nothing(tmp_path: Path) -> None:
    payload = {**_common(tmp_path, "conv-2"), "invocationNum": 1, "initialNumSteps": 3}
    assert _run(tmp_path, "pre-invocation", payload) == {"injectSteps": []}


def test_outward_tool_is_denied_without_an_intention(tmp_path: Path) -> None:
    payload = {
        **_common(tmp_path, "conv-3"),
        "stepIdx": 9,
        "toolCall": {
            "name": "run_command",
            "args": {
                "CommandLine": "rm -rf /tmp/probe",
                "Cwd": str(tmp_path),
                "WaitMsBeforeAsync": 5000,
                "toolAction": "Deleting",
                "toolSummary": "rm",
            },
        },
    }
    result = _run(tmp_path, "pre-tool-use", payload)
    assert result["decision"] == "deny"
    # No .agents/mcp_config.json under EFPF_PROJECT_DIR, so the reason points
    # at setup rather than at a tool the session cannot reach.
    assert "kernel MCP server is not configured" in result["reason"]
    assert ".agents/mcp_config.json" in result["reason"]


def test_inspection_tools_are_allowed_and_the_decision_is_configurable(tmp_path: Path) -> None:
    payload = {
        **_common(tmp_path, "conv-4"),
        "stepIdx": 3,
        "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(tmp_path / "x")}},
    }
    assert _run(tmp_path, "pre-tool-use", payload)["decision"] == "allow"
    asked = _run(
        tmp_path, "pre-tool-use", payload, env_overrides={"EFPF_AGY_ALLOW_DECISION": "ask"}
    )
    assert asked["decision"] == "ask"


def test_mcp_calls_are_gated_by_server_and_tool_name(tmp_path: Path) -> None:
    base = _common(tmp_path, "conv-5")
    say = {
        **base,
        "stepIdx": 6,
        "toolCall": {
            "name": "call_mcp_tool",
            "args": {"ServerName": "tts", "ToolName": "say", "Arguments": {"text": "hi"}},
        },
    }
    recall = {
        **base,
        "stepIdx": 7,
        "toolCall": {
            "name": "call_mcp_tool",
            "args": {"ServerName": "memory", "ToolName": "recall", "Arguments": {"query": "x"}},
        },
    }
    assert _run(tmp_path, "pre-tool-use", say)["decision"] == "deny"
    assert _run(tmp_path, "pre-tool-use", recall)["decision"] == "allow"


@pytest.mark.parametrize("raw_input", ["", "not json", "[1, 2]"])
def test_unreadable_stdin_fails_closed(tmp_path: Path, raw_input: str) -> None:
    result = _run(tmp_path, "pre-tool-use", None, raw_input=raw_input)
    assert result == {"decision": "deny", "reason": UNREADABLE_INPUT_REASON}
    assert _run(tmp_path, "post-tool-use", None, raw_input=raw_input) == {}


def test_tool_results_queue_until_the_next_invocation_refreshes_the_field(
    tmp_path: Path,
) -> None:
    steps = [
        _user_step("look at the file"),
        {
            "step_index": 2,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "/tmp/x"}}],
        },
        {
            "step_index": 3,
            "source": "MODEL",
            "type": "GENERIC",
            "content": "Created At: t\nCompleted At: t\nFile Path: /tmp/x\nhello from the file",
        },
    ]
    common = _common(tmp_path, "conv-6", steps)
    _run(tmp_path, "pre-invocation", {**common, "invocationNum": 0, "initialNumSteps": 1})
    post = {
        **common,
        "stepIdx": 3,
        "error": "",
        "toolCall": {"name": "view_file", "args": {"AbsolutePath": "/tmp/x"}},
    }
    assert _run(tmp_path, "post-tool-use", post) == {}
    queue = tmp_path / "runtime-temp" / BATCH_DIRNAME / "conv-6.jsonl"
    entry = json.loads(queue.read_text(encoding="utf-8").splitlines()[0])
    assert entry["tool_name"] == "Read"
    assert entry["summary"].startswith("File Path: /tmp/x")

    result = _run(
        tmp_path, "pre-invocation", {**common, "invocationNum": 1, "initialNumSteps": 4}
    )
    assert result["injectSteps"]
    assert result["injectSteps"][0]["ephemeralMessage"]
    assert not queue.exists()


def test_a_failed_tool_is_recorded_and_does_not_break_the_hook(tmp_path: Path) -> None:
    payload = {
        **_common(tmp_path, "conv-7"),
        "stepIdx": 4,
        "error": "exit status 1",
        "toolCall": {"name": "run_command", "args": {"CommandLine": "false"}},
    }
    assert _run(tmp_path, "post-tool-use", payload) == {}


def test_stop_maps_a_heartbeat_continuation_onto_agy_continue(tmp_path: Path) -> None:
    steps = [
        _user_step("heartbeat"),
        {
            "step_index": 2,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": "Looked around. [CONTINUE: check the balcony camera]",
        },
    ]
    payload = {
        **_common(tmp_path, "conv-8", steps),
        "executionNum": 0,
        "terminationReason": "NO_TOOL_CALL",
        "error": "",
        "fullyIdle": True,
    }
    heartbeat = {"HEARTBEAT": "1", "MAX_CONTINUES": "2"}
    first = _run(tmp_path, "stop", payload, env_overrides=heartbeat)
    assert first["decision"] == "continue"
    assert "check the balcony camera" in first["reason"]
    assert "1/2" in first["reason"]
    second = _run(tmp_path, "stop", payload, env_overrides=heartbeat)
    assert second["decision"] == "continue"
    assert "2/2" in second["reason"]
    assert _run(tmp_path, "stop", payload, env_overrides=heartbeat) == {}

    # An interactive session never continues on its own.
    assert _run(tmp_path, "stop", payload) == {}


def test_stop_with_an_error_lets_the_agent_stop(tmp_path: Path) -> None:
    payload = {
        **_common(tmp_path, "conv-9"),
        "executionNum": 0,
        "terminationReason": "error",
        "error": "model call failed",
        "fullyIdle": True,
    }
    assert _run(tmp_path, "stop", payload, env_overrides={"HEARTBEAT": "1"}) == {}


def test_post_invocation_and_diagnostics_answer(tmp_path: Path) -> None:
    common = _common(tmp_path, "conv-10")
    assert _run(tmp_path, "post-invocation", {**common, "invocationNum": 0}) == {}
    diagnostics = _run(tmp_path, "diagnostics", common)
    assert diagnostics["owner_id"] == "self"


def test_project_dir_comes_from_workspace_paths_or_the_agents_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert project_dir_from_payload({"workspacePaths": [str(tmp_path)]}) == tmp_path
    agents = tmp_path / ".agents"
    agents.mkdir()
    monkeypatch.chdir(agents)
    assert project_dir_from_payload({"workspacePaths": []}) == tmp_path
    monkeypatch.chdir(tmp_path)
    assert project_dir_from_payload({}) is None


def test_kernel_server_configured_reads_the_agents_mcp_config(tmp_path: Path) -> None:
    assert kernel_server_configured(tmp_path) is False
    agents = tmp_path / ".agents"
    agents.mkdir()
    (agents / "mcp_config.json").write_text(
        json.dumps({"mcpServers": {"kernel": {"command": "uv"}}}), "utf-8"
    )
    assert kernel_server_configured(tmp_path) is True
    (agents / "mcp_config.json").write_text("{not json", "utf-8")
    assert kernel_server_configured(tmp_path) is None
