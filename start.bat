@echo off
title newsbox
echo ================================================
echo  newsbox dashboard
echo  http://localhost:8000
echo ================================================
echo.
echo Starting server... browser opens in ~6s.
echo Close this window to stop.
echo.
:: Raw news data location: default is ..\data (sibling of project root).
:: Override below if your data is elsewhere.
start "" /min powershell -WindowStyle Hidden -Command "Start-Sleep 6; Start-Process 'http://localhost:8000'"
wsl bash -lc "cd $(wslpath -a '%~dp0'); fuser -k 8000/tcp 2>/dev/null; sleep 1; export NEWSBOX_RAW_DIR=$(wslpath -a '%~dp0..\data'); .venv/bin/python panel/server.py"
echo.
echo Server stopped.
pause
