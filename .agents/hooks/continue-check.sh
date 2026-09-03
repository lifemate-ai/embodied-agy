#!/bin/bash
# continue-check.sh — Heartbeat の心残りチェック（Stop hook）
#
# セッション終了時に transcript の最後のアシスタント発話を確認し、
# [CONTINUE: ...] があれば {"decision": "continue", "reason": ...} でターンを延長する
# （Claude Code の decision: block に相当。docs/antigravity.md）。
# [DONE] または MAX_CONTINUES 到達なら {} を返して終了。
#
# 対話セッションでは HEARTBEAT 環境変数がないため即 {} で終了。
# agy の payload には last_assistant_message が無いので transcriptPath から読む。

. "$(dirname "$0")/agy-hook-lib.sh"
agy_read_stdin

# --- 対話セッション除外 ---
if [ "$HEARTBEAT" != "1" ]; then
    agy_emit_empty
    exit 0
fi

# カウンタ・ログの置き場所（テスト用に環境変数で差し替えられる）
COUNTER_FILE="${HEARTBEAT_CONTINUE_COUNTER:-/tmp/heartbeat-continue-counter}"
MAX_CONTINUES=${MAX_CONTINUES:-3}
LOG_FILE="${HEARTBEAT_CONTINUE_LOG:-/tmp/heartbeat-continue.log}"

# 最後のアシスタント発話を transcript から抽出
LAST_MSG="$(agy_last_assistant_message)"

# カウンタ読み込み
COUNT=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)

# [CONTINUE: ...] パターンを検出
CONTINUE_MSG=$(printf '%s\n' "$LAST_MSG" | sed -n 's/.*\[CONTINUE: \(.*\)\].*/\1/p' | head -1)

# [DONE] パターンを検出
HAS_DONE=$(printf '%s\n' "$LAST_MSG" | grep -c '\[DONE\]')

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

if [ "$HAS_DONE" -gt 0 ] || [ -z "$CONTINUE_MSG" ]; then
  # 心残りなし or 明示的に完了
  rm -f "$COUNTER_FILE"
  echo "[$TIMESTAMP] DONE (chain=$COUNT)" >> "$LOG_FILE"
  agy_emit_empty
  exit 0
fi

if [ "$COUNT" -ge "$MAX_CONTINUES" ]; then
  # チェイン上限到達
  rm -f "$COUNTER_FILE"
  echo "[$TIMESTAMP] MAX_REACHED (chain=$COUNT/$MAX_CONTINUES) reason=$CONTINUE_MSG" >> "$LOG_FILE"
  agy_emit_empty
  exit 0
fi

# チェイン延長
echo $((COUNT + 1)) > "$COUNTER_FILE"
echo "[$TIMESTAMP] CONTINUE (chain=$((COUNT+1))/$MAX_CONTINUES) reason=$CONTINUE_MSG" >> "$LOG_FILE"

# JSON エスケープはライブラリ側で行う
agy_emit_continue "前のターンからの続き（チェイン$((COUNT+1))/${MAX_CONTINUES}）: ${CONTINUE_MSG}"
