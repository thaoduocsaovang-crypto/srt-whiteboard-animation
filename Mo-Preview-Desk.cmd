@echo off
set "ROOT=%~dp0"
start "SRT Whiteboard Animation Server" /B "%ROOT%.venv\Scripts\python.exe" "%ROOT%scripts\gui_server.py" >nul 2>&1
ping -n 2 127.0.0.1 >nul
start "SRT Whiteboard Animation - Preview Desk" "http://127.0.0.1:8765/assets/preview.html"
