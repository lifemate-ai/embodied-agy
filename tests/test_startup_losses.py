"""Four things headless startup used to lose without a word (#140).

Each of these fails at the configuration layer and looks fine at the execution
layer: the heartbeat completes, the log reads normally, and only the absence
is missing. Interactive use mostly catches them because a person is watching;
`agy -p` has nobody watching.

Antigravity CLI has no per-server approval list, so the first item is now
workspace trust: an interactive session loads `.agents/` (the kernel hooks and
the servers setup wrote) only for a folder in `trustedWorkspaces`, while
`agy -p --add-dir` loads it regardless (docs/antigravity.md).
"""

from __future__ import annotations

import json
import re
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from scripts import doctor
from scripts.doctor import CheckResult, CheckStatus
from scripts.onboarding import CORE_SERVER_NAMES, FeatureSelection
from scripts.setup import execute_setup
from scripts.setup_io import ConfigConflictError, trust_workspace

ROOT = Path(__file__).parents[1]
SCRIPT = (ROOT / "autonomous-action.sample.sh").read_text(encoding="utf-8")
CLI_SETTINGS = Path(".gemini") / "antigravity-cli" / "settings.json"


# --- 1. interactive agy loads .agents/ only for a trusted folder -----------


def test_trust_creates_the_settings_file_with_only_the_workspace_list(
    tmp_path: Path,
) -> None:
    settings = tmp_path / CLI_SETTINGS
    repo = tmp_path / "repo"
    repo.mkdir()

    assert trust_workspace(settings, repo) is True

    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "trustedWorkspaces": [str(repo.resolve())]
    }


def test_trust_preserves_other_keys_and_existing_entries(tmp_path: Path) -> None:
    # agy keeps its own preferences in this file; losing them would trade one
    # silent startup loss for another.
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "colorScheme": "dark",
                "trustedWorkspaces": ["/somewhere/else"],
                "verbosity": "normal",
            }
        ),
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    assert trust_workspace(settings, repo) is True

    loaded = json.loads(settings.read_text(encoding="utf-8"))
    assert loaded["colorScheme"] == "dark"
    assert loaded["verbosity"] == "normal"
    # Appended, not replaced: the other entries are the user's other projects.
    assert loaded["trustedWorkspaces"] == ["/somewhere/else", str(repo.resolve())]


