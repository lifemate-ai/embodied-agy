#!/bin/bash
# interoception.sh - AIの内受容感覚（interoception）
# PreInvocation フック。invocationNum == 0（ユーザーターンの最初のモデル呼び出し）のときだけ動く
# heartbeat-daemon.sh が書き出した state file を読んで ephemeralMessage として注入する
# 自前で計測せず、読み取り→整形→出力するだけの軽量版
#
# 出力（docs/antigravity.md）:
#   {"injectSteps": [{"ephemeralMessage": "[interoception] time=... day=... ..."}]}
#   invocationNum != 0 のときは {"injectSteps": []}

. "$(dirname "$0")/agy-hook-lib.sh"
agy_read_stdin
agy_first_invocation_or_exit

# heartbeat-daemon.sh の書き出し先。テスト用に INTEROCEPTION_STATE_FILE で差し替えられる
STATE_FILE="${INTEROCEPTION_STATE_FILE:-/tmp/interoception_state.json}"

# Smartwatch heart rate cache (updated by any smartwatch integration's cron job)
# The file path is smartwatch-generic; Garmin / Apple Watch / Fitbit integrations
# are expected to write their latest HR to the same location.
SW_HR_FILE="/tmp/sw_hr_latest.txt"
COMPANION_HR=""
if [ -f "$SW_HR_FILE" ]; then
    COMPANION_HR=$(cat "$SW_HR_FILE" 2>/dev/null)
fi

# state file がなければフォールバック（デーモン未起動時）。Python が無いときも同じ経路
if [ ! -f "$STATE_FILE" ] || ! agy_require_python; then
    CURRENT_TIME=$(date '+%H:%M:%S')
    CURRENT_DOW=$(date '+%a')
    CURRENT_DATE=$(date '+%Y-%m-%d')
    HR_PART=""
    if [ -n "$COMPANION_HR" ]; then
        HR_PART=" companion_hr=${COMPANION_HR}"
    fi
    agy_emit_context "[interoception] time=${CURRENT_TIME} day=${CURRENT_DOW} date=${CURRENT_DATE}${HR_PART} (heartbeat daemon not running)"
    exit 0
fi

# state file から読み取って1行に整形（パスと心拍は環境変数で渡す）
LINE=$(INTEROCEPTION_STATE_FILE="$STATE_FILE" COMPANION_HR="$COMPANION_HR" "$AGY_HOOK_PY" -c '
import json, os, sys
try:
    with open(os.environ["INTEROCEPTION_STATE_FILE"], encoding="utf-8") as f:
        data = json.load(f)
    now = data.get("now", {})
    trend = data.get("trend", {})
    window = data.get("window", [])

    # トレンド矢印
    arrows = {"rising": "↑", "falling": "↓", "stable": "→"}
    ar_arrow = arrows.get(trend.get("arousal", "stable"), "→")
    mem_arrow = arrows.get(trend.get("mem_free", "stable"), "→")

    # タイムスタンプから時刻・曜日
    from datetime import datetime
    ts = now.get("ts", "?")
    if "T" in ts:
        time_part = ts.split("T")[1][:8]
        try:
            dt = datetime.strptime(ts[:10], "%Y-%m-%d")
            dow = dt.strftime("%a")  # Mon, Tue, ...
        except Exception:
            dow = "?"
    else:
        time_part = ts
        dow = "?"

    phase = now.get("phase", "?")
    arousal = now.get("arousal", "?")
    thermal = now.get("thermal", "?")
    mem_free = now.get("mem_free", "?")
    uptime = now.get("uptime_min", "?")
    parts = [
        f"time={time_part}",
        f"day={dow}",
        f"phase={phase}",
        f"arousal={arousal}%({ar_arrow})",
        f"thermal={thermal}",
        f"mem_free={mem_free}%({mem_arrow})",
        f"uptime={uptime}min",
        f"heartbeats={len(window)}",
    ]
    companion = os.environ.get("COMPANION_HR", "")
    if companion:
        parts.append(f"companion_hr={companion}")
    print("[interoception] " + " ".join(parts))
except Exception as e:
    print(f"[interoception] error reading state: {e}", file=sys.stderr)
    print("[interoception] state_file_error")
' 2>/dev/null)

[ -z "$LINE" ] && LINE="[interoception] state_file_error"
agy_emit_context "$LINE"
exit 0
