@echo off
cd /d "%~dp0"
del /q airfloat.log electron-err.log 2>nul
"%~dp0node_modules\electron\dist\electron.exe" "%~dp0." --no-sandbox --disable-gpu --enable-logging 1> electron-err.log 2>&1
echo.
echo ============ ???: %errorlevel% ============
pause
