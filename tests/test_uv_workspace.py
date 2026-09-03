from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
MEMBERS = {
    "consciousness-mcp/packages/kernel-mcp": "kernel-mcp",
    "desire-system": "desire-system",
    "memory-mcp": "memory-mcp",
    "sociality-mcp": "sociality-mcp",
    "sociality-mcp/packages/agent-grammar": "agent-grammar",
    "sociality-mcp/packages/boundary-mcp": "boundary-mcp",
    "sociality-mcp/packages/interaction-orchestrator-mcp": (
        "interaction-orchestrator-mcp"
    ),
    "sociality-mcp/packages/joint-attention-mcp": "joint-attention-mcp",
    "sociality-mcp/packages/relationship-mcp": "relationship-mcp",
    "sociality-mcp/packages/self-narrative-mcp": "self-narrative-mcp",
    "sociality-mcp/packages/social-core": "social-core",
    "sociality-mcp/packages/social-state-mcp": "social-state-mcp",
    "system-temperature-mcp": "system-temperature-mcp",
    "tts-mcp": "tts-mcp",
    "usb-webcam-mcp": "usb-webcam-mcp",
    "wifi-cam-mcp": "wifi-cam-mcp",
    "x-mcp": "x-mcp",
}


def _root_config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_root_declares_every_python_project() -> None:
    config = _root_config()
    assert set(config["tool"]["uv"]["workspace"]["members"]) == set(MEMBERS)
    assert config["project"]["requires-python"] == ">=3.13,<3.14"
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.13"


def test_root_dependencies_install_only_the_core_runtime() -> None:
    config = _root_config()
    dependency_names = {
        value.split("[", 1)[0].split("=", 1)[0]
        for value in config["project"]["dependencies"]
    }
    assert dependency_names == {
        "desire-system",
        "kernel-mcp",
        "memory-mcp",
        "sociality-mcp",
    }
    assert set(config["tool"]["uv"]["sources"]) == set(MEMBERS.values())
    assert all(
        source == {"workspace": True}
        for source in config["tool"]["uv"]["sources"].values()
    )


def test_root_extras_install_optional_capabilities_explicitly() -> None:
    extras = _root_config()["project"]["optional-dependencies"]

    assert extras["camera-usb"] == ["usb-webcam-mcp"]
    assert extras["camera-tapo"] == ["wifi-cam-mcp"]
    assert extras["transcription-whisper"] == ["wifi-cam-mcp[transcribe]"]
    assert extras["transcription-faster"] == ["wifi-cam-mcp[transcribe-faster]"]
    assert extras["voice-voicevox"] == ["tts-mcp"]
    assert extras["voice-elevenlabs"] == ["tts-mcp[elevenlabs]"]
    assert extras["x"] == ["x-mcp"]
    assert extras["system-temperature"] == ["system-temperature-mcp"]
    assert all("transcrib" not in item for item in extras["camera-tapo"])


def test_only_root_lock_and_python_pin_remain() -> None:
    nested_locks = [
        path.relative_to(ROOT)
        for path in ROOT.glob("**/uv.lock")
        if path.parent != ROOT and "tmp" not in path.parts
    ]
    nested_pins = [
        path.relative_to(ROOT)
        for path in ROOT.glob("**/.python-version")
        if path.parent != ROOT and "tmp" not in path.parts
    ]
    assert nested_locks == []
    assert nested_pins == []


def test_transcription_extra_requires_python_313_compatible_numba() -> None:
    config = tomllib.loads((ROOT / "wifi-cam-mcp" / "pyproject.toml").read_text(encoding="utf-8"))
    assert "numba>=0.63.1" in config["project"]["optional-dependencies"]["transcribe"]


def test_social_core_installs_iana_timezone_data_on_windows() -> None:
    config = tomllib.loads(
        (
            ROOT / "sociality-mcp" / "packages" / "social-core" / "pyproject.toml"
        ).read_text(encoding="utf-8")
    )

    assert 'tzdata>=2025.2; sys_platform == "win32"' in config["project"][
        "dependencies"
    ]


def test_installer_performs_one_workspace_sync() -> None:
    script = (ROOT / "scripts" / "install-mcps.sh").read_text(encoding="utf-8")
    sync_commands = re.findall(r"^[ \t]*uv sync.*$", script, flags=re.MULTILINE)
    assert sync_commands == ["uv sync --locked --all-extras --group dev"]
    assert "MCP_DIRS=" not in script
    assert "uv run --package memory-mcp python -c" in script


