@chcp 65001 >nul
@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
set "LOCAL_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\get_lan_ip.ps1"`) do if not defined LOCAL_IP set "LOCAL_IP=%%I"

echo.
echo Yerel IP: %LOCAL_IP%
echo.
echo Aktif ağ profilleri:
powershell -NoProfile -Command "Get-NetConnectionProfile | Format-Table Name,InterfaceAlias,NetworkCategory,IPv4Connectivity -AutoSize"
echo.
echo Port 8000 dinleme kontrolü:
netstat -ano | findstr /R /C:":8000 .*LISTENING"
if errorlevel 1 (
  echo HATA: Port 8000 dinlenmiyor. Önce RUN_MOBILE_LAN.bat çalışmalıdır.
) else (
  echo TAMAM: Port 8000 dinleniyor.
)
echo.
echo Telefon adresi: http://%LOCAL_IP%:8000
echo.
pause
