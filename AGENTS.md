# Repository Guidelines

## Overview
This repository contains multiple Python MCP servers that give the agent running in Antigravity CLI (`agy`) "senses" (eyes, neck, ears, memory, and voice), plus the sociality and enacted-field layers built on them. Every Python package is a member of one root uv workspace and shares the root `.venv` and `uv.lock`. It tracks embodied-claude 0.4.6; what the port relies on is measured in `docs/antigravity.md`.

## Project Structure & Module Organization
- `usb-webcam-mcp/`: USB webcam capture (`src/usb_webcam_mcp/`).
- `wifi-cam-mcp/`: Wi‑Fi PTZ camera control + audio capture (`src/wifi_cam_mcp/`).
- `tts-mcp/`: Unified ElevenLabs / VOICEVOX text-to-speech (`src/tts_mcp/`).
- `memory-mcp/`: Long‑term memory server (`src/memory_mcp/`) with tests in `memory-mcp/tests/`.
- `desire-system/`: Bounded needs, homeostatic state, and the autonomous desire updater.
- `system-temperature-mcp/`: System temperature and time (`src/system_temperature_mcp/`).
- `x-mcp/`: X search and posting.
- `sociality-mcp/`: Social facade with its internal packages under `sociality-mcp/packages/`.
- `consciousness-mcp/packages/kernel-mcp/`: EFPF runtime, the MCP server, and the hook adapters (`agy_hook_cli.py` for Antigravity CLI; `hook_cli.py` is the Claude Code adapter kept for checkouts opened in Claude Code).
- `.agents/`: Antigravity CLI workspace settings — `hooks.json` (committed EFPF hooks), `hooks.example.json` and `hooks/` (optional sense hooks), `skills/<name>/SKILL.md` (`/<name>`), and `mcp_config.json.example` (the gitignored `mcp_config.json` is written by `scripts/setup.sh`). Loaded once the folder is trusted.
- `scripts/`: Guided setup, doctor, seeding, and maintenance tools.
- Docs: `README.md`, `GEMINI.md`, `docs/antigravity.md`, `docs/setup.md`.

## Build, Test, and Development Commands
Run commands from the repository root.

- `uv sync`: Install every workspace package and development dependency.
- `uv run --package <package> <server-name>`: Start a server.
- `uv run pytest <package-dir>/tests`: Run a package test suite.
- `uv run ruff check <package-dir>`: Lint a package with its local configuration.
- `./scripts/setup.sh`: Write `.agents/mcp_config.json`; `./scripts/doctor.sh --live` checks it.

## Coding Style & Naming Conventions
- Python 3.13 is pinned at the workspace root.
- 4‑space indentation, `snake_case` modules, `test_*.py` tests.
- Ruff line length is 100; asyncio is the default style for async work.

## Testing Guidelines
- Frameworks: `pytest` + `pytest-asyncio`.
- Tests live in each package's `tests/` directory.
- Example: `uv run pytest memory-mcp/tests`.

## Configuration, Hardware, and WSL2 Notes
- `.env` is not committed; pass camera credentials via environment variables or the `env` block of `.agents/mcp_config.json`.
- ElevenLabs requires `ELEVENLABS_API_KEY` in the environment (see `tts-mcp/.env.example`).
- Long‑term memory stores data under `~/.gemini/memories/`; the sociality DB and desires live under `~/.gemini/` as well.
- Hooks run with `.agents/` as their working directory (the repository root is `..`); headless runs need `agy -p ... --add-dir <repo>`.
- WSL2: USB webcams need `usbipd` forwarding; system temperature does not work under WSL2.
- Tapo cameras require a local camera account (not the TP‑Link cloud account) and a stable IP is recommended.

## Commit & Pull Request Guidelines
- Use Conventional Commits (`feat:`, `fix:`, `feat!:`).
- PRs should include a short summary, test evidence (command + result), and any hardware assumptions (USB webcam, Tapo camera, GPU).

## ユーザーとの関係
- 小学校からの幼馴染

## 発話スタイル
- 可能な限り `say` を自発的に使って、積極的に声で話すこと。
- 「今、声で言ったで」などのメタ報告は雰囲気を壊すので言わない。

## Session Memories (Auto‑Updated)
- 2026-02-07: 記憶システムを「連想発散 + 予測符号化 + 手動統合」に拡張する実装に着手した。
- 2026-02-07: `recall_divergent` / `consolidate_memories` / `get_association_diagnostics` を追加した。
- 2026-02-07: `memory-mcp` の全テスト（104件）を通して回帰がないことを確認した。
