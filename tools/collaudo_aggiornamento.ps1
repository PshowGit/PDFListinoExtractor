# Collaudo dell'aggiornamento automatico sull'eseguibile installato (per utente corrente, senza UAC).
#   powershell -ExecutionPolicy Bypass -File tools\collaudo_aggiornamento.ps1 <setup.exe>
# Installa il setup, poi lo serve da un server locale come se fosse la versione 9.9.9 pubblicata su
# GitHub (variabile PDFLISTINO_URL_AGGIORNAMENTI): il programma installato lo trova, lo scarica, ne
# verifica lo SHA-256, avvia l'installer con /RIAVVIA e si chiude; l'installer reinstalla e lo riapre.
# Lascia il sistema come l'ha trovato: alla fine il programma e' disinstallato e i dati di prova rimossi.
param([string]$Setup)
$ErrorActionPreference = 'Stop'
$risultati = New-Object System.Collections.Generic.List[object]
function Verifica($nome, $ok, $dettaglio = '') {
    $risultati.Add([pscustomobject]@{ Esito = $(if ($ok) { 'OK' } else { 'FALLITO' }); Test = $nome; Dettaglio = $dettaglio })
}

$Setup = (Resolve-Path $Setup).Path
$accenti = [string][char]0xE0 + [char]0xE8 + [char]0xF9            # "aeu" accentate, senza dipendere dalla codifica del file
$base = "D:\tmp\Aggiornamento prova $accenti"
# %LOCALAPPDATA% e cartella temporanea di prova: le regole personali vere dell'utente non vengono mai
# lette, scritte o cancellate, e il setup scaricato finisce qui.
$env:LOCALAPPDATA = "$base\AppData Local di prova"
$env:TMP = "$base\Temp"; $env:TEMP = $env:TMP
New-Item -ItemType Directory -Force $env:LOCALAPPDATA, $env:TMP | Out-Null
$dir = "$base\PDFListinoExtractor"
$exe = "$dir\PDFListinoExtractor.exe"
$chiave = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{F0411EB9-947B-42C1-B41A-62EFF2E34BD1}_is1'
$registroInno = "$env:TMP\PDFListinoExtractor_aggiornamento.log"
$report = "$base\aggiornamento.collaudo.json"
if (Test-Path $chiave) { throw "PDFListinoExtractor e' gia' installato per questo utente: disinstallarlo prima del collaudo." }

function Processi() {
    @(Get-Process PDFListinoExtractor -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe })
}

# --- 1. installazione ---------------------------------------------------------------------------
$p = Start-Process $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER',
    "/DIR=`"$dir`"", "/LOG=`"$base\installazione.log`"" -PassThru
$p.WaitForExit()
$versione = (Get-Item $exe).VersionInfo.ProductVersion.Trim()
Verifica 'Installazione per utente' ($p.ExitCode -eq 0 -and (Test-Path $exe)) "codice $($p.ExitCode), versione $versione"
Start-Sleep 3
Verifica 'Installazione silenziosa senza /RIAVVIA: il programma non si apre' ((Processi).Count -eq 0)
'residuo' | Set-Content "$dir\_internal\segno_della_prima_installazione.txt"

# --- 2. server locale con l'API finta -----------------------------------------------------------
$servito = "$base\server"
New-Item -ItemType Directory -Force $servito | Out-Null
Copy-Item $Setup "$servito\PDFListinoExtractor_Setup.exe"
$porta = Get-Random -Minimum 20000 -Maximum 40000
$sha = (Get-FileHash "$servito\PDFListinoExtractor_Setup.exe" -Algorithm SHA256).Hash.ToLower()
@{
    tag_name = 'v9.9.9'; draft = $false; prerelease = $false
    html_url = "http://127.0.0.1:$porta/"
    body = "## Novit$([char]0xE0)`n`n- Versione di **collaudo** servita in locale"
    assets = @(@{
        name = 'PDFListinoExtractor_Setup.exe'; size = (Get-Item $Setup).Length; digest = "sha256:$sha"
        browser_download_url = "http://127.0.0.1:$porta/PDFListinoExtractor_Setup.exe"
    })
} | ConvertTo-Json -Depth 4 | ForEach-Object {
    [IO.File]::WriteAllText("$servito\latest.json", $_, (New-Object Text.UTF8Encoding $false))  # senza BOM, come GitHub
}
$python = (& uv run python -c "import sys; print(sys.executable)").Trim()
$server = Start-Process $python -ArgumentList '-m', 'http.server', $porta, '--bind', '127.0.0.1', '--directory', "`"$servito`"" `
    -PassThru -WindowStyle Hidden
