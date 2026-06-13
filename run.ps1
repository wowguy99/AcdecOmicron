# Starts the AcDec Flashcard Generator (Windows PowerShell).
# Builds the frontend if needed, then serves the app at http://127.0.0.1:8000
#
# Tip: if double-clicking run.ps1 does nothing, use run.bat instead.
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

function Test-FrontendBuildStale {
    param([string]$Root)
    $distIndex = Join-Path $Root "frontend\dist\index.html"
    if (-not (Test-Path $distIndex)) {
        return $true
    }
    $distTime = (Get-Item $distIndex).LastWriteTimeUtc
    $watchPaths = @(
        (Join-Path $Root "frontend\src")
        (Join-Path $Root "frontend\index.html")
        (Join-Path $Root "frontend\vite.config.ts")
        (Join-Path $Root "frontend\package.json")
        (Join-Path $Root "frontend\package-lock.json")
        (Join-Path $Root "frontend\tsconfig.json")
    )
    foreach ($path in $watchPaths) {
        if (-not (Test-Path $path)) { continue }
        if ((Get-Item $path).PSIsContainer) {
            $newer = Get-ChildItem -Path $path -Recurse -File |
                Where-Object { $_.LastWriteTimeUtc -gt $distTime } |
                Select-Object -First 1
            if ($newer) { return $true }
        }
        elseif ((Get-Item $path).LastWriteTimeUtc -gt $distTime) {
            return $true
        }
    }
    return $false
}

function Build-Frontend {
    param(
        [string]$Root,
        [switch]$InstallDeps
    )
    Push-Location (Join-Path $Root "frontend")
    try {
        if ($InstallDeps -or -not (Test-Path "node_modules")) {
            npm install
            if ($LASTEXITCODE -ne 0) { Fail "npm install failed. Is Node.js installed?" }
        }
        npm run build
        if ($LASTEXITCODE -ne 0) { Fail "Frontend build failed." }
    }
    finally {
        Pop-Location
    }
}

try {
    # Check port 8000 is free before starting.
    $inUse = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($inUse) {
        Write-Host "Port 8000 is already in use (PID $($inUse.OwningProcess))."
        Write-Host "If the app is already running, open: http://127.0.0.1:8000"
        Write-Host "Otherwise stop that process and run this script again."
        Write-Host ""
        Write-Host "Press Enter to close..."
        Read-Host | Out-Null
        exit 0
    }

    if (-not (Test-Path "$root\.venv\Scripts\python.exe")) {
        Write-Host "Creating virtualenv and installing backend deps..."
        python -m venv "$root\.venv"
        if ($LASTEXITCODE -ne 0) { Fail "Failed to create virtualenv. Is Python installed?" }
        & "$root\.venv\Scripts\python.exe" -m pip install -r "$root\backend\requirements.txt"
        if ($LASTEXITCODE -ne 0) { Fail "Failed to install Python dependencies." }
    }

    $frontendMissing = -not (Test-Path "$root\frontend\dist\index.html")
    $frontendStale = Test-FrontendBuildStale -Root $root
    $needsNpmInstall = -not (Test-Path "$root\frontend\node_modules")
    if ($frontendMissing -or $frontendStale -or $needsNpmInstall) {
        if ($frontendMissing) {
            Write-Host "Building frontend (first run may take a minute)..."
        }
        elseif ($frontendStale) {
            Write-Host "Rebuilding frontend (source changed since last build)..."
        }
        else {
            Write-Host "Installing frontend dependencies..."
        }
        Build-Frontend -Root $root -InstallDeps:$needsNpmInstall
    }

    Write-Host ""
    Write-Host "Starting server at http://127.0.0.1:8000"
    Write-Host "Keep this window open while using the app. Press Ctrl+C to stop."
    Write-Host ""
    & "$root\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir "$root\backend" --host 127.0.0.1 --port 8000
}
catch {
    Fail $_.Exception.Message
}
