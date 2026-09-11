@echo off
echo =======================================================
echo    DriveVoice AI - Windows Launcher
echo =======================================================

echo Checking Python dependencies...
python -c "import fastapi, edge_tts, static_ffmpeg" 2>nul
if %errorlevel% neq 0 (
    echo Installing required packages...
    pip install -r requirements.txt
)

echo Initializing FFmpeg...
python -c "import static_ffmpeg; static_ffmpeg.add_paths()" 2>nul

echo.
echo =======================================================
echo    Starting DriveVoice AI Studio
echo    Open in Browser: http://localhost:8000
echo =======================================================
echo.

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --timeout-keep-alive 75
pause
