"""Canonical tool names for calls that arrive with Antigravity CLI spellings.

The kernel classifies tools by name (`Bash`, `Write`, `mcp__<server>__<tool>`)
and hashes their input to match an intention against the call that follows it.
Antigravity CLI spells the same calls differently: every MCP call is one tool,
`call_mcp_tool`, whose `ServerName` / `ToolName` / `Arguments` say what was
really called; the shell is `run_command` with a `CommandLine`; file writes
are `write_to_file` / `replace_file_content`. Each call also carries two
descriptive keys, `toolAction` and `toolSummary`, that the model writes
freshly every time and that no intention could predict.

`canonical_tool_call` maps all of that onto the kernel's vocabulary. It is
applied on both sides of the gate -- when an intention is proposed and when the
hook sees the call -- so a proposal made in either spelling matches the call
in either spelling. It is idempotent on canonical input, so the Claude Code
adapter is unaffected.
"""

from __future__ import annotations

from typing import Any

MCP_CALL_TOOL = "call_mcp_tool"

# Read-only inspection tools, mapped onto the names `is_field_refreshing_tool`
# already knows so a `view_file` refreshes the field the way `Read` does.
_READ_TOOLS: dict[str, str] = {
    "view_file": "Read",
    "view_file_outline": "Read",
    "view_code_item": "Read",
    "view_content_chunk": "Read",
    "read_terminal": "Read",
    "command_status": "Read",
    "list_dir": "Glob",
    "find_by_name": "Glob",
    "grep_search": "Grep",
    "codebase_search": "Grep",
    "read_url_content": "WebFetch",
    "search_web": "WebSearch",
}

# Tools that change the filesystem, mapped onto the names the gate treats as
# outward actions.
_WRITE_TOOLS: dict[str, str] = {
    "write_to_file": "Write",
    "create_file": "Write",
    "delete_file": "Write",
    "replace_file_content": "Edit",
    "multi_replace_file_content": "Edit",
    "edit_file": "Edit",
    "notebook_edit": "NotebookEdit",
}

# Built-in tools that act on the world without being file writes or a shell.
# They are spelled as MCP-style names so the fragment rules in
# `is_external_tool` apply: `__notify` and `__send` are outward, `__get_` is
# not.
_OUTWARD_BUILTINS: dict[str, str] = {
    "send_command_input": "mcp__agy-terminal__send_command_input",
    "notify_user": "mcp__agy__notify_user",
    "generate_image": "mcp__agy__generate_image",
}

# Keys the model rewrites on every call; they describe the call to the user
# and cannot be part of an intention. `run_command` additionally carries
# `Cwd`, `WaitMsBeforeAsync`, `Blocking` and `SafeToAutoRun`, which vary
# between a proposal and the call without changing what the command does;
# the `run_command` branch keeps only the command line.
_DESCRIPTIVE_KEYS = frozenset({"toolAction", "toolSummary"})


def _strip(args: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key not in _DESCRIPTIVE_KEYS}


def canonical_tool_call(
    tool_name: str | None,
    tool_input: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return `(tool_name, tool_input)` in the kernel's own vocabulary."""

    name = str(tool_name or "")
    args: dict[str, Any] = dict(tool_input) if isinstance(tool_input, dict) else {}
    lowered = name.lower()

    if lowered == MCP_CALL_TOOL:
        server = str(args.get("ServerName") or args.get("server_name") or "").strip()
        tool = str(args.get("ToolName") or args.get("tool_name") or "").strip()
        arguments = args.get("Arguments", args.get("arguments"))
        if server and tool:
            return (
                f"mcp__{server}__{tool}",
                dict(arguments) if isinstance(arguments, dict) else {},
            )
        return name, _strip(args)

    if lowered == "run_command":
        command = args.get("CommandLine", args.get("command", ""))
        return "Bash", {"command": str(command if command is not None else "")}

    if lowered in _WRITE_TOOLS:
        return _WRITE_TOOLS[lowered], _strip(args)

    if lowered in _READ_TOOLS:
        return _READ_TOOLS[lowered], _strip(args)

    if lowered in _OUTWARD_BUILTINS:
        return _OUTWARD_BUILTINS[lowered], _strip(args)

    if lowered.startswith("browser_"):
        # Browser actions reach the network and the page; the fragment rules
        # keep `browser_get_dom` internal and make `browser_click_element`
        # outward.
        return f"mcp__browser__{lowered[len('browser_'):]}", _strip(args)

    # Canonical names (`Bash`, `Write`, `mcp__*`) and unknown tools pass
    # through; only the descriptive keys are dropped.
    return name, _strip(args)
