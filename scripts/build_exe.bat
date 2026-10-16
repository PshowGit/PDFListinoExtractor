@echo off
rem Genera dist\PDFListinoExtractor\PDFListinoExtractor.exe (PyInstaller, modalita' onedir).
rem Uso: scripts\build_exe.bat          (dalla cartella del progetto o da qualunque altra)
rem Esce con codice diverso da 0 se un passo fallisce.
setlocal
cd /d "%~dp0.."

where uv >nul 2>nul
if errorlevel 1 (
    echo ERRORE: "uv" non trovato. Installarlo da https://docs.astral.sh/uv/ e riprovare.
    exit /b 1
)

rem File temporanei fuori da C: se esiste D:\tmp (su questa macchina C: e' stretto)
if exist D:\tmp (
    set "TMP=D:\tmp"
    set "TEMP=D:\tmp"
)

echo [1/3] Dipendenze...
uv sync --frozen
if errorlevel 1 (
    echo ERRORE: installazione delle dipendenze non riuscita.
    exit /b 1
)

echo [2/3] Test...
uv run pytest -q
if errorlevel 1 (
    echo ERRORE: i test non passano, l'eseguibile non viene generato.
    exit /b 1
)

echo [3/3] Compilazione con PyInstaller...
uv run pyinstaller --noconfirm --clean PDFListinoExtractor.spec
if errorlevel 1 (
    echo ERRORE: la compilazione con PyInstaller non e' riuscita. Vedere i messaggi sopra.
    exit /b 1
)
if not exist "dist\PDFListinoExtractor\PDFListinoExtractor.exe" (
    echo ERRORE: PyInstaller non ha prodotto dist\PDFListinoExtractor\PDFListinoExtractor.exe
    exit /b 1
)

echo.
echo Eseguibile pronto: %CD%\dist\PDFListinoExtractor\PDFListinoExtractor.exe
exit /b 0
