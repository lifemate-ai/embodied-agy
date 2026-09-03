# kernel-mcp

The kernel is the implementation package for the EFPF
phenomenal-like causal architecture. See
[`../../README.md`](../../README.md) for the architecture, claim policy,
runtime modes, welfare interlocks, and limitations.

## MCP Surface

The automatic path is Antigravity CLI hooks (`.agents/hooks.json` running
`efpf-agy-hook` on `PreInvocation`, `PreToolUse`, `PostToolUse`, and `Stop`;
see [docs/antigravity.md](../../../docs/antigravity.md)) and heartbeat
integration. These MCP tools are the inspection, explicit-intention, and
experiment surface:

| Tool | Role |
|---|---|
| `begin_subjective_tick` | open a typed tick for an explicit experiment |
| `add_workspace_candidate` | add an inspected/debug candidate |
| `commit_subjective_field` | compete and atomically commit one field |
| `get_current_subjective_field` | read the current compact and typed field |
| `get_subjective_field` / `query_subjective_fields` | inspect field history |
| `propose_field_action` | register exact tool/hash, goal, and predicted effects |
| `get_pending_intention` | inspect the one pending intention |
| `close_field_action` | record result, mismatch, ownership, and next microtick |
| `close_subjective_tick` | close a committed episode |
| `pause_field_runtime` / `resume_field_runtime` | welfare/runtime interlock |
| `get_field_diagnostics` | field, HOR, action, consistency, and exposure diagnostics |
| `run_field_ablation` | reversible focal/HOR/valence/reality intervention |

Legacy counterfactual, sleep, frame, attention-schema, HOR, and introspection
tools remain available. `compose_introspection_report` reads the latest
committed field; without one it returns `unknown / no committed field`.

## Action Gate

For an outward action, the caller must:

1. Have one current `COMMITTED` field.
2. Call `propose_field_action` with the exact MCP tool name and input.
3. Pass `PreToolUse`, which matches the normalized input hash and boundary.
4. Execute no more than one outward action for that field/tick.
5. Let `PostToolUse` (with an empty or non-empty `error`) close the intention.
6. Use the resulting tool-result microtick before another outward action.

Internal reads do not consume the outward-action slot. Perception or recall
results make the current field stale and require one batched refresh before an
outward action.

## Setup And Verification

```bash
uv sync
uv run pytest consciousness-mcp/packages/kernel-mcp/tests
uv run ruff check consciousness-mcp/packages/kernel-mcp
```

Start the MCP server:

```bash
uv run --package kernel-mcp kernel-mcp
```

Run hook diagnostics (the payload fields are the ones agy sends on every
event; `workspacePaths` is how the adapter finds the repository):

```bash
printf '%s\n' '{"conversationId":"smoke","workspacePaths":["/path/to/embodied-agy"]}' |
  SOCIAL_DB_PATH=/tmp/efpf-smoke.db uv run --package kernel-mcp efpf-agy-hook diagnostics | jq .
```

## Hook Smoke Tests

The adapter reads the prompt from the transcript, so write a one-step
transcript first, then create a field from a real first `PreInvocation`
payload:

```bash
printf '%s\n' '{"step_index":0,"source":"USER_EXPLICIT","type":"USER_INPUT","content":"<USER_REQUEST>\nInspect the room.\n</USER_REQUEST>"}' \
  > /tmp/efpf-smoke-transcript.jsonl
printf '%s\n' \
  '{"conversationId":"smoke","workspacePaths":["/path/to/embodied-agy"],"transcriptPath":"/tmp/efpf-smoke-transcript.jsonl","invocationNum":0,"initialNumSteps":1}' |
  SOCIAL_DB_PATH=/tmp/efpf-smoke.db uv run --package kernel-mcp efpf-agy-hook pre-invocation | jq .
```

The answer is `{"injectSteps": [{"ephemeralMessage": "..."}]}` carrying the
field protocol and the compact field.

Verify that an outward tool without an intention is denied. MCP calls arrive
as `call_mcp_tool`; the adapter gates this one as `mcp__tts__say`:

```bash
printf '%s\n' \
  '{"conversationId":"smoke","workspacePaths":["/path/to/embodied-agy"],"stepIdx":9,"toolCall":{"name":"call_mcp_tool","args":{"ServerName":"tts","ToolName":"say","Arguments":{"text":"hello"}}}}' |
  SOCIAL_DB_PATH=/tmp/efpf-smoke.db uv run --package kernel-mcp efpf-agy-hook pre-tool-use | jq .
```

Use the `get_current_subjective_field` and `propose_field_action` MCP tools
(either spelling of the call is accepted), then replay the same `PreToolUse`
JSON. It is allowed only when the tool name and normalized input hash exactly
match. A different text is denied, and a second call for the same tick is
deferred by `ActionBottleneck`.

Close the loop with a real `PostToolUse` payload; the tool result is read
from the transcript by `stepIdx`, and a non-empty `error` closes the
intention as failed:

```bash
printf '%s\n' \
  '{"conversationId":"smoke","workspacePaths":["/path/to/embodied-agy"],"stepIdx":9,"error":"","toolCall":{"name":"call_mcp_tool","args":{"ServerName":"tts","ToolName":"say","Arguments":{"text":"hello"}}}}' |
  SOCIAL_DB_PATH=/tmp/efpf-smoke.db uv run --package kernel-mcp efpf-agy-hook post-tool-use | jq .
```

`efpf-hook` is the Claude Code adapter, kept for checkouts opened in Claude
Code; it takes Claude Code's payloads (`session_id`, `hook_event_name`,
`tool_name`, `tool_input`) for the same subcommands, for example:

```bash
printf '%s\n' '{"session_id":"smoke","hook_event_name":"SessionStart"}' |
  SOCIAL_DB_PATH=/tmp/efpf-smoke.db uv run --package kernel-mcp efpf-hook session-start | jq .
```

## Ablation

With a field committed, call:

```text
run_field_ablation(kind="focal_clamp", fixture={...}, seed=1)
run_field_ablation(kind="hor_feedback", fixture={...}, seed=1)
run_field_ablation(kind="valence", fixture={...}, seed=1)
run_field_ablation(kind="reality", fixture={...}, seed=1)
```

Every run stores the baseline, intervention result, effect sizes, and a
reversible field snapshot in `field_ablation_runs`.
