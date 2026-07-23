@chcp 65001 >nul
@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo HATA: Python başlatıcısı bulunamadı.
  echo Python 3.13 kurun ve kurulumda Add Python to PATH seçeneğini işaretleyin.
  pause
  exit /b 1
)

if exist "db.sqlite3" if not exist ".aeco_v170_clean_schema" (
  if not exist "backups" mkdir "backups"
  for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "DT=%%I"
  if not defined DT set "DT=backup"
  copy /y "db.sqlite3" "backups\db_v162_before_v170_%DT%.sqlite3" >nul
  del /q "db.sqlite3"
  echo Önceki demo veritabanı yedeklendi ve v1.7.0 temiz şeması için sıfırlandı.
)

if not exist ".venv\Scripts\python.exe" (
  py -3.13 -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist ".env" copy ".env.example" ".env" >nul

python manage.py migrate --noinput
if errorlevel 1 goto :error
python manage.py collectstatic --noinput
if errorlevel 1 goto :error
python manage.py check
if errorlevel 1 goto :error
python manage.py setup_aeco
if errorlevel 1 goto :error
> ".aeco_v170_clean_schema" echo v1.7.0

echo.
echo KURULUM BAŞARIYLA TAMAMLANDI.
echo Demo verileri için DEMO_VERI_OLUSTUR.bat dosyasını çalıştırın.
echo Uygulamayı açmak için RUN_WINDOWS.bat dosyasını kullanın.
pause
exit /b 0

:error
echo.
echo HATA: Kurulum tamamlanamadı. Yukarıdaki hata mesajını kontrol edin.
pause
exit /b 1
