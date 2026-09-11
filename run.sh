#!/bin/bash
set -e

# Add static ffmpeg to PATH if available
python3 -c "import static_ffmpeg; static_ffmpeg.add_paths()" 2>/dev/null || true

PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}

echo "======================================================="
echo "   🚀 Starting Google Drive to Voice Converter UI     "
echo "   Access via: http://localhost:$PORT                  "
echo "======================================================="

exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
