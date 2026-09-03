#!/bin/bash
# agy-hook-lib.sh — Antigravity CLI (agy) フック共通ライブラリ（source して使う）
#
# agy のフックは stdin に JSON を 1 つ受け取り、stdout に JSON を 1 つ返す
# （契約は docs/antigravity.md。agy 1.1.25 で実測）。Claude Code と違って
# payload に prompt / last_assistant_message は入っておらず、transcriptPath の
# JSONL から読む。このファイルはその共通部分をまとめたもの。
#
# 使い方:
#   . "$(dirname "$0")/agy-hook-lib.sh"
#   agy_read_stdin                 # stdin を一度だけ $AGY_HOOK_INPUT に読む
#   agy_first_invocation_or_exit   # PreInvocation: invocationNum != 0 なら {"injectSteps": []} を出して exit 0
#   PROMPT="$(agy_user_prompt)"    # transcript の最後の USER_INPUT（<USER_REQUEST> を剥がしたもの）
#   agy_emit_context "[tag] text"  # {"injectSteps": [{"ephemeralMessage": "[tag] text"}]}
#
# 提供する関数:
#   agy_find_python              動く Python を探して名前を出力
#                                （AGY_HOOK_PYTHON / HEARING_PYTHON → python3 → python）
#   agy_require_python           $AGY_HOOK_PY に動く Python を入れる（無ければ 1 を返す）
#   agy_python                   $AGY_HOOK_PY を出力（未設定なら探す）
#   agy_read_stdin               stdin を $AGY_HOOK_INPUT に読み込む（export される）
#   agy_payload_field KEY        payload のトップレベル値を出力（文字列以外は JSON で）
#   agy_invocation_num           invocationNum（無い・数値でないときは 0）
#   agy_conversation_id          conversationId（無ければ $ANTIGRAVITY_CONVERSATION_ID）
#   agy_transcript_path          transcriptPath
#   agy_first_invocation_or_exit invocationNum != 0 なら {"injectSteps": []} を出して exit 0
#   agy_user_prompt              transcript の最後の USER_INPUT の中身（ラッパーを剥がしたもの）
#   agy_last_assistant_message   transcript の最後の MODEL / PLANNER_RESPONSE の content
#   agy_json_string TEXT         TEXT を JSON 文字列リテラルにして出力
#   agy_emit_context TEXT        {"injectSteps": [{"ephemeralMessage": TEXT}]}（TEXT が空なら injectSteps: []）
#   agy_emit_no_context          {"injectSteps": []}
#   agy_emit_continue REASON     {"decision": "continue", "reason": REASON}（Claude Code の decision: block に相当）
#   agy_emit_empty               {}
#
# 移植性メモ:
#   - Python 内に "/tmp/..." を直接書かない（Windows Git Bash では Path("/tmp") が
#     カレントドライブ直下を指す）。パスは必ずシェル側で解決して環境変数で渡す。
#   - python3 は Microsoft Store のエイリアスに取られていることがあるので、
#     実際に "import sys" が通るインタプリタを探す。
#   - Windows の Python は既定で stdout をロケール（cp932 等）で扱うので UTF-8 モードを強制する
#     （POSIX では実質無変化）。
#   - 文字列は argv ではなく環境変数（AGY_HOOK_TEXT 等）で Python に渡す。

export PYTHONUTF8=1

# ── 動く Python を選ぶ ───────────────────────────────────────────────────────
# AGY_HOOK_PYTHON（または hearing フック互換の HEARING_PYTHON）が設定されていればそれだけを試す。
# なければ python3 → python の順で "import sys" が通る最初のものを採用する
# （Store のエイリアスは終了コード 49 で弾かれる）。
agy_find_python() {
    local candidate explicit
    explicit="${AGY_HOOK_PYTHON:-${HEARING_PYTHON:-}}"
    if [ -n "$explicit" ]; then
        if "$explicit" -c "import sys" >/dev/null 2>&1; then
            printf '%s\n' "$explicit"
            return 0
        fi
        return 1
    fi
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c "import sys" >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# サブシェルを使わずに $AGY_HOOK_PY を埋める（スクリプト冒頭で一度呼べば以降は探し直さない）
agy_require_python() {
    [ -n "${AGY_HOOK_PY:-}" ] && return 0
    local found
    found="$(agy_find_python)" || return 1
    AGY_HOOK_PY="$found"
}

agy_python() {
    agy_require_python || return 1
    printf '%s\n' "$AGY_HOOK_PY"
}

# ── stdin ────────────────────────────────────────────────────────────────────
# stdin は一度しか読めないので、最初に丸ごと $AGY_HOOK_INPUT に入れる
agy_read_stdin() {
    if [ -z "${AGY_HOOK_INPUT_READ:-}" ]; then
        AGY_HOOK_INPUT="$(cat 2>/dev/null)"
        AGY_HOOK_INPUT_READ=1
    fi
    export AGY_HOOK_INPUT
}

# ── payload のフィールド ─────────────────────────────────────────────────────
agy_payload_field() {
    local py
    py="$(agy_python)" || return 1
    AGY_HOOK_INPUT="${AGY_HOOK_INPUT:-}" AGY_HOOK_KEY="$1" "$py" -c '
import json, os, sys
try:
    payload = json.loads(os.environ.get("AGY_HOOK_INPUT") or "{}")
except ValueError:
    payload = {}
if not isinstance(payload, dict):
    payload = {}
value = payload.get(os.environ.get("AGY_HOOK_KEY", ""))
if value is None:
    value = ""
sys.stdout.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
' 2>/dev/null
}

agy_invocation_num() {
    local n
    n="$(agy_payload_field invocationNum)"
    case "$n" in
        ''|*[!0-9]*) printf '0\n' ;;   # 無い・数値でない → ターンの最初の呼び出しとして扱う
        *) printf '%s\n' "$n" ;;
    esac
}

