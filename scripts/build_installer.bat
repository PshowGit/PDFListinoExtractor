@echo off
rem Genera dist\PDFListinoExtractor_Setup.exe con Inno Setup, a partire da dist\PDFListinoExtractor\.
rem Uso: scripts\build_installer.bat      (dopo scripts\build_exe.bat)
rem Esce con codice diverso da 0 se un passo fallisce.
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

if not exist "dist\PDFListinoExtractor\PDFListinoExtractor.exe" (
    echo ERRORE: eseguibile non trovato. Lanciare prima scripts\build_exe.bat
    exit /b 1
)

rem Inno Setup: installazione per utente, per tutti gli utenti, oppure nel PATH
set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do (
    if not defined ISCC if exist "%%~P" set "ISCC=%%~P"
)
if not defined ISCC (
    for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
)
if not defined ISCC (
    echo ERRORE: Inno Setup 6 non trovato. Installarlo da https://jrsoftware.org/isdl.php e riprovare.
    exit /b 1
)

rem Versione ed editore da version.py: unica fonte, cosi' installer ed eseguibile non divergono
for /f "delims=" %%V in ('uv run python -c "import version; print(version.__version__)"') do set "VERSIONE=%%V"
for /f "delims=" %%E in ('uv run python -c "import version; print(version.EDITORE)"') do set "EDITORE=%%E"
if not defined VERSIONE (
    echo ERRORE: impossibile leggere la versione da version.py
    exit /b 1
)

set "OPZ_EDITORE="
if defined EDITORE set OPZ_EDITORE="/DEditore=!EDITORE!"

echo Compilazione dell'installer, versione !VERSIONE!...
"%ISCC%" /Q "/DVersione=!VERSIONE!" !OPZ_EDITORE! "installer\PDFListinoExtractor.iss"
if errorlevel 1 (
    echo ERRORE: la compilazione dell'installer non e' riuscita. Vedere i messaggi sopra.
    exit /b 1
)
if not exist "dist\PDFListinoExtractor_Setup.exe" (
    echo ERRORE: Inno Setup non ha prodotto dist\PDFListinoExtractor_Setup.exe
    exit /b 1
)

echo.
echo Installer pronto: %CD%\dist\PDFListinoExtractor_Setup.exe  (versione !VERSIONE!)
exit /b 0
