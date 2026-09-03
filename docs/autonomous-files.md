# Autonomous Prompt Files

`autonomous-action.sample.sh` (installed as `autonomous-action.sh`) builds the
heartbeat prompt with three `@FILE` mentions:

```text
@SOUL.md
@TODO.md
@ROUTINES.md
```

`@FILE` is Antigravity CLI's context mention, the same notation Claude Code
used: the file's contents are expanded into the prompt. The files live in the
project directory, next to the script (the script `cd`s there and hands the
directory to `agy -p` as `--add-dir`). None of them ship with the repository,
because their contents are yours.

## What each file is for

| File | Purpose | Who writes it |
|---|---|---|
| `SOUL.md` | The agent's personality and values: name, voice, what it cares about, what it refuses. The `/recover-from-compact` skill re-reads it first ("remember who you are"). | You, once; the agent may revise with you |
| `TODO.md` | What the agent wants to do. Read to pick an action, written back with what was finished. When a heartbeat runs out of `[CONTINUE]` chains it parks the rest under a "前回の続き" (carried over) section here. | You and the agent |
| `ROUTINES.md` | Recurring things with an interval and a last-run date. On a routine heartbeat the agent picks the one furthest behind schedule, runs it, and updates the date. Optional. | You and the agent |

Without them the heartbeat still runs on `GEMINI.md` alone.

## What happens when one is missing

An `@` mention of a file that does not exist resolves to nothing, and agy does
not say so. The heartbeat completes, the log looks normal, and the prompt has
been running with a dead reference the whole time. Three things now point at
it:

- `autonomous-action.sh` checks for each of the three files before building
  the prompt and writes `WARN: SOUL.md not found in <dir>; the @SOUL.md
  reference in the prompt will not resolve` to its log and to stderr. It does
  not abort.
- `scripts/doctor.sh` warns per missing file when `autonomous-action.sh` is
  installed, and merely notes their absence before that.
- This page exists.

## Silent failure modes

`autonomous-action.sh` has a handful of ways to run to completion, exit 0 and
write a normal-looking log while doing less than it should. Two are commands
that nothing else in the repository requires; the rest are where Antigravity
CLI behaves differently from Claude Code (the measured contract is in
[docs/antigravity.md](antigravity.md)).

| What | Used for | If it is missing or wrong |
|---|---|---|
| `--add-dir "$SCRIPT_DIR"` | Attaching the project as the workspace. `agy -p` does not attach the current directory on its own; `workspacePaths` arrives empty | `.agents/hooks.json` is not loaded, so there is no kernel gate and no `HEARTBEAT` tick; `.agents/mcp_config.json` is not loaded, so there is no memory, sociality or kernel. The model answers from `GEMINI.md` alone and the run exits 0 -- **the quiet one** |
| Workspace trust | Interactive `agy` only: a folder's `.agents/` loads once it is in `trustedWorkspaces` | Does not matter here. `agy -p --add-dir` loads the workspace whether or not the folder is trusted; the doctor's `workspace trust` warning is about opening the repository interactively |
| `jq` | Reading `.status`, `.conversation_id` and `.response` out of the result JSON | The output is logged raw as `[非JSON出力]`, the conversation file is not updated, and the next heartbeat starts a new conversation instead of resuming with `--conversation` |
| `bun` | `scripts/desire-tick.ts` | stderr is captured and logged as `[欲望エラー]` -- **the one that says so** |
| `bun` | `scripts/interoception.ts` | stderr goes to `/dev/null`; the interoception line is simply absent |

There is no per-tool allow list to keep in step with anything: agy has no
`--allowedTools`, the heartbeat runs with `--dangerously-skip-permissions`, and
what the model may actually do is decided by the `PreToolUse` intention gate in
`.agents/hooks.json`. There is likewise no separate MCP file for the heartbeat;
it sees exactly the servers in `.agents/mcp_config.json`.

## Resuming

The script keeps the `.conversation_id` of the last successful run in
`heartbeat-session-id` (gitignored) and passes it back as `--conversation <id>`
on the next run, so consecutive heartbeats share one conversation. Each run logs
`[status] SUCCESS` (or `ERROR`, `CANCELED`, `INTERRUPTED`, on which the script
exits 1) and `[conversation_id] <id>`.

When agy no longer has the conversation it does not fail: it prints
`warning: conversation "<id>" not found` on stderr, starts a fresh one, and
returns `status: SUCCESS` with the new id. The script logs that as
`[resume失敗/会話消失]` and stores the new id, so one heartbeat loses its thread
and the next resumes normally. Runs with an ad-hoc prompt
(`autonomous-action.sh -p "..."`) do not overwrite the stored id.

## Templates

Minimal, neutral starting points are in `examples/`:

```bash
cp examples/SOUL.sample.md SOUL.md
cp examples/TODO.sample.md TODO.md
cp examples/ROUTINES.sample.md ROUTINES.md   # optional
```

Edit them before the first heartbeat. `presets/` is something else: those are
`~/.gemini/GEMINI.md` personality templates, not these files.
