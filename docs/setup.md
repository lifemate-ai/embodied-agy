# Setup Guide

This guide covers the generated project-local `.agents/mcp_config.json`. It is the canonical
credential source for the guided setup. You do not need to run `uv sync` inside
individual package directories or create package-local `.env` files.

## Prerequisites

- Git
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Antigravity CLI (`agy`; what this repository relies on is measured in
  [docs/antigravity.md](./antigravity.md))
- Network access for the first workspace sync and memory model download

The optional autonomous heartbeat needs two more on `PATH`: `jq` and
[`bun`](https://bun.sh/). Neither is required for anything else, and
`autonomous-action.sh` degrades quietly without them -- see
[Autonomous Prompt Files](./autonomous-files.md).

The workspace requires Python 3.13. `uv` can install and select it
automatically.

## Core Setup

Core works without hardware or third-party API keys.

### Linux, macOS, and WSL2

```bash
git clone https://github.com/kmizu/embodied-agy.git
cd embodied-agy
./scripts/setup.sh --profile core --non-interactive
```

### Windows 11 native PowerShell

```powershell
git clone https://github.com/kmizu/embodied-agy.git
cd embodied-agy
scripts\setup.cmd --profile core --non-interactive
```

WSL2 is not required. The Windows launcher runs the same Python setup service
and writes the same `.agents/mcp_config.json` as POSIX setup.

Setup performs one locked Core workspace sync, writes the Core
`.agents/mcp_config.json`, creates `socialPolicy.toml` only when absent, warms
the selected memory model, and runs the doctor. Add `--trust-workspace` to also
record the checkout in Antigravity CLI's `trustedWorkspaces`, which an
interactive session needs before it will load `.agents/` (see
[Trusting the workspace](#trusting-the-workspace)).

Core contains:

| Server | Purpose |
|---|---|
| `memory` | Persistent recall and associations |
| `desire-system` | Bounded needs and homeostatic state |
| `sociality` | People, relationships, boundaries, and interaction context |
| `kernel` | Enacted field runtime, action gate, and diagnostics |

### Run setup before opening the repository in Antigravity CLI

The repository ships `.agents/hooks.json` (committed), whose hooks are active
in any interactive Antigravity CLI session opened at the repository root once
the folder is trusted and `uv` is on PATH, and in any `agy -p --add-dir` run
regardless of trust. `.agents/hooks.example.json` is the same file plus the
optional sense hooks (interoception, auto-recall, auto-social, hearing) as a
second, disabled hook group to copy from.

The PreToolUse hook fails closed: with no registered intention it denies file
writes (`write_to_file`, `replace_file_content`) and any `run_command` that
changes state. The only way to register an intention is
`propose_field_action`, a tool of the `kernel` MCP server, and that
server is wired up by the gitignored `.agents/mcp_config.json` that setup
generates. A checkout that has not run setup therefore cannot write and cannot
unlock writing from inside the session. The deny reason says so and names
`./scripts/setup.sh`; the doctor reports the same state as `hooks:gate`. Run
setup first, then start (or restart) Antigravity CLI. To read the code without
running setup, open a different directory as the project root.

The hooks run `uv run --directory .. --package kernel-mcp
efpf-agy-hook ...`. Antigravity CLI runs every hook with the directory that
holds its `hooks.json` as the working directory, so from `.agents/` the `..` is
the repository root. If the file is copied elsewhere -- into
`~/.gemini/config/hooks.json`, say -- `..` points somewhere else and `uv`
creates a fresh `.venv` in that directory before the hook code runs, which this
project cannot prevent from inside the hook. Keep the workspace hooks in
`.agents/`, and delete any stray `.venv` that appears in an unrelated folder.

## Guided Chooser

Run without arguments:

```bash
./scripts/setup.sh
```

On Windows, use `scripts\setup.cmd`.

The chooser asks which camera, voice engine, X integration, host sensor, and
memory model are available. It asks for credentials only after the
corresponding capability is selected. Secret input is not echoed.

The stable options are:

```text
--profile core
--with-camera usb|tapo
--with-transcription whisper|faster
--with-voice voicevox|elevenlabs
--with-x
--with-system-temperature
--embedding-model small|base
--skip-model-download
--non-interactive
--dry-run
--force
```

Selections compose. For example:

```bash
./scripts/setup.sh \
  --with-camera tapo \
  --with-voice voicevox \
  --with-system-temperature \
  --non-interactive
```

## Memory Model

The code default and the generated Core config are both:

```text
intfloat/multilingual-e5-small
```

It downloads faster and needs less disk/RAM. Select the larger model for
better retrieval quality:

```bash
./scripts/setup.sh \
  --profile core \
  --embedding-model base \
  --non-interactive
```

Setup warms the model before the first Antigravity CLI session. To postpone that
download:

```bash
./scripts/setup.sh \
  --profile core \
  --skip-model-download \
  --non-interactive
```

The first memory operation will download the model instead.

### The server takes tens of seconds to start

`memory-mcp` warms the embedding model before it answers anything
(`MemoryStore.warmup()`, called during startup). Measured on `b4ded53`, Windows
11, with the model already on disk:

```text
import         0.6 s
warmup()      20.3 s        intfloat/multilingual-e5-base
```

The default `e5-small` is quicker, and the first run is slower still because
the model has to be fetched. Either way this is longer than a short client-side
startup timeout allows.

If `memory` is missing from the server list and nothing in the logs explains
why, suspect the warmup before a configuration error. Claude Code had an
`MCP_TIMEOUT` knob for this; Antigravity CLI 1.1.25 exposes no startup-timeout
setting (`agy mcp add --help` has none), so the two things that help are
running setup without `--skip-model-download`, so the model is already on
disk, and re-checking `/mcp` once the warmup has had its twenty seconds.

A server that timed out during startup is skipped, not reported. Sessions
continue without memory, which looks like a working setup that never recalls
anything.

## Optional Capabilities

Non-interactive setup reads credentials from the current environment and writes
only selected values to the ignored, mode-`0600` `.agents/mcp_config.json`.

### USB camera

No credential is required:

```bash
./scripts/setup.sh --with-camera usb --non-interactive
```

On WSL2, forward the USB device with `usbipd` before starting Antigravity CLI. On
other platforms, the camera must be visible to OpenCV.

### Tapo camera

Create a local camera account in the Tapo application. This is not the TP-Link
cloud account.

Required environment:

| Variable | Meaning |
|---|---|
| `TAPO_CAMERA_HOST` | Camera IP address or hostname |
| `TAPO_USERNAME` | Local camera username |
| `TAPO_PASSWORD` | Local camera password |

POSIX:

```bash
export TAPO_CAMERA_HOST=192.168.1.100
export TAPO_USERNAME='camera-user'
export TAPO_PASSWORD='camera-password'
./scripts/setup.sh --with-camera tapo --non-interactive
```

PowerShell:

```powershell
$env:TAPO_CAMERA_HOST = "192.168.1.100"
$env:TAPO_USERNAME = "camera-user"
$env:TAPO_PASSWORD = "camera-password"
scripts\setup.cmd --with-camera tapo --non-interactive
```

`ffmpeg` is optional for still images/PTZ and required for camera audio.
Transcription models are not installed with the camera alone; select exactly
one backend when needed:

```text
--with-transcription whisper|faster
```

This option requires `--with-camera tapo`. See
[`wifi-cam-mcp/README.md`](../wifi-cam-mcp/README.md) and
[`wifi-cam-mcp/README_WinNative.md`](../wifi-cam-mcp/README_WinNative.md).

### VOICEVOX

Start a VOICEVOX engine first. Setup uses
`http://localhost:50021` unless `VOICEVOX_URL` is set:

```bash
export VOICEVOX_URL=http://localhost:50021
./scripts/setup.sh --with-voice voicevox --non-interactive
```

Local playback needs `mpv` or `ffplay`. A missing player is a doctor warning,
not a Core failure.

### ElevenLabs

`ELEVENLABS_API_KEY` is required. `ELEVENLABS_VOICE_ID` is optional because
`tts-mcp` has a default voice.

```bash
export ELEVENLABS_API_KEY='...'
export ELEVENLABS_VOICE_ID='...'  # optional
./scripts/setup.sh --with-voice elevenlabs --non-interactive
```

PowerShell uses `$env:ELEVENLABS_API_KEY` and
`$env:ELEVENLABS_VOICE_ID`.

### X search and posting

The generated X server exposes both xAI-backed search and authenticated posting,
so non-interactive setup requires all five values:

| Variable | Source |
|---|---|
| `XAI_API_KEY` | xAI Console |
| `X_CONSUMER_KEY` | X Developer Portal |
| `X_CONSUMER_SECRET` | X Developer Portal |
| `X_ACCESS_TOKEN` | X Developer Portal |
| `X_ACCESS_TOKEN_SECRET` | X Developer Portal |

```bash
export XAI_API_KEY='...'
export X_CONSUMER_KEY='...'
export X_CONSUMER_SECRET='...'
export X_ACCESS_TOKEN='...'
export X_ACCESS_TOKEN_SECRET='...'
./scripts/setup.sh --with-x --non-interactive
```

### Host temperature and time

```bash
./scripts/setup.sh --with-system-temperature --non-interactive
```

Linux uses available `/sys`/hwmon sensors. Windows native temperature support
uses the LibreHardwareMonitor bridge documented in
[`system-temperature-mcp/README_WinNative.md`](../system-temperature-mcp/README_WinNative.md).
WSL2 normally cannot see Windows host temperature sensors.

The tool replies are phrased in Kansai dialect by default. Set
`SYSTEM_TEMPERATURE_TONE=neutral` for plain Japanese and
`SYSTEM_TEMPERATURE_TIMEZONE` (IANA name, default `Asia/Tokyo`) for the clock;
see [Persona and companion](#persona-and-companion) below.

### Hearing hooks

The `PreInvocation` / `Stop` hooks that feed microphone transcripts into the
conversation are opt-in; `.agents/hooks.example.json` carries them in its
disabled `embodied-agy-senses` group. Registration, the `Stop` timeout (at
least 25 s), and the Windows notes live in
[docs/hearing-hooks.md](hearing-hooks.md).

## Persona and companion

Several servers carry names or a voice. None of them is required, and every
default is neutral; the values used by this project's own agent live in the
package `.env.example` files. The setup script passes any of these through to
the generated `.agents/mcp_config.json` when they are set in the environment it runs under.

| Variable | Default | Used by |
| --- | --- | --- |
| `COMPANION_NAME` | `あなた` | memory (`person` default of `tom` / `joint_attention`), desire-system (`miss_companion` label) |
| `COMPANION_ID` | `companion` | sociality / interaction-orchestrator (`person_id` default and the primary-companion response contract), kernel hooks |
| `SELF_NAME` | `自分` (desire-system) / `This agent` (self-narrative summary) | desire-system `identity_coherence`, sociality `get_self_summary` |
| `SELF_PRONOUN` | `自分` | desire-system `identity_coherence` |
| `SYSTEM_TEMPERATURE_TONE` | `kansai` | system-temperature phrasing (`kansai` or `neutral`) |
| `SYSTEM_TEMPERATURE_TIMEZONE` | `Asia/Tokyo` | system-temperature `get_current_time` |
| `DESIRE_TIMEZONE` | `Asia/Tokyo` | desire-system and kernel allostatic quiet hours (IANA name or `+09:00`) |
| `DESIRE_NIGHT_START` / `DESIRE_NIGHT_END` | `0` / `5` | night band `[start, end)`; `end < start` wraps past midnight |
| `DESIRE_DAWN_END` | `7` | dawn band `[NIGHT_END, DAWN_END)` |

## Preview Without Side Effects

Use `--dry-run` to inspect a redacted generated config:

```bash
./scripts/setup.sh \
  --profile core \
  --with-camera tapo \
  --non-interactive \
  --dry-run
```

Dry-run does not:

- run `uv sync`
- download the embedding model
- write or back up `.agents/mcp_config.json`
- create `socialPolicy.toml`
- create state directories
- change permissions

Credentials are rendered as `<redacted>`.

## Existing `.agents/mcp_config.json`

Setup has three outcomes:

1. No file: create `.agents/mcp_config.json` atomically.
2. Semantically equivalent JSON: keep the original bytes unchanged.
3. Different or invalid JSON: stop and require explicit `--force`.

Forced replacement:

```bash
./scripts/setup.sh --profile core --non-interactive --force
```

The previous bytes are saved first as:

```text
.agents/mcp_config.json.backup-YYYYMMDD-HHMMSS
```

If that name exists, setup adds a numeric suffix. Backup files are ignored by
Git.

Setup does not merge unknown custom MCP servers into the generated profile.
Keep a manual copy or re-add custom entries after generation. The doctor
reports unknown entries as warnings and does not modify them.

### Adding a server: the tool's name decides whether it is gated

`is_external_tool` (`kernel_mcp/agency.py`) classifies every
`mcp__`-prefixed call as an outward act **unless the name contains one of a
small set of read-only fragments** -- `__get_`, `__query_`, `__list_`,
`__search_`, `__read_`, `__see`, `__capture`, and a few more. An outward act
needs a matching `propose_field_action` before the PreToolUse hook will allow
it.

The classifier receives the tool name and its input, and nothing else. A server
that declares `ToolAnnotations(readOnlyHint=True)` is not consulted: the
annotation cannot reach the function, so the **name** has to carry it.

The failure is quiet and points the wrong way. A tool that changes nothing --
the one worth calling freely, right before acting -- is the one that gets
gated, because naming it symmetrically with its neighbours (`x_state` beside
`x_move`, `x_click`) puts it on the outward side. Renaming it `get_x_state` is
enough.

Defaulting unknown names to outward is the safe direction, and it is why this
is a naming note rather than a bug. But it is only discoverable by reading
`agency.py` or by measuring, so: check your tool names against that list before
wiring a new server in.

### `env` blocks override the inherited environment

A value in a server's `env` block wins over whatever the parent process
exported, so only put values there that you want pinned. Setup writes
`SOCIAL_DB_PATH` and `MEMORY_HTTP_PORT` only when they are set in the
environment it runs in; otherwise the servers fall back to their code defaults
(`~/.gemini/sociality/social.db` and `18900`) and a later
`SOCIAL_DB_PATH=... agy` still takes effect. Copying the defaults into
`.agents/mcp_config.json` by hand would silently pin them.

## Trusting the workspace

Antigravity CLI reads a folder's `.agents/` -- hooks, MCP servers, skills --
only after the folder is trusted. Interactive `agy` asks the first time it is
opened in the repository and records the answer in `trustedWorkspaces` inside
`~/.gemini/antigravity-cli/settings.json`. Until then an interactive session
runs with no kernel hooks and no Core servers, and nothing says so beyond
`/mcp` listing nothing.

Either accept that prompt, or have setup record the trust:

```bash
./scripts/setup.sh --trust-workspace
```

The doctor reports an untrusted checkout as a `workspace trust` warning. It is
a warning rather than an error because headless runs do not need it:

```bash
agy -p "..." --add-dir /path/to/embodied-agy
```

`agy -p` does not attach the current directory at all -- `workspacePaths`
arrives empty -- so the workspace has to be passed with `--add-dir`, and with
it `.agents/hooks.json` and `.agents/mcp_config.json` load whether or not the
folder is in `trustedWorkspaces`. `autonomous-action.sh` relies on this;
[Autonomous Prompt Files](./autonomous-files.md) lists what goes quiet when
the flag is missing.

There is no per-server approval list to keep in step with the config, so
editing `.agents/mcp_config.json` resets nothing; restart Antigravity CLI so it
re-reads the file. Servers that should be available in every project rather
than this checkout go in the user-level `~/.gemini/config/mcp_config.json`
through `agy mcp add <name> <command> [args...]` (`agy mcp list` shows what is
registered); setup neither reads nor writes that file.

## Doctor

Run static checks:

```bash
./scripts/doctor.sh
```

Windows:

```powershell
scripts\doctor.cmd
```

Inspect another file:

```bash
uv run python scripts/doctor.py --config /path/to/.agents/mcp_config.json
```

Run real MCP startup checks against isolated temporary state:

```bash
./scripts/doctor.sh --live
```

Windows:

```powershell
scripts\doctor.cmd --live
```

Use `--json` with either mode for a stable machine-readable report.

Statuses:

| Status | Meaning |
|---|---|
| `[ok]` | The requirement is satisfied |
| `[warn]` | An optional selected capability may be unavailable |
| `[error]` | Core or a selected configuration cannot start correctly |

Static doctor is read-only. It does not create state directories, start MCP
servers, or connect to hardware. Its one network action is a TCP connect to
the memory HTTP recall port on localhost. It verifies:

- Python 3.13
- current `uv.lock`
- valid known MCP command shapes
- selected required environment values
- root workspace package declarations
- `socialPolicy.toml`
- writable existing state parents
- optional `ffmpeg`, `mpv`, or `ffplay`
- the checkout is in `trustedWorkspaces` (`workspace trust`, a warning; see
  above)
- memory HTTP recall port (`MEMORY_HTTP_PORT`, default `18900`) is listening.
  `kernel` pulls memory candidates into each tick over it and
  commits the field without them when nothing answers. memory-mcp binds the
  port when Antigravity CLI starts it, so this is a warning until the first
  session is running.
- `SOUL.md`, `TODO.md`, `ROUTINES.md` for the autonomous prompt (a warning
  once `autonomous-action.sh` is installed; see
  [`docs/autonomous-files.md`](autonomous-files.md))

Unknown custom MCP entries are warnings.

`--live` additionally starts each selected MCP over stdio, performs protocol
initialization, lists tools, and makes one memory write to an isolated temporary
database. Selected hardware integrations may contact their configured devices.
The temporary diagnostic state is deleted afterward.

## First Success

After setup:

```bash
agy
```

Accept the trust prompt if it appears. Then:

1. Run `/mcp`.
2. Confirm `memory`, `desire-system`, `sociality`, and `kernel`.
3. Ask the agent to remember a short fact.
4. Ask for that fact in a later turn.

Antigravity CLI loads project MCP configuration at startup. Restart it after
changing `.agents/mcp_config.json`.

## Troubleshooting

### `uv` is missing

POSIX:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Open a new terminal and rerun setup.

### Every write is denied right after cloning

The deny reason begins with `kernel MCP server is not configured for
this project` and ends with the runtime's own verdict. Read-only tools still
pass. Run `./scripts/setup.sh` (or `scripts\setup.cmd`), then restart
Antigravity CLI; see [Run setup before opening the repository in Antigravity
CLI](#run-setup-before-opening-the-repository-in-antigravity-cli).

A deny that reads `EFPF hook received no/invalid JSON on stdin; failing
closed` means the hook ran but no payload reached it. In an interactive session
that never denies anything, check the trust first: an untrusted folder's hooks
do not run at all (see [Trusting the workspace](#trusting-the-workspace)). When driving the hook by
hand, PowerShell `'{json}' | uv run ...` can drop stdin; use Git Bash, or
`cmd /c "... < file"`.

### A Core server is disconnected

1. Restart Antigravity CLI after setup.
2. Run `./scripts/doctor.sh --live`, or `scripts\doctor.cmd --live` on Windows.
3. Run `uv sync --locked` if the workspace or lock check fails.
4. Inspect `/mcp` for the server's stderr.

### Setup refuses an existing config

This is intentional. Inspect the redacted proposal with `--dry-run`, preserve
custom entries, then use `--force` only when replacing the file is intended.

### The first memory call downloads a model

Setup was run with `--skip-model-download`, or the selected model cache was
removed. Rerun setup without that option.

### Camera or audio is unavailable

Core can still operate. Run the doctor, then follow the package-specific
hardware guide linked above. Setup does not install device drivers or vendor
software.
