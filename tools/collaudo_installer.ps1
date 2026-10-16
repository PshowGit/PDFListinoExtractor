# Collaudo di installazione, aggiornamento e disinstallazione (installazione per utente corrente,
# senza privilegi: quella in Program Files richiede la conferma UAC e va provata a mano).
#   powershell -ExecutionPolicy Bypass -File tools\collaudo_installer.ps1 <setup_vecchio.exe> <setup_nuovo.exe> <pdf>
# Lascia il sistema come l'ha trovato: alla fine il programma e' disinstallato e i dati di prova rimossi.
param([string]$SetupVecchio, [string]$SetupNuovo, [string]$Pdf)
$ErrorActionPreference = 'Stop'
$risultati = New-Object System.Collections.Generic.List[object]
function Verifica($nome, $ok, $dettaglio = '') {
    $risultati.Add([pscustomobject]@{ Esito = $(if ($ok) { 'OK' } else { 'FALLITO' }); Test = $nome; Dettaglio = $dettaglio })
}

$accenti = [string][char]0xE0 + [char]0xE8 + [char]0xF9            # "aeu" accentate, senza dipendere dalla codifica del file
$base = "D:\tmp\Installazione prova $accenti"
$dir = "$base\PDFListinoExtractor"
$exe = "$dir\PDFListinoExtractor.exe"
$chiave = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{F0411EB9-947B-42C1-B41A-62EFF2E34BD1}_is1'
$lnkStart = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\PDFListinoExtractor.lnk"
$lnkDesktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'PDFListinoExtractor.lnk'
$datiUtente = "$env:LOCALAPPDATA\PDFListinoExtractor"
$regolePersonali = "$datiUtente\supplier_rules.json"
$export = "$base\Esportati $accenti"
if (Test-Path $chiave) { throw "PDFListinoExtractor e' gia' installato per questo utente: disinstallarlo prima del collaudo." }
if (Test-Path $regolePersonali) { throw "Esiste gia' ${regolePersonali}: il collaudo non lo sovrascrive." }
New-Item -ItemType Directory -Force $export | Out-Null

function Installa($setup, $log) {
    $p = Start-Process $setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER',
        "/DIR=`"$dir`"", '/TASKS=desktopicon', "/LOG=`"$log`"" -PassThru -Wait
    return $p.ExitCode
}
function Avvia($percorso) {
    $prima = @(Get-Process PDFListinoExtractor -ErrorAction SilentlyContinue | ForEach-Object Id)
    Start-Process $percorso | Out-Null
    $titolo = ''
    for ($i = 0; $i -lt 30 -and -not $titolo; $i++) {
        Start-Sleep -Milliseconds 500
        $p = Get-Process PDFListinoExtractor -ErrorAction SilentlyContinue | Where-Object { $prima -notcontains $_.Id -and $_.MainWindowTitle }
        if ($p) { $titolo = $p[0].MainWindowTitle; $p | Stop-Process -Force }
    }
    return $titolo
}

# --- 1. installazione della versione precedente ---------------------------------------------------
$c = Installa $SetupVecchio "$base\install_vecchia.log"
$verVecchia = (Get-ItemProperty $chiave -ErrorAction SilentlyContinue).DisplayVersion
Verifica 'Installazione versione precedente' ($c -eq 0 -and (Test-Path $exe)) "codice $c, versione registrata $verVecchia"

# dati dell'utente che l'aggiornamento non deve toccare
New-Item -ItemType Directory -Force $datiUtente | Out-Null
'{"fornitori": {"collaudo": {"nome": "Fornitore di collaudo"}}}' | Set-Content $regolePersonali -Encoding UTF8
$hashRegole = (Get-FileHash $regolePersonali).Hash
$p = Start-Process $exe -ArgumentList '--collaudo', "`"$Pdf`"", "`"$export\Listino vecchia.xlsx`"" -PassThru -Wait
Verifica 'Estrazione ed export con la versione precedente' ($p.ExitCode -eq 0) "codice $($p.ExitCode)"
'residuo' | Set-Content "$dir\_internal\file_della_versione_vecchia.txt"

