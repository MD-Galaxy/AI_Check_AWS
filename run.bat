@echo off
REM Double-click this file to start EmailPOC on Windows (no "make" required).
REM Requires Docker Desktop to be installed and running.

if not exist .env (
    copy .env.docker.example .env >nul
    echo.
    echo Created .env from .env.docker.example
    echo Open .env in Notepad and fill in: SECRET_KEY, INBOUND_DOMAIN, FROM_EMAIL,
    echo ENGAGELAB_API_USER, ENGAGELAB_API_KEY -- then double-click run.bat again.
    echo.
    pause
    exit /b 1
)

docker compose up -d --build
echo.
echo EmailPOC + Bedrock Availability POC are starting. Give it a few seconds,
echo then open http://localhost:8000 (or the APP_PORT you set in .env) in your
echo browser.
pause
