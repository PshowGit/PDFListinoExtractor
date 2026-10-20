# -*- mode: python ; coding: utf-8 -*-
# Compilazione ripetibile dell'eseguibile Windows (modalita' onedir, senza console).
#     scripts\build_exe.bat          oppure          uv run pyinstaller --noconfirm --clean PDFListinoExtractor.spec
# Uscita: dist\PDFListinoExtractor\PDFListinoExtractor.exe  (+ cartella _internal con le librerie)
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

RADICE = Path(SPECPATH)
sys.path.insert(0, str(RADICE))
import version as v  # noqa: E402  (unica fonte della versione)

numeri = tuple(int(x) for x in v.__version__.split(".")) + (0,)
info_versione = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numeri, prodvers=numeri),
    kids=[
        StringFileInfo([StringTable("041004B0", [  # italiano, Unicode
            StringStruct("CompanyName", v.EDITORE),
            StringStruct("FileDescription", v.DESCRIZIONE),
            StringStruct("FileVersion", v.__version__),
            StringStruct("InternalName", v.NOME_APP),
            StringStruct("OriginalFilename", f"{v.NOME_APP}.exe"),
            StringStruct("ProductName", v.TITOLO_APP),
            StringStruct("ProductVersion", v.__version__),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0410, 1200])]),
    ],
)

dati = [
    (str(RADICE / "config" / "supplier_rules.json"), "config"),
    (str(RADICE / "config" / "supplier_rules.schema.json"), "config"),  # lo applica il salvataggio del wizard
    (str(RADICE / "config" / "modello_fornitori.json"), "config"),  # copiato al primo avvio
    (str(RADICE / "assets" / "icona.ico"), "assets"),
]
dati += collect_data_files("customtkinter")  # temi e font: senza, la finestra non si apre
dati += collect_data_files("jsonschema_specifications")  # i metaschemi che jsonschema carica per validare

a = Analysis(
    [str(RADICE / "main.py")],
    pathex=[str(RADICE)],
    datas=dati,
    hiddenimports=[],
    # strumenti di sviluppo e moduli che il programma non usa: solo peso in piu'
    excludes=["pytest", "_pytest", "ruff", "setuptools", "pip", "unittest", "pydoc", "lib2to3", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

opzioni = dict(
    name=v.NOME_APP,
    icon=str(RADICE / "assets" / "icona.ico"),
    version=info_versione,
    console=False,  # applicazione a finestra: nessuna console nell'uso normale
    upx=False,  # UPX aumenta i falsi positivi degli antivirus e rallenta l'avvio
    debug=False,
)

if os.environ.get("PDFLISTINO_ONEFILE") == "1":
    # Variante a file singolo, solo per confronto (v. README, "onedir o onefile"): a ogni avvio
    # si scompatta in una cartella temporanea, quindi parte piu' lentamente.
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **opzioni)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **opzioni)
    coll = COLLECT(exe, a.binaries, a.datas, name=v.NOME_APP, upx=False)
