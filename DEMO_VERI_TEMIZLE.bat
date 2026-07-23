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
echo.
echo Demo kayıtları ve demo kullanıcıları silinecek.
".venv\Scripts\python.exe" manage.py demo_aeco --clear
if errorlevel 1 goto :error
echo.
echo Demo verileri başarıyla temizlendi.
pause
exit /b 0
:error
echo.
echo HATA: Demo verileri temizlenemedi. Yukarıdaki hata mesajını kontrol edin.
pause
exit /b 1
