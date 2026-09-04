@echo off
rem Grava a API key da OpenAI no Gerenciador de Credenciais do Windows.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m artemis --set-key
pause