# --- 2. aggiornamento ---------------------------------------------------------------------------
$c = Installa $SetupNuovo "$base\install_nuova.log"
$reg = Get-ItemProperty $chiave
$verExe = (Get-Item $exe).VersionInfo.ProductVersion.Trim()
Verifica 'Aggiornamento alla nuova versione' ($c -eq 0 -and $reg.DisplayVersion -ne $verVecchia) "codice $c, $verVecchia -> $($reg.DisplayVersion), eseguibile $verExe"
Verifica 'Una sola voce in App installate' (@(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -like 'PDFListinoExtractor*' }).Count -eq 1)
Verifica 'Stessa cartella di installazione' ($reg.InstallLocation.TrimEnd('\') -eq $dir) $reg.InstallLocation
Verifica 'Librerie della versione vecchia rimosse' (-not (Test-Path "$dir\_internal\file_della_versione_vecchia.txt"))
Verifica 'Regole personali preservate' ((Test-Path $regolePersonali) -and (Get-FileHash $regolePersonali).Hash -eq $hashRegole)
Verifica 'Excel esportato preservato' (Test-Path "$export\Listino vecchia.xlsx")
Verifica 'Log preservato' (Test-Path "$datiUtente\logs\app.log")

# --- 3. collegamenti e avvio --------------------------------------------------------------------
$shell = New-Object -ComObject WScript.Shell
Verifica 'Collegamento nel menu Start' ((Test-Path $lnkStart) -and $shell.CreateShortcut($lnkStart).TargetPath -eq $exe) $lnkStart
Verifica 'Collegamento sul desktop' ((Test-Path $lnkDesktop) -and $shell.CreateShortcut($lnkDesktop).TargetPath -eq $exe) $lnkDesktop
$t = Avvia $lnkStart;   Verifica 'Avvio dal menu Start' ($t -like 'Estrattore listini PDF*') "finestra: $t"
$t = Avvia $lnkDesktop; Verifica 'Avvio dal desktop' ($t -like 'Estrattore listini PDF*') "finestra: $t"
$p = Start-Process $exe -ArgumentList '--collaudo', "`"$Pdf`"", "`"$export\Listino nuova.xlsx`"" -PassThru -Wait
$r = Get-Content "$export\Listino nuova.collaudo.json" -Encoding UTF8 -Raw | ConvertFrom-Json
Verifica 'Estrazione ed export dalla versione installata' ($p.ExitCode -eq 0 -and $r.esito -eq 'ok') "$($r.articoli) articoli, $($r.righe_excel) righe Excel, $($r.durata_s) s"
Verifica 'Regole personali lette dalla versione installata' (@($r.fornitori) -contains 'collaudo') "fornitori: $(@($r.fornitori) -join ', ')"

# --- 4. disinstallazione ------------------------------------------------------------------------
$p = Start-Process "$dir\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru -Wait
Start-Sleep 2  # il disinstallatore completa la rimozione di se' stesso in un processo a parte
Verifica 'Disinstallazione' ($p.ExitCode -eq 0 -and -not (Test-Path $exe)) "codice $($p.ExitCode)"
Verifica 'Voce rimossa da App installate' (-not (Test-Path $chiave))
Verifica 'Collegamenti rimossi' (-not (Test-Path $lnkStart) -and -not (Test-Path $lnkDesktop))
Verifica 'Cartella del programma rimossa' (-not (Test-Path $dir)) $dir
Verifica 'Dati utente preservati dopo la disinstallazione' ((Test-Path $regolePersonali) -and (Test-Path "$datiUtente\logs\app.log"))
Verifica 'Excel esportati preservati dopo la disinstallazione' ((Test-Path "$export\Listino vecchia.xlsx") -and (Test-Path "$export\Listino nuova.xlsx"))

# pulizia: si rimuove solo cio' che il collaudo ha creato
Remove-Item $regolePersonali -Force
$risultati | Format-Table -AutoSize -Wrap | Out-String -Width 220
if ($risultati | Where-Object Esito -ne 'OK') { exit 1 } else { exit 0 }
