@chcp 65001 >nul
@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo HATA: Kurulum bulunamadı. Önce SETUP_WINDOWS.bat dosyasını çalıştırın.
  pause
  exit /b 1
)

set "LOCAL_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\get_lan_ip.ps1"`) do (
  if not defined LOCAL_IP set "LOCAL_IP=%%I"
)

if not defined LOCAL_IP (
  echo HATA: Aktif yerel ağ IP adresi otomatik bulunamadı.
  echo Komut İstemi'nde ipconfig çalıştırıp Wi-Fi IPv4 adresini kontrol edin.
  echo VPN programlarını geçici olarak kapatmayı deneyin.
  pause
  exit /b 1
)

set "DJANGO_ALLOWED_HOSTS=*"
set "DJANGO_DEBUG=True"

start "AECO Tarama Servisi" /min "%~dp0.venv\Scripts\python.exe" "%~dp0scanner_service.py"

echo.
echo ============================================================
echo AECO MOBİL YEREL AĞ KULLANIMI
echo ============================================================
echo Bilgisayarda : http://127.0.0.1:8000
echo Telefonda    : http://%LOCAL_IP%:8000
echo ============================================================
echo.
echo ÖNEMLİ:
echo 1. Telefon ve bilgisayar aynı Wi-Fi ağına bağlı olmalıdır.
echo 2. Telefonda adresi HTTPS değil HTTP olarak açın.
echo 3. İlk kullanımda MOBIL_ERISIM_IZNI.bat dosyasını bir kez çalıştırın.
echo 4. Fiziksel Windows tarayıcısı yalnızca bilgisayardaki formdan kullanılabilir.
echo 5. Telefonda Dosyadan Seç seçeneğiyle PDF veya kamera fotoğrafı yüklenebilir.
echo 6. Bu pencere açık kalmalıdır.
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8000'"
".venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000 --noreload

echo.
echo Sunucu durdu. Yukarıdaki hata mesajlarını kontrol edin.
pause