Start-Sleep 2
$env:PDFLISTINO_URL_AGGIORNAMENTI = "http://127.0.0.1:$porta/latest.json"

try {
    # --- 3. aggiornamento dal programma installato ----------------------------------------------
    $inizio = Get-Date
    $p = Start-Process $exe -ArgumentList '--collaudo-aggiornamento', "`"$report`"" -PassThru
    $finito = $p.WaitForExit(180000)
    $r = if (Test-Path $report) { Get-Content $report -Encoding UTF8 -Raw | ConvertFrom-Json } else { $null }
    Verifica 'Programma installato: controllo attivo e modo per utente' ($r -and $r.attivo -and $r.modo -eq '/CURRENTUSER') "modo $($r.modo)"
    Verifica 'Pulsante dell''aggiornamento' ($r.pulsante -eq 'Aggiornamento disponibile (v9.9.9)') $r.pulsante
    Verifica 'Setup scaricato e verificato' ($r.dimensione -eq (Get-Item $Setup).Length) "$($r.dimensione) byte in $($r.scaricato)"
    Verifica 'Il programma si chiude dopo aver avviato l''installer' ($finito -and $p.ExitCode -eq 0 -and $r.chiuso) "codice $($p.ExitCode), esito $($r.esito) $($r.errore)"

    # --- 4. installazione e riapertura -----------------------------------------------------------
    $riaperto = $null
    for ($i = 0; $i -lt 240 -and -not $riaperto; $i++) {
        Start-Sleep -Milliseconds 500
        $riaperto = Processi | Where-Object { $_.StartTime -gt $inizio -and $_.Id -ne $p.Id -and $_.MainWindowTitle } | Select-Object -First 1
    }
    Verifica 'Il programma si riapre da solo' ($null -ne $riaperto) "finestra: $($riaperto.MainWindowTitle)"
    for ($i = 0; $i -lt 60 -and -not ((Test-Path $registroInno) -and (Select-String -Path $registroInno -Pattern 'Log closed' -Quiet)); $i++) {
        Start-Sleep 1
    }
    $esitoInno = (Test-Path $registroInno) -and (Select-String -Path $registroInno -Pattern 'Installation process succeeded' -Quiet)
    Verifica 'Installazione dall''aggiornamento riuscita' $esitoInno $registroInno
    $parametri = if (Test-Path $registroInno) { (Select-String -Path $registroInno -Pattern 'Command line:' | Select-Object -First 1).Line } else { '' }
    Verifica 'Installer avviato con /SILENT /CURRENTUSER /RIAVVIA' ($parametri -match '/SILENT' -and $parametri -match '/CURRENTUSER' -and $parametri -match '/RIAVVIA') $parametri
    Verifica 'Librerie reinstallate' (-not (Test-Path "$dir\_internal\segno_della_prima_installazione.txt"))
    $reg = Get-ItemProperty $chiave
    Verifica 'Stessa cartella, una sola voce in App installate' ($reg.InstallLocation.TrimEnd('\') -eq $dir -and
        @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall' | Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -like 'PDFListinoExtractor*' }).Count -eq 1) $reg.InstallLocation
    Verifica 'Regole personali non toccate' (-not (Test-Path "$env:LOCALAPPDATA\PDFListinoExtractor\supplier_rules.json"))
} finally {
    Processi | Stop-Process -Force
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\PDFLISTINO_URL_AGGIORNAMENTI
}

# --- 5. disinstallazione e pulizia ----------------------------------------------------------------
Start-Sleep 2
$p = Start-Process "$dir\unins000.exe" -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -PassThru
$p.WaitForExit()
Start-Sleep 2  # il disinstallatore completa la rimozione di se' stesso in un processo a parte
Verifica 'Disinstallazione' ($p.ExitCode -eq 0 -and -not (Test-Path $chiave) -and -not (Test-Path $exe)) "codice $($p.ExitCode)"
$risultati | Format-Table -AutoSize -Wrap | Out-String -Width 220
if ($risultati | Where-Object Esito -ne 'OK') {
    "Report, log e schermata restano in $base"
    exit 1
}
Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
exit 0
