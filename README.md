# Embodied Agy

[日本語](./README-ja.md)

[![CI](https://github.com/kmizu/embodied-agy/actions/workflows/ci.yml/badge.svg)](https://github.com/kmizu/embodied-agy/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-v0.4.6-blue.svg)](https://github.com/kmizu/embodied-agy/releases)

Embodied Agy gives [Antigravity CLI](https://antigravity.google/docs/cli/using/)
(`agy`) eyes, a neck, ears, a voice, and a brain, and turns an Antigravity CLI
project into a persistent, situated companion runtime. Start without hardware:
the agent can remember across sessions, track needs and social context, and
condition planning on one committed self-world field. Add cameras,
microphones, speech, host sensors, or X only when you have them.

This repository is [embodied-claude](https://github.com/lifemate-ai/embodied-claude)
(0.4.6) ported to Antigravity CLI. [docs/antigravity.md](./docs/antigravity.md)
records what the port relies on: where files live, the hook events, headless
mode, and skills.

## Quick Start

You need [Git](https://git-scm.com/),
[uv](https://docs.astral.sh/uv/getting-started/installation/), and
[Antigravity CLI](https://antigravity.google/docs/cli/using/) (`agy`).
`uv` installs the required Python 3.13 runtime and keeps every Python MCP in a
single root `.venv`.

On Linux, macOS, or WSL2:

```bash
git clone https://github.com/kmizu/embodied-agy.git
cd embodied-agy
./scripts/setup.sh --profile core --non-interactive
```

On Windows 11 native PowerShell:

```powershell
git clone https://github.com/kmizu/embodied-agy.git
cd embodied-agy
scripts\setup.cmd --profile core --non-interactive
```

The Core profile needs no camera, API key, or other hardware. It configures:

- `memory`: long-term recall across sessions
- `desire-system`: bounded needs and homeostatic state
- `sociality`: people, relationships, boundaries, and interaction context
- `kernel`: the Enacted First-Person Field runtime and diagnostics

Run setup before starting Antigravity CLI here. Then start `agy` in the
repository and trust the folder when asked, or let setup record the trust
up front:

```bash
./scripts/setup.sh --trust-workspace
```

Antigravity CLI loads the repository's `.agents/` directory only from a trusted
workspace. It holds `.agents/mcp_config.json` (the servers setup just wrote,
gitignored), `.agents/hooks.json` (the committed EFPF hooks), and
`.agents/skills/<name>/SKILL.md` (available as `/<name>` in the session). The
hooks are active as soon as `uv` is on PATH: until setup has written
`.agents/mcp_config.json`, every write in a session opened at the repository
root is denied with a message pointing back at setup. See [Run setup before
opening the repository in Antigravity
CLI](docs/setup.md#run-setup-before-opening-the-repository-in-antigravity-cli)
and [docs/antigravity.md](./docs/antigravity.md).

## Confirm It Works

1. Start `agy` from this repository and trust the folder when asked.
2. Confirm the four Core servers are loaded (`agy mcp list`, or ask the agent
   which MCP servers it can call).
3. Say: `Remember that my setup check word is lantern.`
4. In a later turn, ask: `What was my setup check word?`

If a server does not connect, run the live doctor:

```bash
./scripts/doctor.sh --live
```

On Windows:

```powershell
scripts\doctor.cmd --live
```

The doctor reports blocking errors separately from optional hardware warnings
and prints a concrete remediation for each problem.

## Add Capabilities

Run `./scripts/setup.sh` with no arguments for the guided chooser, or add
features explicitly:

| Experience | Setup option | What you provide |
|---|---|---|
| USB camera vision | `--with-camera usb` | A connected camera |
| Tapo camera vision, PTZ, and audio | `--with-camera tapo` | Camera host and local camera credentials |
| Camera transcription | `--with-transcription whisper|faster` | Tapo camera plus ffmpeg |
| Local VOICEVOX speech | `--with-voice voicevox` | A running VOICEVOX engine |
| ElevenLabs speech | `--with-voice elevenlabs` | An ElevenLabs API key |
| X search and posting | `--with-x` | xAI and X API credentials |
| Host temperature and time | `--with-system-temperature` | A supported sensor source |

Selections compose:

```bash
./scripts/setup.sh \
  --with-camera tapo \
  --with-voice voicevox \
  --with-system-temperature \
  --non-interactive
```

Unselected servers are omitted from `.agents/mcp_config.json`. Existing configurations are
never silently overwritten. See [the setup guide](./docs/setup.md) for
environment variables, dry-run, backups, Windows commands, and troubleshooting.

## Platform Support

| Capability | Linux | macOS (Apple Silicon) | WSL2 | Windows native |
|---|---|---|---|---|
| Core runtime and Antigravity CLI hooks | Supported | Supported | Supported | Supported |
| Tapo network camera | Supported | Supported | Supported | Supported |
| USB camera | Supported | Supported | Requires USB forwarding | Supported by OpenCV-compatible devices |
| Local microphone | PulseAudio/PipeWire | AVFoundation | WSLg/PulseAudio | DirectShow |
| TTS playback | `mpv` or `ffplay` | `mpv` or `ffplay` | WSLg/PulseAudio | `mpv` or `ffplay` |
| Temperature sensors | `/sys`/hwmon | Available system sensors | Host sensors usually unavailable | LibreHardwareMonitor bridge |

Hardware support depends on drivers and the device. The setup command generates
configuration; it does not install vendor applications, ffmpeg, VOICEVOX, or
hardware drivers.

## How It Fits Together

![Embodied Agy architecture](./docs/architecture.svg)

```text
user prompt / heartbeat / tool result
                  |
           Antigravity CLI hooks
                  |
      begin -> compete -> commit field
                  |
   memory + needs + sociality + self model
                  |
       one intention -> action gate
                  |
       outcome -> mismatch -> next field
```

The Enacted First-Person Field (EFPF) runtime commits one typed self-world state
per owner and feeds it upstream into memory selection, attention/precision,
prediction, interaction planning, and action gating. Tool outcomes update
prediction error and provisional agency before the next field is committed.
Source modes (`live`, `inferred`, `remembered`, `imagined`, `mixed`) remain
visible to the agent.

This is a phenomenal-consciousness candidate architecture, also described as a
phenomenal-like causal architecture. It implements inspectable causal
conditions; it does not prove phenomenal consciousness. First-person reports
are readouts, not evidence by themselves.

Read more:

- [Consciousness architecture](./consciousness-mcp/README.md)
- [Kernel runtime](./consciousness-mcp/packages/kernel-mcp/README.md)
- [Field integrity benchmarks](./benchmarks/phenomenal_candidate/README.md)
- [Sociality v0.3 interaction loop](./docs/sociality.md)
- [Sociality package](./sociality-mcp/README.md)

## Repository Map

| Path | Role |
|---|---|
| [`memory-mcp/`](./memory-mcp/) | Long-term memory, recall, associations, and consolidation |
| [`desire-system/`](./desire-system/) | Bounded homeostatic needs and autonomous triggers |
| [`sociality-mcp/`](./sociality-mcp/) | Unified social context, relationship, boundary, and narrative facade |
| [`consciousness-mcp/`](./consciousness-mcp/) | EFPF workspace, field, agency, attention, HOR, and quality geometry |
| [`usb-webcam-mcp/`](./usb-webcam-mcp/) | Local USB camera capture |
| [`wifi-cam-mcp/`](./wifi-cam-mcp/) | Tapo PTZ vision, camera audio, and local microphone capture |
| [`tts-mcp/`](./tts-mcp/) | Unified VOICEVOX and ElevenLabs speech |
| [`system-temperature-mcp/`](./system-temperature-mcp/) | Time, resource, and temperature signals |
| [`x-mcp/`](./x-mcp/) | X search, posting, replies, and deletion |
| [`.agents/`](./.agents/) | Antigravity CLI workspace: automatic EFPF lifecycle hooks (`hooks.json`), optional sense hooks, skills, and the MCP config example |
| [`scripts/`](./scripts/) | Guided setup, doctor, seeding, and maintenance tools |

All Python packages belong to one uv workspace. Run one sync from the
repository root:

```bash
uv sync --locked
```

`tts-mcp[elevenlabs]`, `wifi-cam-mcp[transcribe...]`, `usb-webcam-mcp`,
`system-temperature-mcp`, and `x-mcp` are declared as optional extras in the
root `pyproject.toml`, not base dependencies. A plain `uv sync` only installs
the base workspace packages (`desire-system`, `kernel-mcp`,
`memory-mcp`, `sociality-mcp`) and will **uninstall** any of those optional
packages that were previously installed outside the requested extras — for
example, `python -c "import elevenlabs"` starts failing with
`No module named 'elevenlabs'` inside a running `tts-mcp` server even though
nothing about `tts-mcp` itself changed. If a live MCP server still holds one
of the removed console-script `.exe` files open, `uv sync` also fails outright
with an `os error 32` file-lock message, which looks like a process problem
but is really this same partial-removal in progress. Sync with the extras you
actually use instead:

```bash
uv sync --locked --extra all           # everything, including elevenlabs
uv sync --locked --extra voice-elevenlabs
uv sync --locked --extra camera-tapo
```

To run a package directly:

```bash
uv run --package memory-mcp memory-mcp
uv run --package kernel-mcp kernel-mcp
```

## Configuration Safety

- `.agents/mcp_config.json` is the project-local credential source and is ignored by Git.
- Guided setup writes it atomically and uses mode `0600` on POSIX.
- A different existing config is refused unless `--force` is explicit.
- Forced replacement first creates `.agents/mcp_config.json.backup-<timestamp>`.
- `socialPolicy.toml` is created from the example only when absent.
- `--dry-run` performs no sync, download, directory creation, or file write.
- [`.agents/mcp_config.json.example`](./.agents/mcp_config.json.example) is the portable Core shape. Guided
  setup adds selected capabilities and their environment safely.

## Development

The CI source of truth is [`.github/workflows/ci.yml`](./.github/workflows/ci.yml).
The main workspace checks start with:

```bash
uv sync --locked
uv lock --check
uv run pytest tests -q
```

Package tests and lint run from the same root environment. See
[`GEMINI.md`](./GEMINI.md) and package-level `AGENTS.md` files before changing a
subsystem.

## Autonomous and Strict Runtimes

Antigravity CLI hooks (`.agents/hooks.json`, adapter `efpf-agy-hook`)
automatically begin and refresh fields around the `PreInvocation`,
`PreToolUse`, `PostToolUse`, and `Stop` events. Hook gating covers outward MCP
actions, including speech, social posts, camera movement, and side effects.

Headless runs must attach the workspace explicitly, because `agy -p` ignores
the current directory:

```bash
agy -p "..." --add-dir /path/to/embodied-agy --dangerously-skip-permissions
```

`--dangerously-skip-permissions` approves every tool call; the kernel's
`PreToolUse` gate still refuses any outward action without a committed field
and a matching intention. The event mapping, payload shapes, and headless
flags are in [docs/antigravity.md](./docs/antigravity.md).

Bare interactive Antigravity CLI streams chat text before an external pre-display
gate can fully approve it. Research experiments that require strict text-output
gating should use the documented non-interactive wrapper/runtime described in
the [kernel README](./consciousness-mcp/packages/kernel-mcp/README.md).
Ordinary interactive use remains compatibility mode for displayed chat text.

Autonomous heartbeat operation is optional. Review
[`autonomous-action.sample.sh`](./autonomous-action.sample.sh) and the
privacy/boundary policies before enabling periodic observation or outward
actions.

## Privacy and Welfare

Cameras and microphones can capture other people. Obtain consent, keep boundary
policies current, and disable autonomous capture where observation is
inappropriate. The field runtime bounds sustained negative valence, supports
pause/resume and reversible ablation, and leaves high-frequency spawning off by
default.

Mechanism indicators and self-reports both carry uncertainty. Technical
documentation follows the repository's phenomenal claim policy and does not
present the architecture as proof of consciousness.

## Related Project

[familiar-ai](https://github.com/lifemate-ai/familiar-ai) is a higher-level
companion framework built on these embodied services.

## License

MIT License

## Acknowledgments

This project began with an inexpensive camera and grew into an experiment in
memory, embodiment, agency, and human-AI relationships.

- [Rumia-Channel](https://github.com/Rumia-Channel) for the ONVIF contribution
  ([#5](https://github.com/kmizu/embodied-agy/pull/5))
- [fruitriin](https://github.com/fruitriin) for adding day-of-week context to
  interoception ([#14](https://github.com/kmizu/embodied-agy/pull/14))
- [sugyan](https://github.com/sugyan) for
  [claude-code-webui](https://github.com/sugyan/claude-code-webui)
