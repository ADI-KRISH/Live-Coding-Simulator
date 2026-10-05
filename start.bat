@echo off
rem Starts Livecode with Docker and opens it in the browser. Double-click to run.
rem Stop it with:  docker compose down
cd /d "%~dp0"

docker info >nul 2>&1
if errorlevel 1 (
    echo Docker is not running. Start Docker Desktop, wait until it says "Engine running", then run this again.
    pause
    exit /b 1
)

rem The app reads its settings (API keys) from .env. Create it on first run.
if not exist .env copy .env.example .env >nul

echo Building and starting Livecode. The first run takes a few minutes...
docker compose up --build -d
if errorlevel 1 (
    echo.
    echo Livecode did not start. Read the error above. If port 8000 is busy, close whatever is using it.
    pause
    exit /b 1
)

echo Waiting for the server...
for /l %%i in (1,1,30) do (
    curl -s -o nul http://localhost:8000/api/health && goto ready
    ping -n 2 127.0.0.1 >nul
)
echo The server did not answer within 30 seconds. Check it with:  docker compose logs app
pause
exit /b 1

:ready
echo Livecode is running at http://localhost:8000
start "" http://localhost:8000
