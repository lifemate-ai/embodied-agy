# Antigravity CLI: what this repository relies on

embodied-agy is embodied-claude ported to [Antigravity CLI](https://antigravity.google/docs/cli/using/)
(`agy`). Everything below was measured against `agy 1.1.25` with hooks that
dumped their stdin, not read from a description, so it is the contract the
code and scripts in this repository assume. Re-check it when agy changes.

## Where things live

| Purpose | Claude Code | Antigravity CLI |
|---------|-------------|-----------------|
| Project MCP servers | `.mcp.json` | `.agents/mcp_config.json` (gitignored; `scripts/setup.sh` writes it) |
| User MCP servers | `~/.claude.json` | `~/.gemini/config/mcp_config.json`, `agy mcp add` |
| Hooks | `.claude/settings.json` | `.agents/hooks.json` (committed) and `~/.gemini/config/hooks.json` |
| Project instructions | `CLAUDE.md` | `GEMINI.md` (and `AGENTS.md`; both are read) |
| Slash commands | `.claude/commands/<name>.md` | `.agents/skills/<name>/SKILL.md` (`/<name>`) |
| Extra rules | -- | `.agents/rules/*.md` |
| CLI settings | `~/.claude/settings.json` | `~/.gemini/antigravity-cli/settings.json` |
| Agent state (memory, sociality DB, desires) | `~/.claude/` | `~/.gemini/` |
| Conversation transcripts | `~/.claude/projects/...` | `~/.gemini/antigravity-cli/brain/<conversationId>/.system_generated/logs/transcript_full.jsonl` |

`.agents/workflows/*.md` still load but are deprecated in favour of skills.

### Trust

An interactive `agy` session loads `.agents/` (hooks, MCP servers, skills)
only after the folder is trusted; agy records that in `trustedWorkspaces`
inside `~/.gemini/antigravity-cli/settings.json`. Print mode (`agy -p`) does
**not** attach the current directory at all -- `workspacePaths` arrives empty
and `.agents/` is ignored -- unless the workspace is passed explicitly:

```bash
agy -p "..." --add-dir /path/to/embodied-agy
```

With `--add-dir` the workspace hooks and MCP servers load in print mode
whether or not the folder is in `trustedWorkspaces`. The autonomous heartbeat
relies on this; `scripts/doctor.py` warns when the repository is not trusted
because that is what an interactive session needs.

## Headless mode

```bash
agy -p "prompt" --add-dir "$REPO" --dangerously-skip-permissions --output-format json
agy -p "prompt" --add-dir "$REPO" --conversation "$CONVERSATION_ID" ...   # resume
```

| Claude Code | Antigravity CLI |
|-------------|-----------------|
| `claude -p` | `agy -p` (`--print`, `--prompt`) |
| `--resume <session_id>` | `--conversation <conversation_id>`; `--continue` / `-c` for the latest |
| `--allowedTools ...` | no equivalent; `--dangerously-skip-permissions` approves every tool and the kernel gate refuses what has no intention |
| `--mcp-config file` | no equivalent; the workspace `.agents/mcp_config.json` loads via `--add-dir` |
| `--output-format json` | same flag; different shape (below) |
| default timeout | `--print-timeout` (default `5m`) |

`--output-format json` prints one object:

```json
{"conversation_id": "...", "status": "SUCCESS", "response": "...",
 "duration_seconds": 14.6, "num_turns": 1,
 "usage": {"input_tokens": 26142, "output_tokens": 3402, "thinking_tokens": 3332,
           "cache_read_tokens": 16302, "total_tokens": 29544}}
```

`status` is `SUCCESS`, `ERROR`, `CANCELED` or `INTERRUPTED`; `error` is present
on failure. Where the Claude version read `.session_id` and `.result`, the
agy version reads `.conversation_id` and `.response`. Exit code is `0` on a
successful run and `1` on error (unknown model, invalid JSON, auth needed).

Environment variables are inherited by hook commands, so `HEARTBEAT=1` set by
`autonomous-action.sh` reaches `efpf-agy-hook` and the optional hooks.

## Hooks

`hooks.json` maps a hook name to event lists. `PreToolUse` and `PostToolUse`
are grouped under a `matcher` (a regex on the tool name; use `"*"` -- an empty
matcher did not fire `PostToolUse` in the measured run); `PreInvocation`,
`PostInvocation` and `Stop` are flat lists of handlers. Each handler is
`{"type": "command", "command": "<shell string>", "timeout": <seconds>}`; the
command runs via `sh -c` (`cmd /c` on Windows) with **the directory containing
`hooks.json` as its working directory**, so a workspace hook runs inside
`.agents/` and reaches the repository as `..`. The only environment variable
agy adds is `ANTIGRAVITY_CONVERSATION_ID`. Hooks read one JSON object on stdin
and print one on stdout; keys are camelCase.

Common input fields on every event:

```json
{"conversationId": "...", "workspacePaths": ["/path/to/embodied-agy"],
 "transcriptPath": "/home/u/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript_full.jsonl",
 "artifactDirectoryPath": "/home/u/.gemini/antigravity-cli/brain/<id>", "modelName": "gemini-3.8-flash-high"}
```

### Event mapping

| Claude Code event | Antigravity CLI event | Notes |
|-------------------|-----------------------|-------|
| `SessionStart` | `PreInvocation` with `invocationNum == 0`, first time a `conversationId` is seen | agy has no session event; the adapter keeps a marker per conversation |
| `UserPromptSubmit` | `PreInvocation` with `invocationNum == 0` | fires once per user turn; the prompt is read from the transcript |
| `PostToolBatch` | `PreInvocation` with `invocationNum > 0` | fires before every later model call in the turn, i.e. after each batch of tool calls |
| `PreToolUse` | `PreToolUse` | `toolCall.name` / `toolCall.args` instead of `tool_name` / `tool_input` |
| `PostToolUse` | `PostToolUse` with empty `error` | no tool response in the payload; read from the transcript by `stepIdx` |
| `PostToolUseFailure` | `PostToolUse` with non-empty `error` | |
| `Stop` | `Stop` | `terminationReason` is e.g. `NO_TOOL_CALL`; `executionNum` counts continuations |
| `StopFailure` | `Stop` with `error` or `terminationReason == "error"` | |
| `SessionStart(compact)` | -- | agy has no compaction event; `/recover-from-compact` is a skill |

### Payload and output shapes

`PreInvocation` / `PostInvocation` input adds `invocationNum` (0-indexed,
increments per model call within a turn) and `initialNumSteps`. Output:

```json
{"injectSteps": [{"ephemeralMessage": "text the model sees this invocation"}]}
```

`ephemeralMessage` is the equivalent of Claude Code's `additionalContext`;
`userMessage` is persisted as if the user typed it; `toolCall` injects a call.
`PostInvocation` may also answer `"terminationBehavior": "force_continue"`.

`PreToolUse` input adds `stepIdx` and `toolCall`:

```json
{"stepIdx": 9, "toolCall": {"name": "run_command",
 "args": {"CommandLine": "echo hi", "Cwd": "/path", "WaitMsBeforeAsync": 5000,
          "toolAction": "Running command", "toolSummary": "Run echo"}}}
```

Output: `{"decision": "allow" | "deny" | "ask" | "force_ask", "reason": "..."}`.
A `deny` reason is shown to the model, which continues with the next step.
`allow` bypasses the permission prompt (as in Claude Code); set
`EFPF_AGY_ALLOW_DECISION=ask` to keep agy's own prompts for allowed calls.

`PostToolUse` input is the same plus `error` (empty when the tool succeeded);
it does not fire for a denied call. Output: `{}`.

`Stop` input adds `executionNum`, `terminationReason`, `error`, `fullyIdle`.
Output `{"decision": "continue", "reason": "..."}` re-enters the loop and
injects the reason as a system message (this is Claude Code's
`{"decision": "block"}`); anything else lets the agent stop.

### Tool names

Built-in tools are lowercase snake_case: `run_command`, `view_file`,
`list_dir`, `grep_search`, `find_by_name`, `write_to_file`,
`replace_file_content`, `multi_replace_file_content`, `search_web`,
`read_url_content`, `browser_*`, `send_command_input`, `notify_user`,
`generate_image`. Every MCP call is one tool:

```json
{"name": "call_mcp_tool",
 "args": {"ServerName": "tts", "ToolName": "say", "Arguments": {"text": "..."}}}
```

`kernel_mcp.agy_tools.canonical_tool_call` maps these onto the
kernel's vocabulary (`Bash`, `Write`, `Edit`, `Read`, `mcp__<server>__<tool>`)
and drops `toolAction` / `toolSummary`, which the model rewrites every call.
The mapping is applied when an intention is proposed and when the hook sees
the call, so `propose_field_action` may be called with either spelling.

### Transcript

`transcript_full.jsonl` has one JSON object per step:

| `type` | `source` | carries |
|--------|----------|---------|
| `USER_INPUT` | `USER_EXPLICIT` | `content`: `<USER_REQUEST>\n...\n</USER_REQUEST>` followed by an `<ADDITIONAL_METADATA>` block |
| `PLANNER_RESPONSE` | `MODEL` | `tool_calls: [{"name", "args"}]` or the assistant `content` |
| `GENERIC` | `MODEL` | a tool result: `Created At: ...\nCompleted At: ...\n<output>`; its `step_index` is the `stepIdx` the hook received |
| `EPHEMERAL_MESSAGE` | `SYSTEM_SDK` | an injected `ephemeralMessage` |
| `SYSTEM_MESSAGE` | `SYSTEM` | e.g. `Stop hook blocked termination: <reason>` |

`kernel_mcp.agy_transcript` reads it; a missing or half-written
file yields `None`, never an exception.

## The kernel hooks (`.agents/hooks.json`)

`efpf-agy-hook <event>` is the adapter (`kernel_mcp.agy_hook_cli`),
installed by the workspace as a console script. The committed
`.agents/hooks.json` wires all four events through
`uv run --directory .. --package kernel-mcp efpf-agy-hook ...`.
`.agents/hooks.example.json` adds the optional sense hooks
(`interoception.sh`, `auto-recall.sh`, `auto-social.sh`, hearing) as a second,
disabled hook group to copy from. Those scripts follow the same protocol:
read the event JSON on stdin, print `{"injectSteps": [...]}` on
`PreInvocation` (and only when `invocationNum == 0` if they are per-turn), and
`{"decision": "continue", ...}` or `{}` on `Stop`.
