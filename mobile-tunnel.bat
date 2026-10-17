@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo   Starting HTTPS Tunnel for Mobile Phone Testing
echo ===================================================
echo.
echo Forwarding port 8000 to public HTTPS URL...
echo Look for the URL ending with '.trycloudflare.com' below.
echo.

npx.cmd cloudflared tunnel --url http://localhost:8000
pause
