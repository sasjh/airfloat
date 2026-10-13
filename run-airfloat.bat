@echo off
cd /d "%~dp0"
del /q airfloat.log 2>nul
"%~dp0node_modules\electron\dist\electron.exe" "%~dp0." --no-sandbox --disable-gpu
