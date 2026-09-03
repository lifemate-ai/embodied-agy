#!/bin/bash
# auto-recall.sh - 自動連想想起
exec 2>/tmp/auto-recall-debug.log
# PreInvocation フック。invocationNum == 0（ユーザーターンごとに1回）のときだけ動く
# transcript の最後のユーザー入力から memory-mcp の HTTP エンドポイントで関連記憶を検索し、
# ephemeralMessage として注入する（docs/antigravity.md）
#
# 出力: {"injectSteps": [{"ephemeralMessage": "[associative_recall] ..."}]}
#       注入するものが無いときは {"injectSteps": []}

MEMORY_HTTP_PORT="${MEMORY_HTTP_PORT:-18900}"

. "$(dirname "$0")/agy-hook-lib.sh"
agy_read_stdin
agy_first_invocation_or_exit

# Python が無ければ何もしない
agy_require_python || { agy_emit_no_context; exit 0; }

# ユーザー入力は payload には無いので transcript から読む
USER_INPUT="$(agy_user_prompt)"

# 入力が空か短すぎたらスキップ
if [ -z "$USER_INPUT" ] || [ ${#USER_INPUT} -lt 5 ]; then
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

# URL encode the query（文字列は環境変数で渡す）
ENCODED=$(AGY_HOOK_TEXT="$USER_INPUT" "$AGY_HOOK_PY" -c 'import urllib.parse, os; print(urllib.parse.quote(os.environ.get("AGY_HOOK_TEXT", "")))' 2>/dev/null)

if [ -z "$ENCODED" ]; then
    agy_emit_no_context
    exit 0
fi

# memory-mcp HTTP endpoint に問い合わせ（タイムアウト3秒）
RESULT=$(curl -s --max-time 3 "http://127.0.0.1:${MEMORY_HTTP_PORT}/recall?q=${ENCODED}&n=2" 2>/dev/null)

# 結果が空か [] ならスキップ
if [ -z "$RESULT" ] || [ "$RESULT" = "[]" ]; then
    agy_emit_no_context
    exit 0
fi

echo "DEBUG: USER_INPUT='$USER_INPUT' ENCODED='$ENCODED' RESULT='$RESULT'" >&2
agy_emit_context "[associative_recall] $RESULT"
