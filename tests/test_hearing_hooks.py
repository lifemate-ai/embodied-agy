"""The shell hooks under ``.agents/hooks`` are plain bash + embedded Python.

Two things are pinned here:

* The Antigravity CLI hook protocol (docs/antigravity.md): hooks run with
  ``.agents/`` as the working directory, read one JSON object on stdin, take the
  prompt / last assistant message from ``transcriptPath`` (the payload carries
  neither), and answer ``{"injectSteps": [...]}`` on PreInvocation or
  ``{"decision": "continue", ...}`` / ``{}`` on Stop.
* The Git Bash portability fixes of the hearing hooks (#139): no ``/tmp`` literal
  inside Python, a probed interpreter instead of a bare ``python3``, and a
  ``tasklist`` fallback for PID liveness. They cannot regress quietly on a
  POSIX-only machine, so they are checked as text.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
AGENTS = ROOT / ".agents"
HOOKS = AGENTS / "hooks"
LIB = "agy-hook-lib.sh"
SCRIPTS = ("hearing-hook.sh", "hearing-stop-hook.sh")
ALL_SHELL = sorted(p.name for p in HOOKS.glob("*.sh"))


def _read(name: str) -> str:
    return (HOOKS / name).read_text(encoding="utf-8")


def _python_heredocs(script: str) -> list[str]:
    """Return the bodies of every ``<<'PYEOF' ... PYEOF`` block in the script."""
    blocks = re.findall(r"<<'PYEOF'.*?\n(.*?)\nPYEOF", script, flags=re.DOTALL)
    assert blocks, "expected at least one embedded Python heredoc"
    return blocks


def _transcript_line(**step: object) -> str:
    return json.dumps(step, ensure_ascii=False)


def _write_transcript(path: Path, prompt: str, assistant: str | None) -> Path:
    """A transcript_full.jsonl the way agy 1.1.25 writes it: the prompt wrapped in
    <USER_REQUEST> plus trailing system blocks, tool-call steps without content,
    one junk line, then the final assistant message."""
    lines = [
        _transcript_line(
            step_index=0,
            source="USER_EXPLICIT",
            type="USER_INPUT",
            content=(
                f"<USER_REQUEST>\n{prompt}\n</USER_REQUEST>\n"
                "<ADDITIONAL_METADATA>\nThe current local time is: 2026-09-03T21:46:38+09:00.\n"
                "</ADDITIONAL_METADATA>\n<USER_SETTINGS_CHANGE>\nignored\n</USER_SETTINGS_CHANGE>"
            ),
        ),
        _transcript_line(
            step_index=1,
            source="MODEL",
            type="PLANNER_RESPONSE",
            tool_calls=[{"name": "run_command", "args": {"CommandLine": "true"}}],
        ),
        "this line is not json",
        _transcript_line(
            step_index=2, source="MODEL", type="GENERIC", content="Created At: x\nok"
        ),
    ]
    if assistant is not None:
        lines.append(
            _transcript_line(
                step_index=3, source="MODEL", type="PLANNER_RESPONSE", content=assistant
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _payload(transcript: Path, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "conversationId": "test-conversation",
        "workspacePaths": [],
        "transcriptPath": str(transcript),
        "artifactDirectoryPath": str(transcript.parent),
        "modelName": "gemini-test",
    }
    base.update(extra)
    return base


def _run_hook(
    name: str, payload: dict[str, object], **env: str
) -> subprocess.CompletedProcess[str]:
    """Run a hook the way agy does: ``bash ./hooks/<name>`` from ``.agents/`` with the
    event JSON on stdin. Environment is inherited plus the given overrides."""
    full_env = {**os.environ, **env}
    return subprocess.run(
        ["bash", f"./hooks/{name}"],
        cwd=AGENTS,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
        timeout=60,
        check=False,
    )


def _json_stdout(proc: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, (
        f"expected exactly one JSON line on stdout, got {proc.stdout!r}"
    )
    return json.loads(lines[0])


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    return _write_transcript(
        tmp_path / "transcript_full.jsonl",
        'こんにちは "世界"\n二行目',
        "作業中 [CONTINUE: 続きをやる]",
    )


# --------------------------------------------------------------------------- text checks


@pytest.mark.parametrize("name", ALL_SHELL)
def test_every_shell_hook_parses(name: str) -> None:
    proc = subprocess.run(
        ["bash", "-n", str(HOOKS / name)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", SCRIPTS)
def test_embedded_python_never_hardcodes_tmp(name: str) -> None:
    """Python's Path("/tmp/...") resolves to the current drive on Windows, while the
    shell's /tmp is the MSYS temp dir. The location has to come from the shell via
    HEARING_DIR, with tempfile.gettempdir() as the stand-alone fallback."""
    script = _read(name)
    for body in _python_heredocs(script):
        assert '"/tmp/' not in body, name
        assert "'/tmp/" not in body, name
        assert 'os.environ.get("HEARING_DIR") or tempfile.gettempdir()' in body, name
    # Shell side resolves the directory exactly once and exports it for Python.
    assert 'HEARING_DIR="${HEARING_DIR:-${TMPDIR:-/tmp}}"' in script, name
    assert "export HEARING_DIR" in script, name
    # No shell-level literal either (PID/offset/timing/context files all live under it).
    for line in script.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert not re.search(r"(?<![\w{:-])/tmp/", line), (name, line)


def test_library_python_never_hardcodes_tmp() -> None:
    """The shared library is sourced by every hook, so it must obey the same rule:
    paths reach Python through the environment, never as a literal."""
    lib = _read(LIB)
    for line in lib.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert "/tmp/" not in line, line
    assert "export PYTHONUTF8=1" in lib


@pytest.mark.parametrize("name", SCRIPTS)
def test_interpreter_is_probed_not_assumed(name: str) -> None:
    """`python3` may be the Microsoft Store alias (exits 49 without running anything).
    The probe lives in agy-hook-lib.sh: honour HEARING_PYTHON / AGY_HOOK_PYTHON,
    otherwise try python3 then python and keep the first that actually executes
    `import sys`; none -> the hook answers its empty JSON and exits 0."""
    lib = _read(LIB)
    assert "agy_find_python()" in lib
    assert "HEARING_PYTHON" in lib
    assert "AGY_HOOK_PYTHON" in lib
    assert "for candidate in python3 python; do" in lib
    assert '"$candidate" -c "import sys"' in lib

    script = _read(name)
    assert '. "$(dirname "$0")/agy-hook-lib.sh"' in script, name
    assert re.search(
        r"^agy_require_python \|\| \w+_exit$", script, flags=re.MULTILINE
    ), name
    assert 'PY="$AGY_HOOK_PY"' in script, name
    # Every remaining interpreter call goes through $PY, never a bare python3.
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "for candidate in" in stripped:
            continue
        assert not re.match(r"^\w+=\$\(python3? ", stripped), (name, line)
        assert not stripped.startswith("python3 -"), (name, line)


@pytest.mark.parametrize("name", SCRIPTS)
def test_daemon_liveness_falls_back_to_tasklist(name: str) -> None:
    """MSYS `kill -0` only sees MSYS processes; a daemon started as a native Windows
    process looks dead. pid_alive() asks tasklist when kill -0 fails."""
    script = _read(name)
    assert "pid_alive()" in script, name
    assert 'kill -0 "$1" 2>/dev/null && return 0' in script, name
    assert 'tasklist /FI "PID eq $1"' in script, name
    # Git Bash rewrites "/FI" into a Windows path unless conversion is disabled.
    assert "MSYS_NO_PATHCONV=1" in script, name
    assert 'pid_alive "$PID"' in script, name
    assert 'kill -0 "$PID"' not in script, name


def test_stop_hook_separates_library_dir_from_buffer_dir() -> None:
    """HEARING_DIR is where the buffer lives; the hearing library handed to
    `uv run --directory` is HEARING_LIB_DIR. The two used to share one name."""
    script = _read("hearing-stop-hook.sh")
    assert '--directory "$HEARING_LIB_DIR"' in script
    assert '--directory "$HEARING_DIR"' not in script


def test_stop_hook_documents_its_timeout_budget() -> None:
    """A Stop hook registered with the core hooks' timeout of 10 is killed mid-wait
    and never extends a turn, silently. The header and the docs both say >= 30 s,
    and the docs point at the agy registration shape (.agents/hooks.json)."""
    script = _read("hearing-stop-hook.sh")
    header = "\n".join(
        line for line in script.splitlines()[:50] if line.startswith("#")
    )
    assert "30" in header
    assert ".agents/hooks.json" in header
    assert '"decision": "continue"' in header
    doc = (ROOT / "docs" / "hearing-hooks.md").read_text(encoding="utf-8")
    assert '"timeout": 30' in doc
    assert "HEARING_PYTHON" in doc
    assert "HEARING_DIR" in doc
    assert "bash.exe" in doc
    assert ".agents/hooks.json" in doc
    assert "docs/antigravity.md" in doc
    assert "UserPromptSubmit" not in doc


def test_no_claude_code_protocol_left_in_hooks() -> None:
    """The port is complete only if no hook still speaks the Claude Code protocol:
    no `.prompt` / `.last_assistant_message` payload reads, no `decision: block`."""
    for name in ALL_SHELL:
        code = "\n".join(
            line
            for line in _read(name).splitlines()
            if not line.lstrip().startswith("#")
        )
        assert '"decision": "block"' not in code, name
        assert 'decision\\": \\"block' not in code, name
        assert ".last_assistant_message" not in code, name
        assert "jq -r '.prompt" not in code, name
        assert 'get("prompt")' not in code, name
        assert "get('prompt'" not in code, name


# --------------------------------------------------------------------------- the library


def test_library_reads_prompt_and_last_assistant_from_transcript(
    transcript: Path,
) -> None:
    """The prompt is the inside of <USER_REQUEST>, without the trailing metadata
    blocks; the last assistant message is the last MODEL/PLANNER_RESPONSE that has
    content (tool-call steps and junk lines are skipped)."""
    script = (
        ". ./hooks/agy-hook-lib.sh; agy_read_stdin;"
        ' printf "%s\\n---\\n%s\\n---\\n%s\\n" "$(agy_invocation_num)" "$(agy_user_prompt)" "$(agy_last_assistant_message)"'
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        cwd=AGENTS,
        input=json.dumps(_payload(transcript, invocationNum=0)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert (
        proc.stdout
        == '0\n---\nこんにちは "世界"\n二行目\n---\n作業中 [CONTINUE: 続きをやる]\n'
    )


def test_library_tolerates_missing_transcript_and_missing_python(
    tmp_path: Path,
) -> None:
    """A hook that cannot read the transcript must still answer valid JSON, and the
    emitters must not depend on Python being present."""
    script = (
        ". ./hooks/agy-hook-lib.sh; agy_read_stdin;"
        ' printf "[%s]\\n" "$(agy_user_prompt)";'
        ' AGY_HOOK_PYTHON=/nonexistent/python agy_emit_context "a \\"b\\"\nc"'
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        cwd=AGENTS,
        input=json.dumps(_payload(tmp_path / "nonexistent.jsonl", invocationNum=0)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            k: v
            for k, v in os.environ.items()
            if k not in ("AGY_HOOK_PYTHON", "HEARING_PYTHON")
        },
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    first, second = [line for line in proc.stdout.splitlines() if line]
    assert first == "[]"
    assert json.loads(second) == {"injectSteps": [{"ephemeralMessage": 'a "b"\nc'}]}


# --------------------------------------------------------------------------- PreInvocation hooks


def test_interoception_first_invocation_injects_ephemeral_message(
    transcript: Path, tmp_path: Path
) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "now": {
                    "ts": "2026-09-03T21:00:00+0900",
                    "phase": "night",
                    "arousal": 12,
                    "thermal": 40.5,
                    "mem_free": 70,
                    "uptime_min": 100,
                },
                "window": [{"arousal": 10}, {"arousal": 11}, {"arousal": 12}],
                "trend": {"arousal": "rising", "mem_free": "stable"},
            }
        ),
        encoding="utf-8",
    )
    out = _json_stdout(
        _run_hook(
            "interoception.sh",
            _payload(transcript, invocationNum=0),
            INTEROCEPTION_STATE_FILE=str(state),
        )
    )
    steps = out["injectSteps"]
    assert len(steps) == 1
    message = steps[0]["ephemeralMessage"]
    assert message.startswith(
        "[interoception] time=21:00:00 day=Thu phase=night arousal=12%(↑)"
    )
    assert "heartbeats=3" in message


def test_interoception_without_state_file_still_injects(
    transcript: Path, tmp_path: Path
) -> None:
    out = _json_stdout(
        _run_hook(
            "interoception.sh",
            _payload(transcript, invocationNum=0),
            INTEROCEPTION_STATE_FILE=str(tmp_path / "missing.json"),
        )
    )
    message = out["injectSteps"][0]["ephemeralMessage"]
    assert message.startswith("[interoception] time=")
    assert "heartbeat daemon not running" in message


def test_interoception_later_invocation_emits_no_context(transcript: Path) -> None:
    """PreInvocation fires before every model call in a turn; the per-turn hooks
    act only on invocationNum == 0 and answer an empty injectSteps otherwise."""
    out = _json_stdout(
        _run_hook("interoception.sh", _payload(transcript, invocationNum=1))
    )
    assert out == {"injectSteps": []}


def test_post_compact_recovery_emits_ephemeral_message(transcript: Path) -> None:
    out = _json_stdout(
        _run_hook("post-compact-recovery.sh", _payload(transcript, invocationNum=0))
    )
    message = out["injectSteps"][0]["ephemeralMessage"]
    assert message.startswith("[コンパクションが実行されました")
    assert "/recover-from-compact" in message
    later = _json_stdout(
        _run_hook("post-compact-recovery.sh", _payload(transcript, invocationNum=2))
    )
    assert later == {"injectSteps": []}


def test_auto_recall_skips_autonomous_prompts_and_unreachable_memory(
    tmp_path: Path,
) -> None:
    skip = _write_transcript(
        tmp_path / "skip.jsonl", "今日は好きなことをいっぱいして", None
    )
    out = _json_stdout(
        _run_hook(
            "auto-recall.sh", _payload(skip, invocationNum=0), MEMORY_HTTP_PORT="1"
        )
    )
    assert out == {"injectSteps": []}
    normal = _write_transcript(
        tmp_path / "normal.jsonl", "昨日の夜景のことを覚えてる？", None
    )
    out = _json_stdout(
        _run_hook(
            "auto-recall.sh", _payload(normal, invocationNum=0), MEMORY_HTTP_PORT="1"
        )
    )
    assert out == {"injectSteps": []}


def test_auto_social_without_database_emits_no_context(
    transcript: Path, tmp_path: Path
) -> None:
    out = _json_stdout(
        _run_hook(
            "auto-social.sh", _payload(transcript, invocationNum=0), HOME=str(tmp_path)
        )
    )
    assert out == {"injectSteps": []}
    script = _read("auto-social.sh")
    assert '"$HOME/.gemini/sociality/social.db"' in script
    assert "${COMPANION_ID:-kouta}" in script


def test_hearing_hook_without_daemon_saves_prompt_and_emits_no_context(
    transcript: Path, tmp_path: Path
) -> None:
    hearing_dir = tmp_path / "hearing"
    hearing_dir.mkdir()
    out = _json_stdout(
        _run_hook(
            "hearing-hook.sh",
            _payload(transcript, invocationNum=0),
            HEARING_DIR=str(hearing_dir),
        )
    )
    assert out == {"injectSteps": []}
    saved = (hearing_dir / "hearing_user_prompt.txt").read_text(encoding="utf-8")
    assert saved == 'こんにちは "世界"\n二行目'
    later = _json_stdout(
        _run_hook(
            "hearing-hook.sh",
            _payload(transcript, invocationNum=1),
            HEARING_DIR=str(hearing_dir),
        )
    )
    assert later == {"injectSteps": []}


# --------------------------------------------------------------------------- Stop hooks


def test_continue_check_continues_on_continue_marker(
    transcript: Path, tmp_path: Path
) -> None:
    counter = tmp_path / "counter"
    log = tmp_path / "continue.log"
    env = {
        "HEARTBEAT": "1",
        "HEARTBEAT_CONTINUE_COUNTER": str(counter),
        "HEARTBEAT_CONTINUE_LOG": str(log),
        "MAX_CONTINUES": "2",
    }
    payload = _payload(
        transcript,
        executionNum=0,
        terminationReason="NO_TOOL_CALL",
        error="",
        fullyIdle=True,
    )

    out = _json_stdout(_run_hook("continue-check.sh", payload, **env))
    assert out["decision"] == "continue"
    assert out["reason"].endswith("続きをやる")
    assert "チェイン1/2" in out["reason"]
    assert counter.read_text().strip() == "1"
    assert "CONTINUE (chain=1/2)" in log.read_text(encoding="utf-8")

    out = _json_stdout(_run_hook("continue-check.sh", payload, **env))
    assert out["decision"] == "continue"
    assert counter.read_text().strip() == "2"

    # MAX_CONTINUES reached: let the agent stop and reset the chain.
    out = _json_stdout(_run_hook("continue-check.sh", payload, **env))
    assert out == {}
    assert not counter.exists()
    assert "MAX_REACHED" in log.read_text(encoding="utf-8")


def test_continue_check_emits_empty_when_done_or_interactive(tmp_path: Path) -> None:
    done = _write_transcript(tmp_path / "done.jsonl", "ok", "終わり [DONE]")
    env = {
        "HEARTBEAT": "1",
        "HEARTBEAT_CONTINUE_COUNTER": str(tmp_path / "counter"),
        "HEARTBEAT_CONTINUE_LOG": str(tmp_path / "log"),
    }
    assert _json_stdout(_run_hook("continue-check.sh", _payload(done), **env)) == {}
    # No HEARTBEAT: an interactive session, never extended.
    pending = _write_transcript(tmp_path / "pending.jsonl", "ok", "[CONTINUE: x]")
    interactive = {k: v for k, v in os.environ.items() if k != "HEARTBEAT"}
    proc = subprocess.run(
        ["bash", "./hooks/continue-check.sh"],
        cwd=AGENTS,
        input=json.dumps(_payload(pending)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=interactive,
        check=False,
    )
    assert _json_stdout(proc) == {}


def test_hearing_stop_hook_without_daemon_emits_empty_and_saves_context(
    transcript: Path, tmp_path: Path
) -> None:
    hearing_dir = tmp_path / "hearing"
    hearing_dir.mkdir()
    payload = _payload(
        transcript,
        executionNum=0,
        terminationReason="NO_TOOL_CALL",
        error="",
        fullyIdle=True,
    )
    out = _json_stdout(
        _run_hook(
            "hearing-stop-hook.sh",
            payload,
            HEARING_DIR=str(hearing_dir),
            MCP_BEHAVIOR_TOML=str(tmp_path / "no-such.toml"),
        )
    )
    assert out == {}
    context = json.loads(
        (hearing_dir / "hearing_context.json").read_text(encoding="utf-8")
    )
    assert context["conversationId"] == "test-conversation"
    assert context["last_assistant_message"] == "作業中 [CONTINUE: 続きをやる]"


def test_hearing_stop_hook_continues_when_speech_arrives(
    transcript: Path, tmp_path: Path
) -> None:
    """With a live daemon PID and a buffered utterance the stop hook answers
    decision: continue (Claude Code's block) carrying the [hearing] line."""
    hearing_dir = tmp_path / "hearing"
    hearing_dir.mkdir()
    daemon = subprocess.Popen(["sleep", "30"])
    try:
        (hearing_dir / "hearing-daemon.pid").write_text(str(daemon.pid))
        (hearing_dir / "hearing_buffer.jsonl").write_text(
            json.dumps(
                {
                    "ts": "2026-09-03T21:00:11",
                    "text": "聞こえてる？",
                    "no_speech_prob": 0.1,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        payload = _payload(
            transcript,
            executionNum=0,
            terminationReason="NO_TOOL_CALL",
            error="",
            fullyIdle=True,
        )
        out = _json_stdout(
            _run_hook(
                "hearing-stop-hook.sh",
                payload,
                HEARING_DIR=str(hearing_dir),
                MCP_BEHAVIOR_TOML=str(tmp_path / "no-such.toml"),
                HEARING_WAIT_SECONDS="0",
                HEARING_RETRY_WAIT="0",
                HEARING_GUARANTEED_SLEEP="0",
            )
        )
    finally:
        daemon.kill()
        daemon.wait()
    assert out["decision"] == "continue"
    assert (
        "[hearing] chunks=1 span=21:00:11~21:00:11 text=聞こえてる？" in out["reason"]
    )
    assert "チェイン(1/20)" in out["reason"]
    assert (hearing_dir / "hearing-stop-counter").read_text().strip() == "1"
