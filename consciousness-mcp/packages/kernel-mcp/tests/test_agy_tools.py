"""Antigravity CLI spells tool calls differently; the gate must not notice.

Every case is a call shape agy 1.1.25 actually sent to a PreToolUse hook,
or the kernel's own canonical spelling of the same call.
"""

from __future__ import annotations

from kernel_mcp.agency import ActionProposal, hash_tool_input, is_external_tool
from kernel_mcp.agy_tools import canonical_tool_call
from kernel_mcp.tick import is_field_refreshing_tool


def test_call_mcp_tool_becomes_the_kernel_mcp_name() -> None:
    name, args = canonical_tool_call(
        "call_mcp_tool",
        {
            "ServerName": "tts",
            "ToolName": "say",
            "Arguments": {"text": "hi"},
            "toolAction": "Speaking",
            "toolSummary": "Say hi",
        },
    )
    assert name == "mcp__tts__say"
    assert args == {"text": "hi"}


def test_call_mcp_tool_without_server_or_tool_is_left_alone() -> None:
    name, args = canonical_tool_call("call_mcp_tool", {"Arguments": {}, "toolAction": "x"})
    assert name == "call_mcp_tool"
    assert args == {"Arguments": {}}


def test_run_command_becomes_bash_with_only_the_command_line() -> None:
    name, args = canonical_tool_call(
        "run_command",
        {
            "CommandLine": "echo probe-ok",
            "Cwd": "/home/user/project",
            "WaitMsBeforeAsync": 5000,
            "toolAction": "Running command",
            "toolSummary": "Run echo",
        },
    )
    assert (name, args) == ("Bash", {"command": "echo probe-ok"})


def test_file_tools_map_onto_write_and_edit() -> None:
    name, args = canonical_tool_call(
        "write_to_file",
        {"TargetFile": "/tmp/x.txt", "CodeContent": "hi", "toolAction": "Writing"},
    )
    assert name == "Write"
    assert args == {"TargetFile": "/tmp/x.txt", "CodeContent": "hi"}
    assert canonical_tool_call("replace_file_content", {})[0] == "Edit"
    assert canonical_tool_call("multi_replace_file_content", {})[0] == "Edit"


def test_read_tools_refresh_the_field_like_their_claude_counterparts() -> None:
    assert canonical_tool_call("view_file", {"AbsolutePath": "/tmp/x"})[0] == "Read"
    assert canonical_tool_call("grep_search", {})[0] == "Grep"
    assert canonical_tool_call("list_dir", {})[0] == "Glob"
    assert canonical_tool_call("search_web", {})[0] == "WebSearch"
    assert canonical_tool_call("read_url_content", {})[0] == "WebFetch"
    assert is_field_refreshing_tool("view_file")
    assert is_field_refreshing_tool("search_web")


def test_canonical_spellings_pass_through_unchanged() -> None:
    assert canonical_tool_call("Bash", {"command": "ls"}) == ("Bash", {"command": "ls"})
    assert canonical_tool_call("mcp__memory__recall", {"query": "x"}) == (
        "mcp__memory__recall",
        {"query": "x"},
    )
    assert canonical_tool_call("", None) == ("", {})


def test_gate_classifies_agy_spellings() -> None:
    assert not is_external_tool("run_command", {"CommandLine": "ls -la"})
    assert is_external_tool("run_command", {"CommandLine": "rm -rf /tmp/x"})
    assert is_external_tool(
        "call_mcp_tool", {"ServerName": "tts", "ToolName": "say", "Arguments": {}}
    )
    assert not is_external_tool(
        "call_mcp_tool", {"ServerName": "memory", "ToolName": "recall", "Arguments": {}}
    )
    assert not is_external_tool(
        "call_mcp_tool",
        {"ServerName": "kernel", "ToolName": "propose_field_action", "Arguments": {}},
    )
    assert is_external_tool("write_to_file", {"TargetFile": "/tmp/x", "CodeContent": "hi"})
    assert is_external_tool("replace_file_content", {"TargetFile": "/tmp/x"})
    assert not is_external_tool("view_file", {"AbsolutePath": "/tmp/x"})
    assert not is_external_tool("browser_get_dom", {})
    assert is_external_tool("browser_click_element", {"Index": 3})
    assert is_external_tool("notify_user", {"Message": "hi"})
    assert is_external_tool("send_command_input", {"CommandId": "1", "Input": "y"})


def test_proposal_and_call_hash_the_same_in_either_spelling() -> None:
    proposal = ActionProposal(
        field_id="field",
        tool_name="call_mcp_tool",
        tool_input={
            "ServerName": "tts",
            "ToolName": "say",
            "Arguments": {"text": "hi"},
            "toolAction": "Speaking",
        },
        goal="greet",
    )
    assert proposal.tool_name == "mcp__tts__say"
    _, actual = canonical_tool_call("mcp__tts__say", {"text": "hi"})
    assert hash_tool_input(proposal.tool_input) == hash_tool_input(actual)

    shell = ActionProposal(
        field_id="field",
        tool_name="run_command",
        tool_input={"CommandLine": "touch /tmp/x", "Cwd": "/tmp"},
        goal="touch",
    )
    _, actual_shell = canonical_tool_call(
        "run_command",
        {"CommandLine": "touch /tmp/x", "Cwd": "/elsewhere", "WaitMsBeforeAsync": 1},
    )
    assert shell.tool_name == "Bash"
    assert hash_tool_input(shell.tool_input) == hash_tool_input(actual_shell)
