@echo off
title HealthPrice Monitor
echo.
echo  HealthPrice Monitor - Iniciando servidor...
echo  Acesse: http://localhost:5000
echo.
cd /d "%~dp0"
start "" "http://localhost:5000"
python -B web_app.py
pause
