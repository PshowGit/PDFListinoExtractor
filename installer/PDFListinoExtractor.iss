; Installer Windows di PDFListinoExtractor (Inno Setup 6).
; Non compilarlo a mano: scripts\build_installer.bat legge la versione da version.py e la passa qui
; con /DVersione=... e, se valorizzato, l'editore con /DEditore=...
; Input:  dist\PDFListinoExtractor\  (prodotto da scripts\build_exe.bat)
; Uscita: dist\PDFListinoExtractor_Setup.exe

#ifndef Versione
  #error "Versione non definita: usare scripts\build_installer.bat"
#endif

#define NomeApp "PDFListinoExtractor"
#define TitoloApp "Estrattore listini PDF"
#define Eseguibile "PDFListinoExtractor.exe"

[Setup]
; AppId identifica il programma fra una versione e l'altra: NON va mai cambiato, altrimenti
; un aggiornamento verrebbe installato come un programma diverso accanto al vecchio.
AppId={{F0411EB9-947B-42C1-B41A-62EFF2E34BD1}
AppName={#NomeApp}
AppVersion={#Versione}
AppVerName={#NomeApp} {#Versione}
#ifdef Editore
AppPublisher={#Editore}
#endif
AppComments={#TitoloApp}: estrazione di listini prezzi PDF in Excel
VersionInfoVersion={#Versione}
VersionInfoProductName={#NomeApp}
VersionInfoDescription=Installazione di {#NomeApp}
; Program Files per tutti gli utenti (richiede i privilegi di amministratore), oppure, a scelta
; dell'utente nella prima schermata, installazione solo per l'utente corrente senza privilegi.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#NomeApp}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename={#NomeApp}_Setup
SetupIconFile=..\assets\icona.ico
UninstallDisplayIcon={app}\{#Eseguibile}
UninstallDisplayName={#NomeApp} {#Versione}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; se il programma e' aperto durante un aggiornamento, l'installer propone di chiuderlo
CloseApplications=yes
RestartApplications=no
; nessuna pagina di licenza: non e' stata predisposta una licenza del programma.
; Le licenze dei componenti di terze parti sono installate in LICENZE_TERZE_PARTI.txt.

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Un aggiornamento sostituisce per intero le librerie: file rimasti da una versione precedente
; verrebbero caricati accanto a quelli nuovi. I dati dell'utente non stanno qui.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\{#NomeApp}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LEGGIMI.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENZE_TERZE_PARTI.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#NomeApp}"; Filename: "{app}\{#Eseguibile}"; Comment: "{#TitoloApp}"
Name: "{autodesktop}\{#NomeApp}"; Filename: "{app}\{#Eseguibile}"; Comment: "{#TitoloApp}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Eseguibile}"; Description: "{cm:LaunchProgram,{#NomeApp}}"; Flags: nowait postinstall skipifsilent

; Nessuna sezione [UninstallDelete] sui dati utente: la disinstallazione rimuove il programma ma
; lascia %LOCALAPPDATA%\PDFListinoExtractor (log, regole personali) e i file Excel esportati.
