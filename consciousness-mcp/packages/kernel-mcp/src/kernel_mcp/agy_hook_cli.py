"""Antigravity CLI hook adapter for the enacted-field runtime.

Antigravity CLI (`agy`) has five hook events and a payload of its own; the
handlers in `hook_cli` speak Claude Code's. This module is the translation
layer, measured against agy 1.1.25 rather than read from a description:

    agy event         fires                       -> handler(s)
    PreInvocation #0  before the first model call -> session_start (once per
                                                     conversation), then
                                                     user_prompt_submit
    PreInvocation #n  before every later call     -> post_tool_batch over the
                                                     tool calls since #n-1
    PreToolUse        before a tool               -> pre_tool_use (the gate)
    PostToolUse       after a tool ran            -> post_tool_use or
                                                     post_tool_use_failure
    Stop              when the loop ends          -> stop or stop_failure

What the payload lacks is read from the transcript (`agy_transcript`): the
prompt, each tool's result, the last assistant message. Tool names are
canonicalised (`agy_tools`) before the gate sees them, so `call_mcp_tool`
with `ServerName=tts` is gated as `mcp__tts__say`.

Outputs follow the agy contract. Context goes back as one `ephemeralMessage`
in `injectSteps` (there is no PostToolUse context in agy, so the refreshed
field surfaces on the next PreInvocation instead), a refused tool is
`{"decision": "deny", "reason": ...}`, and a heartbeat continuation is
`{"decision": "continue", "reason": ...}` on Stop.

Hook commands run with the directory holding `hooks.json` as their working
directory and with only `ANTIGRAVITY_CONVERSATION_ID` in the environment
beyond what agy inherited, so the project root comes from `workspacePaths`
(or the parent of a `.agents` cwd) and is exported as `EFPF_PROJECT_DIR` for
`hook_cli` to find the MCP config.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from boundary_mcp.store import BoundaryStore
from social_core import SocialDB

from kernel_mcp import hook_cli
from kernel_mcp.agy_tools import canonical_tool_call
from kernel_mcp.agy_transcript import (
    last_assistant_message,
    last_user_prompt,
    read_transcript,
    tool_result,
)
from kernel_mcp.boundary_adapter import BoundaryPolicyAdapter
from kernel_mcp.tick import FieldRuntime, TickProducer

COMMANDS = (
    "pre-invocation",
    "pre-tool-use",
    "post-tool-use",
    "post-invocation",
    "stop",
    "diagnostics",
    "organism-step",
)

WORKSPACE_CONFIG_DIRS = frozenset({".agents", "_agents", ".agent", "_agent"})

# What an allowed call answers. Claude Code's adapter answers `allow`, which
# in both harnesses bypasses the permission prompt: the intention gate is the
# permission system once it is armed. `EFPF_AGY_ALLOW_DECISION=ask` keeps
# agy's own prompts in front of the user in interactive sessions.
ALLOW_DECISION_ENV = "EFPF_AGY_ALLOW_DECISION"
DEFAULT_ALLOW_DECISION = "allow"

# Kept for tests and diagnostics; the temp root is what changes per platform.
BATCH_DIRNAME = "efpf-agy-batch"
SESSION_DIRNAME = "efpf-agy-sessions"
_MAX_PROMPT_CHARS = 4000


def _temp_root() -> Path:
    return Path(os.getenv("EFPF_RUNTIME_TEMP", "").strip() or tempfile.gettempdir())


def _batch_path(conversation_id: str) -> Path:
    return _temp_root() / BATCH_DIRNAME / f"{conversation_id or 'none'}.jsonl"


def _session_marker(conversation_id: str) -> Path:
    return _temp_root() / SESSION_DIRNAME / (conversation_id or "none")


def project_dir_from_payload(payload: dict[str, Any]) -> Path | None:
    """The workspace root agy is running in, or None when it cannot be known.

    Print mode without `--add-dir` sends an empty `workspacePaths`, and then
    the only clue is that hook commands run inside the customization
    directory (`.agents/`), whose parent is the workspace.
    """
    paths = payload.get("workspacePaths")
    if isinstance(paths, list):
        for value in paths:
            if isinstance(value, str) and value.strip():
                return Path(value)
    cwd = Path.cwd()
    if cwd.name in WORKSPACE_CONFIG_DIRS:
        return cwd.parent
    return None


def _export_project_dir(payload: dict[str, Any]) -> None:
    if os.environ.get("EFPF_PROJECT_DIR"):
        return
    root = project_dir_from_payload(payload)
    if root is not None:
        os.environ["EFPF_PROJECT_DIR"] = str(root)


def _conversation_id(payload: dict[str, Any]) -> str:
    value = payload.get("conversationId") or os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
    return str(value or "")


def _steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return read_transcript(payload.get("transcriptPath"))


def _tool_call(payload: dict[str, Any]) -> tuple[str, dict[str, Any], str, dict[str, Any]]:
    """Return `(canonical_name, canonical_input, raw_name, raw_args)`."""
    call = payload.get("toolCall")
    call = call if isinstance(call, dict) else {}
    raw_name = str(call.get("name") or "")
    raw_args = call.get("args")
    raw_args = raw_args if isinstance(raw_args, dict) else {}
    name, args = canonical_tool_call(raw_name, raw_args)
    return name, args, raw_name, raw_args


def _step_idx(payload: dict[str, Any]) -> int | None:
    try:
        return int(payload["stepIdx"])
    except (KeyError, TypeError, ValueError):
        return None


def _context_of(result: dict[str, Any]) -> str:
    output = result.get("hookSpecificOutput")
    if isinstance(output, dict):
        return str(output.get("additionalContext") or "")
    return ""


def _inject(context: str) -> dict[str, Any]:
    if not context:
        return {"injectSteps": []}
    return {"injectSteps": [{"ephemeralMessage": context}]}


def _base_payload(payload: dict[str, Any]) -> dict[str, Any]:
    base: dict[str, Any] = {"session_id": _conversation_id(payload)}
    for key in ("owner_id", "person_id"):
        if payload.get(key):
            base[key] = payload[key]
    return base


# --- batch queue -----------------------------------------------------------


def _enqueue(conversation_id: str, entry: dict[str, Any]) -> None:
    path = _batch_path(conversation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _drain(conversation_id: str) -> list[dict[str, Any]]:
    path = _batch_path(conversation_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    path.unlink(missing_ok=True)
    entries: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


# --- handlers ----------------------------------------------------------------


def pre_invocation(payload: dict[str, Any], producer: TickProducer) -> dict[str, Any]:
    conversation_id = _conversation_id(payload)
    try:
        invocation = int(payload.get("invocationNum") or 0)
    except (TypeError, ValueError):
        invocation = 0
    steps = _steps(payload)
    base = _base_payload(payload)

    if invocation == 0:
        # A new turn: whatever was queued for a previous turn is stale.
        _batch_path(conversation_id).unlink(missing_ok=True)
        recovery_note = ""
        marker = _session_marker(conversation_id)
        if conversation_id and not marker.exists():
            started = hook_cli.session_start(dict(base), producer)
            context = _context_of(started)
            cut = context.find("\n\nRuntime recovery")
            if cut >= 0:
                recovery_note = context[cut:]
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("started\n", encoding="utf-8")
        prompt = last_user_prompt(steps) or ""
        submitted = hook_cli.user_prompt_submit(
            {**base, "prompt": prompt[:_MAX_PROMPT_CHARS]},
            producer,
        )
        return _inject(_context_of(submitted) + recovery_note)

    entries = _drain(conversation_id)
    if not entries:
        return {"injectSteps": []}
    tool_calls = []
    for entry in entries:
        step_idx = entry.get("step_idx")
        response = tool_result(steps, step_idx if isinstance(step_idx, int) else None)
        if response is None:
            response = str(entry.get("summary") or "")
        tool_calls.append(
            {
                "tool_name": entry.get("tool_name"),
                "tool_input": entry.get("tool_input"),
                "tool_use_id": f"{conversation_id}:{step_idx}",
                "tool_response": response,
            }
        )
    batched = hook_cli.post_tool_batch({**base, "tool_calls": tool_calls}, producer)
    return _inject(_context_of(batched))


def pre_tool_use(payload: dict[str, Any], runtime: FieldRuntime) -> dict[str, Any]:
    name, args, _, _ = _tool_call(payload)
    result = hook_cli.pre_tool_use(
        {**_base_payload(payload), "tool_name": name, "tool_input": args},
        runtime,
    )
    output = result.get("hookSpecificOutput") or {}
    reason = str(output.get("permissionDecisionReason") or "")
    if output.get("permissionDecision") == "deny":
        return {"decision": "deny", "reason": reason}
    decision = os.getenv(ALLOW_DECISION_ENV, "").strip() or DEFAULT_ALLOW_DECISION
    return {"decision": decision, "reason": reason}


def post_tool_use(payload: dict[str, Any], runtime: FieldRuntime) -> dict[str, Any]:
    name, args, raw_name, _ = _tool_call(payload)
    conversation_id = _conversation_id(payload)
    step_idx = _step_idx(payload)
    error = str(payload.get("error") or "")
    base = {
        **_base_payload(payload),
        "tool_name": name,
        "tool_input": args,
        "tool_use_id": f"{conversation_id}:{step_idx}",
    }
    if error:
        hook_cli.post_tool_use_failure({**base, "error": error}, runtime)
        summary = f"{raw_name} failed: {error}"
    else:
        recorded = tool_result(_steps(payload), step_idx)
        summary = recorded if recorded is not None else f"{raw_name} completed"
        hook_cli.post_tool_use({**base, "tool_response": summary}, runtime)
    _enqueue(
        conversation_id,
        {
            "step_idx": step_idx,
            "tool_name": name,
            "tool_input": args,
            "error": error,
            "summary": summary[:500],
        },
    )
    return {}


def post_invocation(payload: dict[str, Any], producer: TickProducer) -> dict[str, Any]:
    # The refreshed field is injected on the next PreInvocation, which fires
    # right after this event; nothing further is needed here.
    return {}


def stop(payload: dict[str, Any], producer: TickProducer) -> dict[str, Any]:
    base = _base_payload(payload)
    error = str(payload.get("error") or "")
    reason = str(payload.get("terminationReason") or "")
    if error or reason.lower() == "error":
        hook_cli.stop_failure({**base, "error": error or reason}, producer)
        return {}
    last = last_assistant_message(_steps(payload)) or ""
    result = hook_cli.stop({**base, "last_assistant_message": last}, producer)
    if result.get("decision") == "block":
        return {"decision": "continue", "reason": str(result.get("reason") or "")}
    return {}


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="efpf-agy-hook")
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args()
    payload = hook_cli._read_input()
    if payload is None:
        if args.command == "pre-tool-use":
            hook_cli._emit({"decision": "deny", "reason": hook_cli.UNREADABLE_INPUT_REASON})
            return
        payload = {}
    _export_project_dir(payload)
    db = SocialDB()
    producer = TickProducer(db)
    runtime = FieldRuntime(
        db,
        producer=producer,
        boundary_evaluator=BoundaryPolicyAdapter(BoundaryStore(db=db)),
        compatibility_mode=False,
    )
    handlers = {
        "pre-invocation": lambda: pre_invocation(payload, producer),
        "pre-tool-use": lambda: pre_tool_use(payload, runtime),
        "post-tool-use": lambda: post_tool_use(payload, runtime),
        "post-invocation": lambda: post_invocation(payload, producer),
        "stop": lambda: stop(payload, producer),
        "diagnostics": lambda: hook_cli.diagnostics(_base_payload(payload), producer),
        "organism-step": lambda: hook_cli.organism_step(db, producer),
    }
    try:
        hook_cli._emit(handlers[args.command]())
    except Exception as exc:
        if args.command == "pre-tool-use":
            hook_cli._emit(
                {
                    "decision": "deny",
                    "reason": hook_cli._deny_reason("EFPF hook failed closed: " + str(exc)),
                }
            )
        elif args.command == "pre-invocation":
            hook_cli._emit(
                _inject("EFPF runtime error; no field state was synthesized: " + str(exc))
            )
        else:
            print(f"efpf-agy-hook {args.command}: {exc}", file=sys.stderr)
            hook_cli._emit({})
    finally:
        db.close()


if __name__ == "__main__":
    main()
