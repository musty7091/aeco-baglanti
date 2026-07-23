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
echo AECO sistem kontrolü çalıştırılıyor...
".venv\Scripts\python.exe" manage.py check
if errorlevel 1 goto :error

echo.
echo Model ve temiz migrasyon eşleşmesi kontrol ediliyor...
".venv\Scripts\python.exe" manage.py makemigrations operations --check --dry-run
if errorlevel 1 goto :error

echo.
echo Operations testleri çalıştırılıyor...
".venv\Scripts\python.exe" manage.py test operations -v 2
if errorlevel 1 goto :error

echo.
echo TÜM DJANGO KONTROLLERİ BAŞARIYLA TAMAMLANDI.
pause
exit /b 0

:error
echo.
echo HATA: Kontrollerden biri başarısız oldu. Yukarıdaki hata mesajını inceleyin.
pause
exit /b 1
