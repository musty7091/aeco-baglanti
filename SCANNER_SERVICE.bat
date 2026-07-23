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

echo AECO yerel tarama servisi başlatılıyor...
echo Servis adresi: http://127.0.0.1:8765
".venv\Scripts\python.exe" scanner_service.py

if errorlevel 1 (
  echo.
  echo HATA: Tarama servisi durdu. Yukarıdaki hata mesajını kontrol edin.
  pause
)
