from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import doctor
from scripts.doctor import CheckResult, CheckStatus

GATE_COMMAND = (
    "uv run --directory .. --package kernel-mcp efpf-agy-hook pre-tool-use"
)


def test_json_output_has_stable_schema(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        doctor,
        "run_doctor",
        lambda *_args, **_kwargs: [
            CheckResult(CheckStatus.OK, "python", "3.13.5"),
            CheckResult(
                CheckStatus.WARN,
                "tts:playback",
                "no player",
                "Install mpv.",
            ),
        ],
    )

    exit_code = doctor.main(["--json"])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report == {
        "schema_version": 1,
        "platform": doctor.platform.system().lower(),
        "summary": {"ok": 1, "warn": 1, "error": 0},
        "checks": [
            {
                "status": "ok",
                "subject": "python",
                "detail": "3.13.5",
                "remediation": None,
            },
            {
                "status": "warn",
                "subject": "tts:playback",
                "detail": "no player",
                "remediation": "Install mpv.",
            },
        ],
    }


def test_json_output_returns_one_when_any_check_is_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        doctor,
        "run_doctor",
        lambda *_args, **_kwargs: [
            CheckResult(CheckStatus.ERROR, "config:file", "missing"),
        ],
    )

    assert doctor.main(["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["summary"]["error"] == 1


def test_main_reads_agy_settings_from_the_override_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    override = tmp_path / "settings.json"
    seen: list[Path | None] = []

    def fake_run_doctor(*_args, settings_path=None, **_kwargs):
        seen.append(settings_path)
        return [CheckResult(CheckStatus.OK, "python", "3.13.5")]

    monkeypatch.setattr(doctor, "run_doctor", fake_run_doctor)
    monkeypatch.setenv("AGY_CLI_SETTINGS_PATH", str(override))

    assert doctor.main(["--json"]) == 0
    capsys.readouterr()
    assert seen == [override]


def test_live_checks_delegate_to_the_isolated_mcp_probe(
    tmp_path: Path,
) -> None:
    (tmp_path / ".agents").mkdir()
    config_path = tmp_path / ".agents" / "mcp_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "memory": {
                        "command": "uv",
                        "args": [
                            "run",
                            "--package",
                            "memory-mcp",
                            "memory-mcp",
                        ],
                        "env": {"MEMORY_EMBEDDING_MODEL": "fixture/model"},
                    }
                }
            }
        )
    )
    calls: list[list[str]] = []

    def runner(command, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "ok": True,
                    "server": "memory",
                    "tool_count": 31,
                    "remember_roundtrip": True,
                }
            ),
            "",
        )

    results = doctor.run_live_checks(
        tmp_path,
        config_path,
        tmp_path / "state",
        runner=runner,
    )

    assert len(results) == 1
    assert results[0].status is CheckStatus.OK
    assert "31 tools" in results[0].detail
    assert "--remember-roundtrip" in calls[0]


def _repo_with_hooks(tmp_path: Path, hooks: dict | None = None) -> Path:
    """A checkout as git delivers it: the workspace hooks, no .agents/mcp_config.json."""
    root = tmp_path / "repo"
    (root / ".agents").mkdir(parents=True)
    document = hooks or {
        "embodied-agy-efpf": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": GATE_COMMAND, "timeout": 5}
                    ],
                }
            ]
        }
    }
    (root / ".agents" / "hooks.json").write_text(json.dumps(document), encoding="utf-8")
    return root


def test_hook_gate_check_names_the_deny_when_mcp_config_is_missing(
    tmp_path: Path,
) -> None:
    root = _repo_with_hooks(tmp_path)
    config_path = root / ".agents" / "mcp_config.json"

    result = doctor.check_hook_gate(root, None, config_path)

    assert result is not None
    assert result.status is CheckStatus.ERROR
    assert result.subject == "hooks:gate"
    assert "active once the folder is trusted (or --add-dir is passed)" in result.detail
    assert "denied" in result.detail
    assert "setup.sh" in (result.remediation or "")


def test_hook_gate_check_passes_when_kernel_is_configured(
    tmp_path: Path,
) -> None:
    root = _repo_with_hooks(tmp_path)
    config = {"mcpServers": {"kernel": {"command": "uv"}}}
    config_path = root / ".agents" / "mcp_config.json"

    result = doctor.check_hook_gate(root, config, config_path)

    assert result is not None
    assert result.status is CheckStatus.OK

    missing_kernel = doctor.check_hook_gate(
        root, {"mcpServers": {"memory": {}}}, config_path
    )
    assert missing_kernel is not None
    assert missing_kernel.status is CheckStatus.ERROR


def test_hook_gate_check_is_silent_without_a_committed_pre_tool_use_hook(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".agents" / "mcp_config.json"
    assert doctor.check_hook_gate(tmp_path, None, config_path) is None

    # A PreToolUse hook that is not the kernel gate does not deny anything.
    other = _repo_with_hooks(
        tmp_path / "other",
        {
            "senses": {
                "PreToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [{"type": "command", "command": "bash ./hooks/x.sh"}],
                    }
                ]
            }
        },
    )
    assert doctor.check_hook_gate(other, None, other / ".agents" / "mcp_config.json") is None


def test_hook_gate_check_ignores_a_disabled_hook_group(tmp_path: Path) -> None:
    root = _repo_with_hooks(
        tmp_path,
        {
            "parked": {
                "enabled": False,
                "PreToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [{"type": "command", "command": GATE_COMMAND}],
                    }
                ],
            }
        },
    )

    assert doctor.check_hook_gate(root, None, root / ".agents" / "mcp_config.json") is None


def test_hook_gate_check_reads_the_committed_hooks_file() -> None:
    # The real .agents/hooks.json must be recognised as the gate, or the
    # diagnostic goes silent exactly where it matters.
    repo_root = Path(__file__).parents[1]
    result = doctor.check_hook_gate(
        repo_root,
        {"mcpServers": {"kernel": {"command": "uv"}}},
        repo_root / ".agents" / "mcp_config.json",
    )

    assert result is not None
    assert result.status is CheckStatus.OK
