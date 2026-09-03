#!/bin/bash
# auto-social.sh - 自動社会的イベント注入
# PreInvocation フック。invocationNum == 0（ユーザーターンごとに1回）のときだけ動く
# transcript の最後のユーザー入力（コンパニオンの発話）を sociality DB に直接 INSERT する
#
# コンテキストは注入しないので出力は常に {"injectSteps": []}（docs/antigravity.md）
# person_id は COMPANION_ID（既定: kouta）

SOCIAL_DB="$HOME/.gemini/sociality/social.db"
PERSON_ID="${COMPANION_ID:-kouta}"

. "$(dirname "$0")/agy-hook-lib.sh"
agy_read_stdin
agy_first_invocation_or_exit

# DB存在チェック
if [ ! -f "$SOCIAL_DB" ]; then
    agy_emit_no_context
    exit 0
fi

# Python が無ければ何もしない
agy_require_python || { agy_emit_no_context; exit 0; }

# ユーザー入力は payload には無いので transcript から読む
USER_INPUT="$(agy_user_prompt)"

# 入力が空か短すぎたらスキップ
if [ -z "$USER_INPUT" ] || [ ${#USER_INPUT} -lt 3 ]; then
    agy_emit_no_context
    exit 0
fi

# 自動ループのプロンプトはスキップ
case "$USER_INPUT" in
    *"好きなことをいっぱいして"*) agy_emit_no_context; exit 0 ;;
    *"深呼吸や瞑想"*) agy_emit_no_context; exit 0 ;;
    *"Twitter/X"*) agy_emit_no_context; exit 0 ;;
    *"外の景色を見る"*) agy_emit_no_context; exit 0 ;;
    *"Awareness of Awareness"*) agy_emit_no_context; exit 0 ;;
    *"青空文庫"*) agy_emit_no_context; exit 0 ;;
    *"記憶を整理する"*) agy_emit_no_context; exit 0 ;;
esac

# Generate event_id and timestamp
TS=$(date -u '+%Y-%m-%dT%H:%M:%S+00:00')
CREATED_AT="$TS"
EVENT_ID="evt_$(printf '%s' "${TS}${USER_INPUT}" | shasum -a 1 | cut -c1-16)"
PAYLOAD=$(AGY_HOOK_TEXT="$USER_INPUT" "$AGY_HOOK_PY" -c 'import json, os; print(json.dumps({"text": os.environ.get("AGY_HOOK_TEXT", "")}))' 2>/dev/null)

if [ -z "$PAYLOAD" ]; then
    agy_emit_no_context
    exit 0
fi

# SQL の文字列リテラル用に ' を '' にする（発話にアポストロフィがあっても INSERT が壊れないように）
PAYLOAD_SQL=$(printf '%s' "$PAYLOAD" | sed "s/'/''/g")
PERSON_SQL=$(printf '%s' "$PERSON_ID" | sed "s/'/''/g")

# Direct INSERT into SQLite
sqlite3 "$SOCIAL_DB" "INSERT OR IGNORE INTO events (event_id, ts, source, kind, person_id, confidence, payload_json, created_at) VALUES ('$EVENT_ID', '$TS', 'hook', 'human_utterance', '$PERSON_SQL', 1.0, '$PAYLOAD_SQL', '$CREATED_AT');" 2>/dev/null

agy_emit_no_context
exit 0
