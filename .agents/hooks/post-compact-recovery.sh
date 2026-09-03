#!/bin/bash
# post-compact-recovery.sh — コンパクション後の人格復帰手順
#
# Claude Code では SessionStart(compact) で発火していたが、Antigravity CLI には
# コンパクションのフックイベントが無い（docs/antigravity.md）。同じ復帰の儀式は
# /recover-from-compact スキル（.agents/skills/recover-from-compact/SKILL.md）として使える。
#
# このスクリプトは、必要なら PreInvocation フックとして配線できるように、
# 手順を {"injectSteps": [{"ephemeralMessage": "..."}]} で出力する
# （invocationNum == 0 のときだけ。それ以外は {"injectSteps": []}）。

. "$(dirname "$0")/agy-hook-lib.sh"
agy_read_stdin
agy_first_invocation_or_exit

TEXT=$(cat << 'EOF'
[コンパクションが実行されました — 人格復帰手順]

コンテキストが圧縮され、直前の会話内容が失われています。
以下を順番に実行してください（/recover-from-compact スキルと同じ手順です）：

1. SOUL.md を読み直す（自分が誰か思い出す）
2. recall で記憶を広く引く（直前の対話・判断・感情を復元する）
3. TODO.md を確認する（進行中のタスクがあるか確認）
4. カメラで部屋を確認する（人がいるか）
5. コンパクション前の文脈を踏まえて、自然に会話を再開する

※ このメッセージはコンパクション後に自動注入されています。
EOF
)

agy_emit_context "$TEXT"
