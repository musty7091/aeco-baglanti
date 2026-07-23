@chcp 65001 >nul
@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo AECO v1.7.0 temiz veri modeli kullanır.
echo Bu paket mevcut v1.6 demo veritabanını yedekleyip yeniden kurmalıdır.
echo Güncelleme için SETUP_WINDOWS.bat dosyasını çalıştırın.
echo SETUP_WINDOWS.bat eski db.sqlite3 dosyasını backups klasörüne alır.
echo.
pause
call "%~dp0SETUP_WINDOWS.bat"