agy_conversation_id() {
    local id
    id="$(agy_payload_field conversationId)"
    printf '%s\n' "${id:-${ANTIGRAVITY_CONVERSATION_ID:-}}"
}

agy_transcript_path() {
    agy_payload_field transcriptPath
}

# PreInvocation はターン内のモデル呼び出しごとに発火する。ユーザーターンごとに 1 回だけ
# 動きたいフックは invocationNum == 0 のときだけ本処理をする。
agy_first_invocation_or_exit() {
    if [ "$(agy_invocation_num)" != "0" ]; then
        agy_emit_no_context
        exit 0
    fi
}

# ── transcript ───────────────────────────────────────────────────────────────
# transcript_full.jsonl は 1 行 1 ステップ。読めない・壊れている行は黙って飛ばす
# （kernel_mcp.agy_transcript と同じ規則）。
_AGY_TRANSCRIPT_PY='
import json, os, re, sys

path = os.environ.get("AGY_HOOK_TRANSCRIPT") or ""
want = os.environ.get("AGY_HOOK_WANT") or "prompt"

def steps():
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out

USER_REQUEST = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)
TRAILING_BLOCK = re.compile(r"\s*<[A-Z_]+>.*\Z", re.DOTALL)

def unwrap(content):
    m = USER_REQUEST.search(content)
    if m:
        return m.group(1).strip()
    return TRAILING_BLOCK.sub("", content).strip()

text = ""
for step in reversed(steps()):
    if want == "prompt":
        if step.get("type") == "USER_INPUT":
            content = step.get("content")
            text = unwrap(content) if isinstance(content, str) else ""
            break
    else:
        if step.get("source") == "MODEL" and step.get("type") == "PLANNER_RESPONSE":
            content = step.get("content")
            if isinstance(content, str) and content.strip():
                text = content
                break
sys.stdout.write(text)
'

_agy_transcript_read() {
    local py
    py="$(agy_python)" || return 1
    AGY_HOOK_TRANSCRIPT="$(agy_transcript_path)" AGY_HOOK_WANT="$1" \
        "$py" -c "$_AGY_TRANSCRIPT_PY" 2>/dev/null
}

# 最後のユーザー入力（<USER_REQUEST>...</USER_REQUEST> の中身。後続の <ADDITIONAL_METADATA> 等は捨てる）
agy_user_prompt() {
    _agy_transcript_read prompt
}

# 最後のアシスタント発話（Claude Code の last_assistant_message に相当）
agy_last_assistant_message() {
    _agy_transcript_read assistant
}

# ── 出力 ─────────────────────────────────────────────────────────────────────
# Python が無いときの最低限の JSON 文字列化（\ " 改行 タブ CR だけ）
_agy_json_string_fallback() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\t'/\\t}"
    s="${s//$'\r'/\\r}"
    printf '"%s"\n' "$s"
}

agy_json_string() {
    local py
    if py="$(agy_python)"; then
        AGY_HOOK_TEXT="$1" "$py" -c 'import json, os; print(json.dumps(os.environ.get("AGY_HOOK_TEXT", ""), ensure_ascii=False))' 2>/dev/null && return 0
    fi
    _agy_json_string_fallback "$1"
}

agy_emit_no_context() {
    printf '{"injectSteps": []}\n'
}

agy_emit_context() {
    if [ -z "$1" ]; then
        agy_emit_no_context
        return 0
    fi
    printf '{"injectSteps": [{"ephemeralMessage": %s}]}\n' "$(agy_json_string "$1")"
}

agy_emit_continue() {
    printf '{"decision": "continue", "reason": %s}\n' "$(agy_json_string "$1")"
}

agy_emit_empty() {
    printf '{}\n'
}
