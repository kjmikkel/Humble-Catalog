# Start the catalog viewer.
#
# Foreground by default (Ctrl+C stops it). -Detached runs it in the
# background and returns; use stop.ps1 to shut that one down. A detached
# viewer has no console anyone can see, so it is started with
# --no-handoff: login, reset and restore are then run from a terminal.
#
# Restart after changing Python code. A running server serves static
# files from disk on every request but holds its Python in memory, so a
# stale process pairs new JS with an old API - which is exactly how the
# viewer once rendered zero rows and hid every panel.
param([switch]$Detached)
. (Join-Path $PSScriptRoot "_common.ps1")
Require-Venv
Set-Location $Root

$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Error "Port $Port is already in use - run scripts\windows\stop.ps1 first."
}

if ($Detached) {
    $proc = Start-Process -FilePath $Python `
        -ArgumentList "-m", "humble_catalog", "serve", "--port", "$Port", "--no-handoff" `
        -WorkingDirectory $Root -PassThru -WindowStyle Hidden
    Write-Host "Viewer started detached on port $Port (PID $($proc.Id))."
    Write-Host "Stop it with: .\scripts\windows\stop.ps1"
} else {
    & $Python -m humble_catalog serve --port $Port
}