def test_setup_uses_one_cross_platform_workspace_entrypoint() -> None:
    wrapper = (ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    setup = (ROOT / "scripts" / "setup.py").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "uv run --no-project --python 3.13" in wrapper
    assert 'python scripts/setup.py "$@"' in wrapper
    assert "https://astral.sh/uv/install.sh" in wrapper
    assert '["uv", "sync", "--locked", "--no-dev"]' in setup
    assert "MCP_DIRS=" not in setup
    assert "--trust-workspace" in setup
    assert ".agents/mcp_config.json" in gitignore.splitlines()
    assert ".agents/mcp_config.json.backup-*" in gitignore.splitlines()


def test_mcp_example_runs_python_servers_from_workspace_packages() -> None:
    config = json.loads((ROOT / ".agents/mcp_config.json.example").read_text(encoding="utf-8"))
    expected = {
        "desire-system": ("desire-system", "desire-system"),
        "memory": ("memory-mcp", "memory-mcp"),
        "sociality": ("sociality-mcp", "sociality-mcp"),
        "kernel": ("kernel-mcp", "kernel-mcp"),
    }

    servers = config["mcpServers"]
    assert set(servers) == set(expected)
    for server_name, (package, entrypoint) in expected.items():
        assert servers[server_name]["command"] == "uv"
        assert servers[server_name]["args"] == [
            "run",
            "--package",
            package,
            entrypoint,
        ]


HOOK_FILES = (".agents/hooks.json", ".agents/hooks.example.json")
KERNEL_HOOK = "efpf-agy-hook"
KERNEL_EVENTS = {
    "PreToolUse": "pre-tool-use",
    "PostToolUse": "post-tool-use",
    "PreInvocation": "pre-invocation",
    "Stop": "stop",
}
GROUPED_EVENTS = ("PreToolUse", "PostToolUse")


def _hook_commands(config: dict) -> list[tuple[str, str, str]]:
    """(hook name, event, command) for every handler in an agy hooks.json.

    `PreToolUse` and `PostToolUse` entries are `{matcher, hooks: [...]}`
    groups; the other events are flat handler lists (docs/antigravity.md).
    """
    found: list[tuple[str, str, str]] = []
    for hook_name, events in config.items():
        for event, entries in events.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                found.extend(
                    (hook_name, event, handler["command"])
                    for handler in entry.get("hooks", [entry])
                )
    return found


def _hook_files() -> list[tuple[str, dict]]:
    return [
        (name, json.loads((ROOT / name).read_text(encoding="utf-8")))
        for name in HOOK_FILES
    ]


def test_efpf_hooks_run_from_the_root_workspace() -> None:
    # A workspace hook runs with `.agents/` as its working directory, so the
    # repository is `..`; no Claude-style project-dir variable exists in agy.
    for name, config in _hook_files():
        kernel = [
            (event, command)
            for _hook_name, event, command in _hook_commands(config)
            if KERNEL_HOOK in command
        ]
        assert kernel, name
        for event, command in kernel:
            assert command == (
                "uv run --directory .. --package kernel-mcp "
                f"{KERNEL_HOOK} {KERNEL_EVENTS[event]}"
            ), (name, event, command)
            assert ".sh" not in command
            assert "CLAUDE_PROJECT_DIR" not in command


def test_kernel_hooks_are_wired_to_the_four_agy_events() -> None:
    for name, config in _hook_files():
        wired = {
            event
            for _hook_name, event, command in _hook_commands(config)
            if KERNEL_HOOK in command
        }
        assert wired == set(KERNEL_EVENTS), name


def test_tool_hook_groups_match_every_tool() -> None:
    """PreToolUse and PostToolUse are grouped under a matcher; it must be "*".

    An empty matcher did not fire PostToolUse in the measured run
    (docs/antigravity.md), and a tool the gate can refuse but the post hook
    never sees would leave its intention pending, so both events match
    everything.
    """
    for name, config in _hook_files():
        for hook_name, events in config.items():
            for event in GROUPED_EVENTS:
                # Not every hook wires the tool events (the parked sense hooks
                # do not); every group that does has to match everything.
                for group in events.get(event, []):
                    assert group["matcher"] == "*", (name, hook_name, event)
                    assert group["hooks"], (name, hook_name, event)


def test_core_hook_settings_do_not_require_posix_shell_scripts() -> None:
    config = json.loads((ROOT / ".agents" / "hooks.json").read_text(encoding="utf-8"))

    assert all(".sh" not in command for _hook, _event, command in _hook_commands(config))


def test_ci_uses_the_locked_root_workspace() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'python-version: "3.13"' in workflow
    assert "run: uv sync --locked --all-extras --group dev" in workflow
    assert "run: uv sync --locked --group dev" in workflow
    assert "run: uv run ruff check ." in workflow
    assert "working-directory:" not in workflow
    assert "uv lock --check" in workflow
    assert (
        'uv run --project "$GITHUB_WORKSPACE" --directory memory-mcp pytest -q'
    ) in workflow
    assert (
        'uv run --project "$GITHUB_WORKSPACE" --directory '
        "consciousness-mcp/packages/kernel-mcp pytest -q"
    ) in workflow
    assert (
        'uv run --project "$GITHUB_WORKSPACE" --directory '
        "sociality-mcp/packages/agent-grammar pytest -q"
    ) in workflow


def test_ci_release_gate_covers_linux_macos_and_windows() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "ubuntu-latest" in workflow
    assert "macos-latest" in workflow
    assert "windows-latest" in workflow
    assert "./scripts/setup.sh" in workflow
    assert "./scripts/doctor.sh" in workflow
    assert r"scripts\setup.cmd" in workflow
    assert r"scripts\doctor.cmd" in workflow
    assert "test_embedding_warmup.py" in workflow
    assert "--live" in workflow


def test_primary_docs_describe_the_single_workspace() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_ja = (ROOT / "README-ja.md").read_text(encoding="utf-8")
    gemini = (ROOT / "GEMINI.md").read_text(encoding="utf-8")
    consciousness = (ROOT / "consciousness-mcp" / "README.md").read_text(encoding="utf-8")
    benchmark = (
        ROOT / "benchmarks" / "phenomenal_candidate" / "README.md"
    ).read_text(encoding="utf-8")
    kernel = (
        ROOT / "consciousness-mcp" / "packages" / "kernel-mcp" / "README.md"
    ).read_text(encoding="utf-8")

    assert "Python 3.13" in readme
    assert "Python 3.13" in readme_ja
    assert "single root `.venv`" in readme
    assert "単一の root `.venv`" in readme_ja
    assert "uv sync --extra dev" not in gemini
    assert "uv run --package" in gemini
    assert "--package kernel-mcp" in consciousness
    assert "--package kernel-mcp" in kernel
    assert "python benchmarks/phenomenal_candidate/run.py" in consciousness
    assert "python benchmarks/phenomenal_candidate/run.py" in benchmark


def test_docs_bound_platform_and_global_memory_launch() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_ja = (ROOT / "README-ja.md").read_text(encoding="utf-8")
    memory = (ROOT / "memory-mcp" / "README.md").read_text(encoding="utf-8")

    assert "macOS (Apple Silicon)" in readme
    assert "macOS（Apple Silicon）" in readme_ja
    assert (
        '"--directory", "/path/to/embodied-agy", '
        '"--package", "memory-mcp"'
    ) in memory


def test_primary_docs_lead_with_the_guided_core_setup() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_ja = (ROOT / "README-ja.md").read_text(encoding="utf-8")
    setup_guide = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")

    for document in (readme, readme_ja):
        assert "kmizu/embodied-agy" in document
        assert "--profile core --non-interactive" in document
        assert "/mcp" in document
        assert "--with-camera" in document
        assert "--with-voice" in document
        assert "--with-x" in document
        assert "--with-system-temperature" in document
        assert "docs/setup.md" in document
        assert "docs/sociality.md" in document
        assert "cp .env.example .env" not in document

    assert "Windows native" in readme
    assert "Windows ネイティブ" in readme_ja
    assert "TAPO_CAMERA_HOST" in setup_guide
    assert "ELEVENLABS_API_KEY" in setup_guide
    assert "X_ACCESS_TOKEN_SECRET" in setup_guide
    assert ".agents/mcp_config.json.backup-" in setup_guide


def test_primary_docs_make_windows_and_live_diagnostics_first_class() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_ja = (ROOT / "README-ja.md").read_text(encoding="utf-8")
    setup_guide = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")

    for document in (readme, readme_ja, setup_guide):
        assert r"scripts\setup.cmd" in document
        assert r"scripts\doctor.cmd --live" in document
    assert "--with-transcription whisper|faster" in document
    assert "Windows 11" in readme
    assert "Windows 11" in setup_guide
    assert "WSL2 is not required" in setup_guide
