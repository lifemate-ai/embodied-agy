---
name: consolidate
description: >-
  Run the sleep-consolidation glue manually. Quiet-hours-gated by default;
  pass `force` to bypass. Writes `~/.gemini/morning_briefing.json` for the
  next first-session-of-day to surface. Use it to trigger an off-cycle
  briefing, to verify the scheduler glue after a config change, or to preview
  the next morning injection.
---

# /consolidate

Phase 2.1 hook into `kernel-mcp.sleep_consolidate`.

Arguments: the text typed after `/consolidate` — `force` and/or `dry_run`
(see below).

## When to use this

- **Manually trigger an off-cycle briefing**: e.g. you just had a long
  conversation and want the counterfactual journal summarized before going
  to bed, even though it's not strictly quiet hours.
- **Verify the scheduler glue works after a config change**: dry-run mode
  builds the briefing without touching `morning_briefing.json`.
- **Debugging**: confirm what the next first-session-of-day MORNING_PROMPT
  injection will look like.

## Behavior

Default invocation: call `mcp__kernel__sleep_consolidate()`.

- If the wrapped quiet-hours predicate accepts the current timestamp, the
  briefing is assembled from the last 24h of counterfactuals +
  interpretation shifts and written to `~/.gemini/morning_briefing.json`.
- If not in quiet hours, the call is **skipped** and returns
  `{ran: false, skipped_reason: ...}`.

Argument forms (pass to the tool as flags):

- `force` → bypass quiet-hours gate.
- `dry_run` → assemble the briefing but do not write to disk.

## What it does NOT do (Phase 2.1)

- Does not call memory-mcp `consolidate_memories` or `recall_divergent`
  yet — those engines are wired in a later phase.
- Does not write any `daybook` entry; `append_daybook` stays manual until
  Phase 2.2 ships the consciousness-tick loop.

## Vocabulary discipline

The `consciousness-mcp` package follows functional-only language in
technical artifacts (see `consciousness-mcp/AGENTS.md`). When invoking
this skill, treat the output as **structured records of attention,
deliberation, and counterfactual responsibility** — not as phenomenal
self-report. Kokone's own first-person voice is unaffected; she can
react to a briefing in-character without changing the technical claim.