def test_trust_is_idempotent_and_leaves_a_current_file_alone(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = tmp_path / "settings.json"
    # An unresolved spelling of the same folder still counts as trusted.
    settings.write_text(
        json.dumps({"trustedWorkspaces": [str(tmp_path / "." / "repo")]}) + "\n",
        encoding="utf-8",
    )
    before = settings.read_text(encoding="utf-8")

    assert trust_workspace(settings, repo) is False
    assert settings.read_text(encoding="utf-8") == before


def test_trust_refuses_to_overwrite_unreadable_settings(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigConflictError, match="not valid JSON"):
        trust_workspace(settings, tmp_path)
    assert settings.read_text(encoding="utf-8") == "{not json"


def test_trust_refuses_a_workspace_list_that_is_not_a_list(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text('{"trustedWorkspaces": "/only/one"}', encoding="utf-8")

    with pytest.raises(ConfigConflictError, match="trustedWorkspaces"):
        trust_workspace(settings, tmp_path)


def _fixture_workspace(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.1.0"\n'
        'dependencies = ["memory-mcp", "desire-system", "sociality-mcp", '
        '"kernel-mcp"]\n'
    )
    (root / "uv.lock").write_text("version = 1\n")
    policy = root / "examples" / "configs" / "socialPolicy.example.toml"
    policy.parent.mkdir(parents=True)
    policy.write_text('version = 1\nname = "fixture"\n')


def _run_setup(
    root: Path,
    *,
    trust: bool,
    output: StringIO,
    dry_run: bool = False,
) -> int:
    return execute_setup(
        FeatureSelection(),
        {},
        repo_root=root,
        home=root / "home",
        dry_run=dry_run,
        force=False,
        skip_model_download=True,
        trust=trust,
        runner=lambda command, **_k: subprocess.CompletedProcess(command, 0, "", ""),
        doctor=lambda *_a, **_k: [CheckResult(CheckStatus.OK, "fixture", "ready")],
        output=output,
    )


def test_setup_trusts_exactly_this_repository_when_asked(tmp_path: Path) -> None:
    _fixture_workspace(tmp_path)
    output = StringIO()

    assert _run_setup(tmp_path, trust=True, output=output) == 0

    written = json.loads(
        (tmp_path / ".agents" / "mcp_config.json").read_text(encoding="utf-8")
    )["mcpServers"]
    assert list(written) == list(CORE_SERVER_NAMES)
    settings = tmp_path / "home" / CLI_SETTINGS
    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "trustedWorkspaces": [str(tmp_path.resolve())]
    }
    assert "==> trusted" in output.getvalue()


def test_setup_only_points_at_the_trust_prompt_by_default(tmp_path: Path) -> None:
    # Trust is a per-user decision agy asks about itself; setup does not make
    # it silently, it says how to make it.
    _fixture_workspace(tmp_path)
    output = StringIO()

    assert _run_setup(tmp_path, trust=False, output=output) == 0

    assert not (tmp_path / "home" / ".gemini").exists()
    assert "--trust-workspace" in output.getvalue()
    assert "trust this folder when agy asks" in output.getvalue()


def test_setup_hands_the_settings_path_to_doctor(tmp_path: Path) -> None:
    _fixture_workspace(tmp_path)
    settings = tmp_path / "elsewhere" / "settings.json"
    seen: list[Path | None] = []

    def fake_doctor(*_args, settings_path=None, **_kwargs):
        seen.append(settings_path)
        return [CheckResult(CheckStatus.OK, "fixture", "ready")]

    result = execute_setup(
        FeatureSelection(),
        {},
        repo_root=tmp_path,
        home=tmp_path / "home",
        dry_run=False,
        force=False,
        skip_model_download=True,
        trust=True,
        settings_path=settings,
        runner=lambda command, **_k: subprocess.CompletedProcess(command, 0, "", ""),
        doctor=fake_doctor,
        output=StringIO(),
    )

    assert result == 0
    assert seen == [settings]
    assert json.loads(settings.read_text(encoding="utf-8"))["trustedWorkspaces"] == [
        str(tmp_path.resolve())
    ]
    assert not (tmp_path / "home").exists()


def test_dry_run_does_not_touch_agy_settings(tmp_path: Path) -> None:
    _fixture_workspace(tmp_path)

    _run_setup(tmp_path, trust=True, output=StringIO(), dry_run=True)

    assert not (tmp_path / "home").exists()
    assert not (tmp_path / ".agents").exists()


def test_no_per_machine_approval_file_is_left_in_the_repository() -> None:
    # Claude Code kept the headless approval in a per-machine settings file
    # inside the checkout and ignored it; agy keeps trust outside the
    # repository, so only the generated config and its backups are ignored
    # under .agents/.
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".agents/mcp_config.json" in ignored
    assert ".agents/mcp_config.json.backup-*" in ignored
    assert not any(".claude" in line for line in ignored)


def _settings(tmp_path: Path, trusted: object) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"trustedWorkspaces": trusted, "verbosity": "normal"}),
        encoding="utf-8",
    )
    return path


