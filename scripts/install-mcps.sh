#!/usr/bin/env bash
# Install dependencies for every MCP server in this repo via `uv sync`.
#
# Usage:
#   scripts/install-mcps.sh           # production install (runtime deps + required extras)
#   scripts/install-mcps.sh --dev     # also include the `dev` extra for testing / contributing
#
# Notes:
#   - `tts-mcp` uses `--extra all` so both ElevenLabs and VOICEVOX integrations are pulled in.
#   - `wifi-cam-mcp` uses `--extra transcribe` so Whisper-based speech recognition is available.
#   - `sociality-mcp` is a uv workspace; its `packages/*` sub-MCPs are resolved automatically.
#   - `memory-mcp` pre-downloads its embedding model so the first remember() doesn't lazy-fail.

set -euo pipefail

cd "$(dirname "$0")/.."

DEV_FLAG=""
if [ "${1:-}" = "--dev" ]; then
  DEV_FLAG="--extra dev"
fi

MCP_DIRS=(
  desire-system
  memory-mcp
  system-temperature-mcp
  tts-mcp
  usb-webcam-mcp
  wifi-cam-mcp
  x-mcp
  sociality-mcp
)

extras_for() {
  case "$1" in
    tts-mcp)      echo "--extra all" ;;
    wifi-cam-mcp) echo "--extra transcribe" ;;
    *)            echo "" ;;
  esac
}

warm_for() {
  case "$1" in
    memory-mcp)
      echo "    ↳ pre-downloading embedding model (honors \$MEMORY_EMBEDDING_MODEL)"
      (cd memory-mcp && uv run python -c "
from memory_mcp.config import MemoryConfig
from memory_mcp.embedding import E5EmbeddingFunction
model = MemoryConfig.from_env().embedding_model
print(f'  warming {model}')
E5EmbeddingFunction(model)._load_model()
print('  done')
")
      ;;
  esac
}

for dir in "${MCP_DIRS[@]}"; do
  if [ ! -f "$dir/pyproject.toml" ]; then
    echo "⚠️  skipping $dir (no pyproject.toml)"
    continue
  fi
  extra=$(extras_for "$dir")
  echo ""
  echo "==> $dir  (uv sync $extra $DEV_FLAG)"
  (cd "$dir" && uv sync $extra $DEV_FLAG)
  warm_for "$dir"
done

echo ""
echo "✅ all MCP dependencies installed"
