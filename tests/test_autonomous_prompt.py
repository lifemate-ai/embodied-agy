"""The autonomous prompt has to reach agy as written.

PROMPT is assembled as a double-quoted shell string, so anything the prompt
says with backticks is command substitution rather than markup. The tool names
in the supplementary rules were being executed, failing, and substituted with
the empty string -- the rules arrived as arrows pointing at nothing.

Nothing surfaces that: `command not found` goes to stderr, which cron discards,
and the log records the prompt after the stripping.

The second half pins the Antigravity CLI invocation (docs/antigravity.md),
which fails just as quietly. `agy -p` takes the prompt as the flag's value:
piping it on stdin, as the Claude Code version did, makes the next flag the
prompt and the run "succeeds". Print mode does not attach the current
directory, so without `--add-dir` neither `.agents/hooks.json` nor
`.agents/mcp_config.json` loads, and the heartbeat exits 0 with no kernel and
no memory. The Claude-only flags it replaced have no agy equivalent and must
not come back.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "autonomous-action.sample.sh"

# The script is mostly Japanese, so the encoding cannot be left to the locale.
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")

PROMPT_START = 'PROMPT="自律行動タイム'
PROMPT_END = '${INTEROCEPTION_SECTION}"'


def _prompt_block() -> str:
    start = SCRIPT.index(PROMPT_START)
    return SCRIPT[start : SCRIPT.index(PROMPT_END, start)]


def _code_lines() -> list[str]:
    """Script lines with comments dropped, so prose about the old flags does not count."""
    return [line for line in SCRIPT.splitlines() if not line.lstrip().startswith("#")]


def _invocations() -> list[str]:
    """The lines that actually run agy (the dry-run's `echo "agy -p ..."` is prose)."""
    return [
        line
        for line in _code_lines()
        if "agy -p" in line and not line.lstrip().startswith("echo")
    ]


def _agy_args_block() -> str:
    start = SCRIPT.index("AGY_ARGS=(")
    return SCRIPT[start : SCRIPT.index(")", start)]


def test_prompt_block_is_where_we_think_it_is() -> None:
    # If the prompt is ever rewritten as a quoted heredoc, the check below stops
    # being meaningful rather than starting to fail. Pin the assumption.
    assert SCRIPT.count(PROMPT_START) == 1
    assert SCRIPT.count(PROMPT_END) == 1
    assert "PROMPT=$(cat <<" not in SCRIPT


def test_prompt_quotes_tool_names_without_running_them() -> None:
    unescaped = [match.start() for match in re.finditer(r"(?<!\\)`", _prompt_block())]
    assert unescaped == [], (
        "unescaped backtick in the prompt: the shell runs what it encloses and "
        "substitutes the empty string, so the tool name never reaches agy"
    )


def test_the_tool_names_are_still_there() -> None:
    # Escaping is only half of it: deleting the names would satisfy the check
    # above and lose the rules the prompt is trying to state. Dropping the
    # backticks instead of escaping them is a fine way to fix this, so the
    # names are checked without them.
    prompt = _prompt_block()
    for tool in (
        "get_social_state",
        "evaluate_action",
        "review_social_post",
        "ingest_social_event",
        "append_daybook",
    ):
        assert tool in prompt


def test_prompt_is_the_value_of_dash_p() -> None:
    # Measured on agy 1.1.25: `echo "$PROMPT" | agy -p --output-format json`
    # exits 2 with "-p took \"--output-format\" as its prompt". The prompt has
    # to be the argument right after -p, and every invocation has to say so.
    invocations = _invocations()
    assert invocations, "no agy -p invocation found"
    for line in invocations:
        assert 'agy -p "$PROMPT"' in line, line
        assert '"${AGY_ARGS[@]}"' in line, line
    assert not any(re.search(r"\|\s*agy\b", line) for line in _code_lines()), (
        "the prompt is piped into agy; agy reads it from -p, not stdin"
    )


def test_agy_args_attach_the_workspace_and_run_headless() -> None:
    block = _agy_args_block()
    for flag in (
        '--add-dir "$SCRIPT_DIR"',
        "--dangerously-skip-permissions",
        "--output-format json",
        "--print-timeout 20m",
    ):
        assert flag in block, flag


def test_resume_uses_the_conversation_id_from_the_json() -> None:
    code = "\n".join(_code_lines())
    assert '--conversation "$SESSION_ID"' in code
    assert ".conversation_id" in code
    assert ".response" in code
    assert ".status" in code
    # The Claude Code shape: --resume and .session_id / .result / .is_error.
    assert "--resume" not in code
    assert ".session_id" not in code
    assert ".is_error" not in code


def test_stderr_is_kept_apart_from_the_json() -> None:
    # A stale --conversation id is not an error on agy: exit 0, status SUCCESS,
    # a new conversation, and `warning: conversation "<id>" not found` on
    # stderr. Merging the streams (the Claude version's 2>&1) would hand that
    # warning to jq along with the JSON.
    for line in _invocations():
        assert "2>&1" not in line, line
        assert '2>"$AGY_STDERR"' in line, line
    code = "\n".join(_code_lines())
    assert "not found" in code, "the lost-conversation warning is not detected"


def test_claude_only_flags_and_files_are_gone() -> None:
    for leftover in (
        "--allowedTools",
        "allowedTools",
        "--mcp-config",
        "autonomous-mcp.json",
        ".claude/",
        "enabledMcpjsonServers",
        "permissions.allow",
    ):
        assert leftover not in SCRIPT, leftover


def test_the_timeout_backstop_survived() -> None:
    code = "\n".join(_code_lines())
    assert '"$TIMEOUT_CMD" 20m agy -p' in code
    assert '"$AGY_EXIT" -eq 124' in code


def test_heartbeat_is_exported_for_the_hooks() -> None:
    # PreInvocation inherits the environment; this is how efpf-agy-hook knows
    # the turn is a heartbeat rather than a person typing.
    assert any(line.strip() == "export HEARTBEAT=1" for line in _code_lines())


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not on PATH")
def test_script_parses() -> None:
    completed = subprocess.run(
        ["bash", "-n", str(SCRIPT_PATH)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not on PATH")
def test_dry_run_shows_the_prompt_and_the_workspace_flag(tmp_path: Path) -> None:
    # The dry run needs neither agy nor bun nor jq: --dry-run without --date
    # skips the schedule, the desire tick and the interoception probe. Copying
    # the script keeps its .autonomous-logs/ and its warnings out of the repo.
    script = tmp_path / "autonomous-action.sh"
    script.write_bytes(SCRIPT_PATH.read_bytes())
    env = {**os.environ, "HOME": str(tmp_path)}
    completed = subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "自律行動タイム（Heartbeat）" in completed.stdout
    assert "@SOUL.md" in completed.stdout
    assert f"--add-dir {tmp_path}" in completed.stdout
    assert "--dangerously-skip-permissions" in completed.stdout
    assert "--output-format json" in completed.stdout
    # The missing prompt files are named, on stderr, and do not abort the run.
    assert "WARN: SOUL.md not found" in completed.stderr
