# Hearing Hooks

Two Antigravity CLI hooks under `.agents/hooks/` turn a running hearing daemon
(started with the `start_listening` tool of the hearing MCP server in
`lifemate-ai/embodied-codex`) into conversation:

| Script | Event | What it does |
|---|---|---|
| `hearing-hook.sh` | `PreInvocation` (acts only when `invocationNum == 0`, i.e. once per user turn) | Drains the transcript buffer and injects it as `{"injectSteps": [{"ephemeralMessage": "[hearing] chunks=… span=… text=…"}]}`. Also saves the user's prompt (read from `transcriptPath`) to `hearing_user_prompt.txt` for the optional LLM filter. |
| `hearing-stop-hook.sh` | `Stop` | Waits for new speech after a reply and, when some arrives, returns `{"decision": "continue", "reason": "…"}` so the turn is extended (Claude Code's `decision: block`). Saves the Stop payload plus the last assistant message to `hearing_context.json`. |

Both hooks always print exactly one JSON object: `{"injectSteps": []}` or `{}`
when no daemon PID is alive or there is nothing to say, so a mis-registration
shows up as silence rather than an error. The protocol they follow (payload
keys, where the prompt comes from, the working directory) is measured in
[docs/antigravity.md](antigravity.md). Both source `agy-hook-lib.sh` from the
same directory for the shared parts (stdin, transcript, JSON output).

## Registration

The shipped `.agents/hooks.json` does not register them; they are opt-in.
Copy the `embodied-agy-senses` group from `.agents/hooks.example.json` into
`.agents/hooks.json` and set `"enabled": true` (or drop the key). In agy's
`hooks.json`, `PreInvocation` and `Stop` are flat lists of handlers, and every
command runs with **`.agents/` as its working directory**, hence `./hooks/…`:

```json
{
  "embodied-agy-senses": {
    "PreInvocation": [
      { "type": "command", "command": "bash ./hooks/hearing-hook.sh", "timeout": 10 }
    ],
    "Stop": [
      { "type": "command", "command": "bash ./hooks/hearing-stop-hook.sh", "timeout": 30 }
    ]
  }
}
```

The hooks can also go into the user-level `~/.gemini/config/hooks.json`; then
the working directory is `~/.gemini/config/`, so use absolute script paths.

**Give the `Stop` hook a timeout of at least 30 seconds.** One silent pass
takes about 21 s with the defaults (`HEARING_WAIT_SECONDS` 5 + three retries of
`HEARING_RETRY_WAIT` 3 + `HEARING_GUARANTEED_SLEEP` 5). The core hooks ship
with `"timeout": 10`; copying that value kills the hook mid-wait, the turn is
never extended, and nothing is logged. `30` is the value in the example file.

Because `PreInvocation` fires before *every* model call in a turn (after each
batch of tool calls too), `hearing-hook.sh` checks `invocationNum` and answers
`{"injectSteps": []}` on anything but `0`; the buffer is drained once per user
turn, exactly when Claude Code's per-prompt hook used to run.

## Files and overrides

All working files live in one directory, `HEARING_DIR`, which defaults to
`$TMPDIR` or `/tmp`: the buffer (`hearing_buffer.jsonl`), the daemon PID
(`hearing-daemon.pid`), the offset/counter files, `hearing_user_prompt.txt`,
`hearing_context.json` and `hearing_timing.log`. The shell resolves the
directory once and exports it, so the embedded Python always reads the same
place the shell writes to.

| Variable | Meaning | Default |
|---|---|---|
| `HEARING_DIR` | Directory holding the buffer, PID file and state | `$TMPDIR`, else `/tmp` |
| `HEARING_PYTHON` (or `AGY_HOOK_PYTHON`) | Interpreter used for the embedded Python | first of `python3`, `python` that can run `import sys` |
| `HEARING_LIB_DIR` | The hearing library project handed to `uv run --directory` when reading `[hearing]` from `mcpBehavior.toml` (stop hook only) | `<repo>/embodied-agy/hearing`, else `<repo>/hearing` |
| `MCP_BEHAVIOR_TOML` | The `mcpBehavior.toml` whose `[hearing]` table supplies `min_guaranteed`, `guaranteed_sleep`, `llm_filter`, `llm_filter_timeout`, `llm_filter_model` | `<repo>/mcpBehavior.toml` |
| `HEARING_WAIT_SECONDS`, `HEARING_RETRY_WAIT`, `HEARING_GUARANTEED_SLEEP`, `MAX_HEARING_CONTINUES`, `HEARING_NO_SPEECH_THRESHOLD` | Timing and filtering knobs of the stop hook | 5 / 3 / 5 / 20 / 0.6 |

`HEARING_DIR` and `HEARING_LIB_DIR` are different things: the first is where
the daemon writes, the second is where the hearing library's `pyproject.toml`
lives.

The optional hallucination filter (`llm_filter = true` under `[hearing]`) runs
`agy -p` on the recognised text with the last user prompt and assistant message
as context. It does not pass `--add-dir`, so the nested agy does not load this
workspace's hooks and cannot recurse.

## Windows (Git Bash)

The hooks run under Git Bash (`C:\Program Files\Git\bin\bash.exe`). Three
things that mean something else on Windows are handled inside the scripts
(#139), and two need attention when registering:

- **Point at Git Bash explicitly.** agy runs hook commands through `cmd /c` on
  Windows, and a bare `"command": "bash …"` resolves to the WSL App Execution
  Alias on a default install and fails with "Windows Subsystem for Linux has no
  installed distributions". Use the full path (forward slashes avoid JSON
  escaping; quote it because of the space):

  ```json
  { "type": "command", "command": "\"C:/Program Files/Git/bin/bash.exe\" ./hooks/hearing-stop-hook.sh", "timeout": 30 }
  ```

- **Keep the `Stop` timeout at 30.** Same reason as above; the symptom on
  Windows is identical and just as silent.
- `HEARING_DIR` defaults to Git Bash's `/tmp`, which is
  `C:\Users\<you>\AppData\Local\Temp`. Python receives the already-converted
  Windows path, so no `D:\tmp` surprises. Set `HEARING_DIR` if the daemon
  writes somewhere else.
- `python3` is often the Microsoft Store alias (it exits 49 without running
  anything). The hooks try `python3` then `python` and keep the first one that
  actually executes; set `HEARING_PYTHON` (for example to the interpreter of a
  `uv` environment) to skip the probe.
- A daemon started as a native Windows process is invisible to MSYS
  `kill -0`; the hooks fall back to `tasklist` to check the PID.

`tests/test_hearing_hooks.py` pins these portability fixes and runs every hook
from `.agents/` against a fake transcript, the way agy does.