def test_doctor_warns_when_the_repository_is_not_trusted(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = _settings(tmp_path, ["/somewhere/else"])

    result = doctor.check_workspace_trust(repo, settings)

    assert result.status is CheckStatus.WARN
    assert result.subject == "workspace:trust"
    assert "interactive agy sessions will not load .agents/" in result.detail
    assert "accept the trust prompt" in result.remediation
    assert "--trust-workspace" in result.remediation
    assert "`agy -p --add-dir` is unaffected" in result.remediation


def test_doctor_warns_when_agy_has_no_settings_file_yet(tmp_path: Path) -> None:
    result = doctor.check_workspace_trust(
        tmp_path, tmp_path / "missing" / "settings.json"
    )

    assert result.status is CheckStatus.WARN
    assert "does not exist" in result.detail
    assert "--trust-workspace" in result.remediation


def test_doctor_is_satisfied_by_a_trusted_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = _settings(tmp_path, ["/somewhere/else", str(repo)])

    result = doctor.check_workspace_trust(repo, settings)

    assert result.status is CheckStatus.OK
    assert "interactive sessions load .agents/" in result.detail


def test_doctor_does_not_assume_a_trusted_parent_covers_the_repository(
    tmp_path: Path,
) -> None:
    # Whether agy extends trust to sub-folders was not measured, so the check
    # asks for the root itself rather than guessing.
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = _settings(tmp_path, [str(tmp_path)])

    assert doctor.check_workspace_trust(repo, settings).status is CheckStatus.WARN


def test_doctor_reports_unreadable_settings_instead_of_raising(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{not json", encoding="utf-8")

    result = doctor.check_workspace_trust(tmp_path, settings)

    assert result.status is CheckStatus.WARN
    assert "not readable JSON" in result.detail


def test_settings_path_honours_the_test_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"

    monkeypatch.delenv("AGY_CLI_SETTINGS_PATH", raising=False)
    assert doctor.cli_settings_path(home) == home / CLI_SETTINGS

    override = tmp_path / "override.json"
    monkeypatch.setenv("AGY_CLI_SETTINGS_PATH", str(override))
    assert doctor.cli_settings_path(home) == override
    assert doctor.cli_settings_path(home, {}) == home / CLI_SETTINGS


def test_full_doctor_run_reports_trust_against_the_given_settings(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.1.0"\ndependencies = []\n'
    )
    settings = _settings(tmp_path, [str(repo)])

    results = doctor.run_doctor(
        repo,
        repo / ".agents" / "mcp_config.json",
        tmp_path / "home",
        which=lambda _name: "/usr/bin/uv",
        runner=lambda command, **_k: subprocess.CompletedProcess(command, 0, "", ""),
        settings_path=settings,
    )

    trust = next(result for result in results if result.subject == "workspace:trust")
    assert trust.status is CheckStatus.OK
    subjects = [result.subject for result in results]
    assert subjects.index("workspace:trust") < subjects.index("config:file")


# --- 2. memory HTTP recall port -------------------------------------------


def test_doctor_warns_when_the_recall_port_is_closed() -> None:
    result = doctor.check_memory_http_port({}, is_listening=lambda _h, _p: False)

    assert result.status is CheckStatus.WARN
    assert result.detail == (
        "memory HTTP recall port 18900 is not listening; kernel ticks "
        "will carry no memory candidates"
    )


def test_doctor_probes_the_configured_recall_port() -> None:
    probed: list[tuple[str, int]] = []

    def listening(host: str, port: int) -> bool:
        probed.append((host, port))
        return True

    result = doctor.check_memory_http_port(
        {"MEMORY_HTTP_PORT": "18901"}, is_listening=listening
    )

    assert probed == [("127.0.0.1", 18901)]
    assert result.status is CheckStatus.OK


def test_doctor_really_connects_to_a_closed_port() -> None:
    import socket

    # Bind and release to find a port nothing is listening on right now.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    result = doctor.check_memory_http_port({"MEMORY_HTTP_PORT": str(port)})

    assert result.status is CheckStatus.WARN
    assert f"port {port} is not listening" in result.detail


# --- 3. @SOUL.md / @TODO.md / @ROUTINES.md --------------------------------


def test_script_checks_each_mentioned_file_before_building_the_prompt() -> None:
    check_at = SCRIPT.index("for PROMPT_FILE in SOUL.md TODO.md ROUTINES.md")
    prompt_at = SCRIPT.index('PROMPT="自律行動タイム')
    assert check_at < prompt_at

    for name in ("SOUL.md", "TODO.md", "ROUTINES.md"):
        assert f"@{name}" in SCRIPT
    assert re.search(r'WARN: \$PROMPT_FILE not found in \$SCRIPT_DIR', SCRIPT)
    assert ">&2" in SCRIPT[check_at:prompt_at]
    assert '>> "$LOG_FILE"' in SCRIPT[check_at:prompt_at]
    # Warn, do not abort: the heartbeat still runs on GEMINI.md alone.
    assert "exit" not in SCRIPT[check_at:prompt_at]


def test_templates_and_doc_exist_for_the_three_files() -> None:
    for name in ("SOUL", "TODO", "ROUTINES"):
        assert (ROOT / "examples" / f"{name}.sample.md").is_file()
    doc = (ROOT / "docs" / "autonomous-files.md").read_text(encoding="utf-8")
    for name in ("SOUL.md", "TODO.md", "ROUTINES.md"):
        assert name in doc


def test_doctor_warns_for_missing_files_once_the_script_is_installed(
    tmp_path: Path,
) -> None:
    (tmp_path / "SOUL.md").write_text("# me\n")

    [before] = doctor.check_autonomous_files(tmp_path)
    assert before.status is CheckStatus.OK
    assert "TODO.md, ROUTINES.md absent" in before.detail

    (tmp_path / "autonomous-action.sh").write_text("#!/bin/bash\n")
    after = doctor.check_autonomous_files(tmp_path)
    assert [(r.status, r.subject) for r in after] == [
        (CheckStatus.WARN, "autonomous:TODO.md"),
        (CheckStatus.WARN, "autonomous:ROUTINES.md"),
    ]
    assert "@TODO.md reference" in after[0].detail

    (tmp_path / "TODO.md").write_text("- [ ]\n")
    (tmp_path / "ROUTINES.md").write_text("|\n")
    [present] = doctor.check_autonomous_files(tmp_path)
    assert present.status is CheckStatus.OK


# --- 4. the example config no longer pins SOCIAL_DB_PATH -------------------


def test_example_does_not_pin_state_overrides() -> None:
    # agy has no --mcp-config, so the heartbeat loads the same
    # .agents/mcp_config.json via --add-dir; this example is the only shape.
    config = json.loads(
        (ROOT / ".agents" / "mcp_config.json.example").read_text(encoding="utf-8")
    )
    for server in config["mcpServers"].values():
        env = server.get("env", {})
        assert "SOCIAL_DB_PATH" not in env
        assert "MEMORY_HTTP_PORT" not in env
