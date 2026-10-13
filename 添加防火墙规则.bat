@echo off
echo ??? AirFloat ?????????...
netsh advfirewall firewall add rule name="AirFloat TCP 53317" dir=in action=allow protocol=TCP localport=53317
netsh advfirewall firewall add rule name="AirFloat UDP 53317" dir=in action=allow protocol=UDP localport=53317
echo.
echo ????????????
pause
