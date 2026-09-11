#!/bin/bash
set -e

echo "🔍 Checking environment..."

# 1. Install dependencies if not already present
if ! python3 -c "import fastapi, edge_tts, static_ffmpeg" 2>/dev/null; then
    echo "📦 Installing required Python dependencies..."
    pip install -r requirements.txt
fi

# 2. Add static ffmpeg to PATH
python3 -c "import static_ffmpeg; static_ffmpeg.add_paths()" 2>/dev/null || true

PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}

echo "======================================================="
echo "   🚀 DriveVoice AI Web Studio is starting!          "
echo "   Local URL:  http://localhost:$PORT                  "
if [ -n "$CODESPACE_NAME" ]; then
    echo "   Codespaces: Port $PORT is available in Ports tab   "
fi
echo "======================================================="

exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload --timeout-keep-alive 75
