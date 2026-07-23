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
echo Önceki demo kayıtları temizlenecek ve yeniden oluşturulacak.
echo.
".venv\Scripts\python.exe" manage.py demo_aeco --reset
if errorlevel 1 goto :error
echo.
echo Demo verileri başarıyla hazırlandı.
echo Kullanıcı: demo_admin
echo Şifre: Demo1234!
pause
exit /b 0
:error
echo.
echo HATA: Demo verileri oluşturulamadı. Yukarıdaki hata mesajını kontrol edin.
pause
exit /b 1
