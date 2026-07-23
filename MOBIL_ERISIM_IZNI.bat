@chcp 65001 >nul
@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

fltmc >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo AECO mobil erişimi için Windows ağ ve güvenlik duvarı ayarları yapılacak.
echo Bu işlemi yalnızca güvendiğiniz ev veya iş Wi-Fi ağında uygulayın.
echo.
choice /C EH /N /M "Aktif ağ güvenilir bir ev/iş ağı mı? [E/H]: "
if errorlevel 2 (
  echo İşlem iptal edildi.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$profiles=Get-NetConnectionProfile ^| Where-Object {$_.IPv4Connectivity -ne 'Disconnected'}; foreach($p in $profiles){ if($p.NetworkCategory -ne 'DomainAuthenticated'){ Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private } }"

netsh advfirewall firewall delete rule name="AECO Mobil Erişim TCP 8000" >nul 2>&1
netsh advfirewall firewall add rule name="AECO Mobil Erişim TCP 8000" dir=in action=allow protocol=TCP localport=8000 profile=private >nul

if errorlevel 1 (
  echo HATA: Güvenlik duvarı kuralı eklenemedi.
  pause
  exit /b 1
)

echo.
echo TAMAM: Aktif ağ Özel olarak ayarlandı.
echo TAMAM: Windows Güvenlik Duvarı TCP 8000 portuna izin verdi.
echo Şimdi RUN_MOBILE_LAN.bat dosyasını çalıştırın.
echo.
pause
