#!/usr/bin/env python3
"""hearing-daemon は別リポジトリ lifemate-ai/embodied-codex の hearing/ に移動しました。

    https://github.com/lifemate-ai/embodied-codex  →  hearing/

そこにある MCP サーバーの start_listening / stop_listening ツールで聞き耳を
開始・停止します（wifi-cam-mcp にはこれらのツールはありません）。
このリポジトリの hearing-hook.sh / hearing-stop-hook.sh（Antigravity CLI の
PreInvocation / Stop フック）は、その hearing が $HEARING_DIR（既定 /tmp）の
hearing_buffer.jsonl に書き込んだものを読む側としてそのまま使われます。
"""
raise SystemExit(
    "hearing-daemon は lifemate-ai/embodied-codex の hearing/ に移行しました。\n"
    "https://github.com/lifemate-ai/embodied-codex の hearing MCP サーバーで "
    "start_listening を呼んで聞き耳を開始してください。"
)
