@echo off
rem Tek dosyalik RafKamera exe'sini derler (hedef bilgisayarda Python ya da kurulum gerekmez).
rem   kurulum\derle.cmd            Korumali paket (community): dist\community\RafKamera-community.exe
rem   kurulum\derle.cmd duz        duz modellerle (gelistirme): dist\RafKamera.exe
rem Inno Setup 6 kuruluysa ayrica kurulum dosyasi: dist\kurulum\RafKamera-Kurulum-0.1.0.exe
setlocal
cd /d "%~dp0.."

set KIP=%~1
if "%KIP%"=="" set KIP=community

if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv || goto :hata
  .venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller==6.19.0 || goto :hata
)
if not exist motor\deps\onnxruntime\__init__.py (
  echo motor\deps hazir degil: README'deki kaynak kod kurulumu bolumune bakin.
  goto :hata
)
if /i "%KIP%"=="community" (
  if not exist kurulum\community-modeller\community-paket.json goto :paket_yok
  if not exist kurulum\community-modeller\goruntu-*.dll goto :paket_yok
  if not exist kurulum\community-modeller\RUST-NOTICES.txt goto :paket_yok
)

rem Gelistirme sinamalari yalnizca egitim\ klasoru olan kopyada calisir.
for %%S in (dene_kurulum dene_motor_yerlesimi dene_arayuzsuz dene_model_lisansi dene_is_akisi dene_kamera_kaydi dene_motor_iskeleti) do (
  if exist egitim\%%S.py (
    .venv\Scripts\python egitim\%%S.py >nul 2>&1 || (echo %%S basarisiz & goto :hata)
  )
)
if not exist kurulum\sahne\raf-kamera.pmod (
  echo Hazir sahne yok: kurulum\sahne\raf-kamera.pmod
  echo README'deki adimlarla bir kez uretin: kurulum\sablon.py, sonra Studio'da Farkli Kaydet.
  goto :hata
)
.venv\Scripts\python kurulum\modeller_iss.py --denetle || goto :hata
.venv\Scripts\python kurulum\simge.py >nul || goto :hata

if /i "%KIP%"=="duz" (
  set RAF_MODEL_PAKETI=
  .venv\Scripts\python -m PyInstaller kurulum\RafKamera.spec --noconfirm --clean --distpath dist --workpath build\duz || goto :hata
  echo.
  echo Hazir: dist\RafKamera.exe
) else (
  set RAF_MODEL_PAKETI=%KIP%
  .venv\Scripts\python -m PyInstaller kurulum\RafKamera.spec --noconfirm --clean --distpath dist\%KIP% --workpath build\%KIP% || goto :hata
  echo.
  echo Hazir: dist\%KIP%\RafKamera-%KIP%.exe
)

set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ISCC%" (
  "%ISCC%" /Q /DKip=%KIP% kurulum\RafKamera.iss || goto :hata
  echo Kurulum dosyasi: dist\kurulum\RafKamera-Kurulum-0.1.0.exe
) else (
  echo Inno Setup 6 kurulu degil: kurulum dosyasi uretilmedi. Kurmak icin: winget install JRSoftware.InnoSetup
)
exit /b 0

:paket_yok
echo Korumali model paketi eksik: kurulum\community-modeller
echo Gerekenler: community-paket.json, goruntu-*.dll ve RUST-NOTICES.txt (Raf Kamera'nin kendi paket kimligiyle).
echo Paket eklenmeden yalnizca gelistirme derlemesi yapilabilir: kurulum\derle.cmd duz
goto :hata

:hata
echo Derleme basarisiz.
exit /b 1
