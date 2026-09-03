#!/bin/bash
# cron 環境をシミュレートして autonomous-action.sh をテストする
# cron は最小限の環境変数しか持たない（$HOME, $PATH すらデフォルトでは存在しない）
# env -i で空の環境を作り、autonomous-action.sh が正しく動作するか確認
#
# Usage:
#   ./test-autonomous.sh                          # 通常Heartbeatをcron環境で実行
#   ./test-autonomous.sh --check-tools            # 全MCP/スキルの動作チェック
#   ./test-autonomous.sh --dry-run                # プロンプト確認（agy 実行なし）
#   ./test-autonomous.sh --dry-run --date "2026-02-20 03:00"   # 深夜帯のスケジュール確認
#   ./test-autonomous.sh --dry-run --date "2026-02-20 14:30"   # 昼間帯のスケジュール確認
#   ./test-autonomous.sh --dry-run --force-routine             # ルーチン回を強制確認
#   ./test-autonomous.sh --force-routine          # ルーチン回を強制実行

# スクリプトのディレクトリを取得（このファイルと autonomous-action.sh が同じディレクトリにある前提）
# 例: ~/embodied-agy/autonomous-action.sh
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SCRIPT_DIR/autonomous-action.sh"

# テスト結果の保存先（一時ディレクトリ）
# 例: /tmp/test_result/test_20260221_153000.log
RESULT_DIR="/tmp/test_result"
mkdir -p "$RESULT_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# --check-tools を探す（他の引数はそのまま autonomous-action.sh に渡す）
CHECK_TOOLS=false
PASSTHROUGH_ARGS=()

for arg in "$@"; do
  if [ "$arg" = "--check-tools" ]; then
    CHECK_TOOLS=true
  else
    PASSTHROUGH_ARGS+=("$arg")
  fi
done

if [ "$CHECK_TOOLS" = true ]; then
  # --check-tools: 全MCP/スキルの動作チェック用プロンプトを生成
  # autonomous-action.sh が --add-dir で載せるワークスペースの MCP と、agy の組み込みツールを順番に試す
  # （agy に allowedTools は無い。許可は --dangerously-skip-permissions、拒否は PreToolUse の意図ゲート）
  PROMPT_FILE="$RESULT_DIR/debug_prompt_${TIMESTAMP}.txt"
  cat > "$PROMPT_FILE" <<'PROMPT'
ツールの動作チェック。以下のツールを順番に1つずつ試して、結果をレポートせよ。
各ツールについて「OK」「NG（エラー内容）」「スキップ（理由）」を記録すること。

## チェックリスト

### ファイル操作（agy 組み込みツール）
# NOTE: ~/yourproject/ はサンプルパス。実際の環境に合わせて編集すること
1. view_file — ~/yourproject/SOUL.md を読む
2. write_to_file — ~/yourproject/test_write_check.txt に「write OK」と書く
3. replace_file_content — ~/yourproject/test_write_check.txt の内容を「edit OK」に変更
4. find_by_name — ~/yourproject/*.md を検索

# MCP は call_mcp_tool(ServerName, ToolName) で呼ぶ。以下は「サーバー名 / ツール名」
### MCP: wifi-cam
5. wifi-cam / see — カメラで1枚撮影
6. wifi-cam / look_left — 左を向く（10度）
7. wifi-cam / listen — 2秒間録音（文字起こし含む）
8. wifi-cam / camera_info — カメラ情報取得

### MCP: memory
9. memory / get_memory_stats — 統計取得
10. memory / recall_divergent — 「動作テスト」で検索
11. memory / get_working_memory — ワーキングメモリ取得

### MCP: tts
12. tts / say — 「テスト完了」と発声（VOICEVOX）

### MCP: system-temperature
13. system-temperature / get_current_time — 現在時刻取得

### MCP: sociality
14. sociality / get_social_state — 現在の social state を取得
15. sociality / get_person_model — kouta の person model を取得
16. sociality / get_current_joint_focus — joint focus を取得
17. sociality / get_quiet_mode_state — quiet mode 状態を取得
18. sociality / get_self_summary — 自己要約を取得

### スキル
19. /read — /read https://example.com をテスト（--info のみ）

### コマンド実行
20. run_command — bun --version を実行

## レポート形式

最後に以下の形式でサマリーを出力すること：

```
=== ツール動作チェック結果 ===
1. view_file:            OK/NG
2. write_to_file:        OK/NG
3. replace_file_content: OK/NG
...
=== 合計: X/20 OK ===
```
PROMPT

  echo "=== ツール動作チェック ==="
  echo "プロンプト: $PROMPT_FILE"
  echo "結果出力先: $RESULT_DIR/"
  echo ""

  # env -i: 空の環境で bash を起動（cron 環境をシミュレート）
  # autonomous-action.sh 内で $HOME, $PATH を再設定するため動作する
  env -i bash -c "'$SCRIPT' --test-prompt '$PROMPT_FILE'" 2>&1 | tee "$RESULT_DIR/check_tools_${TIMESTAMP}.log"
  EXIT_CODE=$?

else
  # 引数をそのまま autonomous-action.sh に渡す（--dry-run, --date など）
  echo "=== cron環境シミュレート実行 ==="
  echo "スクリプト: $SCRIPT"
  echo "引数: ${PASSTHROUGH_ARGS[*]}"
  echo ""

  # 引数を正しくクォートして渡す（スペース含む引数も正しく処理）
  ARGS_STR=""
  for arg in "${PASSTHROUGH_ARGS[@]}"; do
    ARGS_STR="$ARGS_STR '$arg'"
  done

  # env -i: 空の環境で bash を起動
  env -i bash -c "'$SCRIPT' $ARGS_STR" 2>&1 | tee "$RESULT_DIR/test_${TIMESTAMP}.log"
  EXIT_CODE=$?
fi

echo ""
echo "=== 終了 (exit: $EXIT_CODE) ==="
echo "--- 最新の自律行動ログ ---"
# autonomous-action.sh が生成したログファイルを SCRIPT_DIR ベースで表示
ls -t "$SCRIPT_DIR/.autonomous-logs/"*.log 2>/dev/null | head -1 | xargs cat 2>/dev/null
