# Restart the AcDec Flashcard Generator: free port 8000, then start.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Fail($msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    Write-Host ""
    Write-Host "Press Enter to close..."
    Read-Host | Out-Null
    exit 1
}

try {
    $listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        $pids = $listeners.OwningProcess | Select-Object -Unique
        foreach ($procId in $pids) {
            Write-Host "Stopping process on port 8000 (PID $procId)..."
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    } else {
        Write-Host "No server was listening on port 8000."
    }

    & "$root\run.ps1"
}
catch {
    Fail $_.Exception.Message
}
