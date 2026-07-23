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

start "AECO Tarama Servisi" /min "%~dp0.venv\Scripts\python.exe" "%~dp0scanner_service.py"
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000'"

echo.
echo AECO Bağlantılı Satış başlatılıyor...
echo Bilgisayar adresi: http://127.0.0.1:8000
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000 --noreload

echo.
echo Sunucu durdu. Yukarıdaki hata mesajlarını kontrol edin.
pause
