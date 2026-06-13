# Build the Windows installer (Setup.exe) for AcDec Flashcard Generator.
# Prerequisites: Python venv, Node.js, Inno Setup 6 (iscc on PATH or default install path).
#
# Usage (from repo root):
#   .\packaging\build.ps1
#   .\packaging\build.ps1 -SkipInno   # PyInstaller folder only (no Setup.exe)
#   .\packaging\build.ps1 -Version 0.2.0   # skip version prompt
#
# Output:
#   packaging\output\AcDecFlashcards-Setup-<version>.exe
param(
    [switch]$SkipInno,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Fail($msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function Find-InnoSetup {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if ($iscc) { return $iscc.Source }
    return $null
}

function Stop-RunningApp {
    $stopped = $false
    Get-Process -Name "AcDecFlashcards" -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Host "Stopping AcDecFlashcards.exe (PID $($_.Id))..."
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        $stopped = $true
    }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like "*\packaging\dist*\AcDecFlashcards*" } |
        ForEach-Object {
            Write-Host "Stopping $($_.Name) (PID $($_.ProcessId))..."
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            $stopped = $true
        }
    $listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        foreach ($procId in ($listeners.OwningProcess | Select-Object -Unique)) {
            Write-Host "Stopping process on port 8000 (PID $procId)..."
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            $stopped = $true
        }
    }
    if ($stopped) {
        Start-Sleep -Seconds 2
    }
}

function Remove-BuildDir($path) {
    if (-not (Test-Path $path)) { return $true }
    for ($i = 0; $i -lt 5; $i++) {
        try {
            Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Get-AppVersion {
    $pkgPath = Join-Path $root "frontend\package.json"
    if (-not (Test-Path $pkgPath)) { Fail "package.json not found at $pkgPath" }
    $pkg = Get-Content $pkgPath -Raw | ConvertFrom-Json
    return [string]$pkg.version
}

function Get-InnoAppVersion {
    $issPath = Join-Path $root "packaging\installer.iss"
    $content = Get-Content $issPath -Raw
    if ($content -match '#define AppVersion "([^"]+)"') {
        return $Matches[1]
    }
    return $null
}

function Test-VersionFormat($version) {
    return $version -match '^\d+\.\d+\.\d+$'
}

function Set-AppVersion($version) {
    $pkgPath = Join-Path $root "frontend\package.json"
    $content = [System.IO.File]::ReadAllText($pkgPath)
    $updated = [regex]::Replace($content, '("version"\s*:\s*")[^"]+(")', "`${1}$version`${2}")
    if ($updated -eq $content) { Fail "Could not update version in package.json" }
    [System.IO.File]::WriteAllText($pkgPath, $updated)

    $issPath = Join-Path $root "packaging\installer.iss"
    $issContent = [System.IO.File]::ReadAllText($issPath)
    if ($issContent -match '#define AppVersion ') {
        $issUpdated = [regex]::Replace($issContent, '(#define AppVersion ")[^"]+(")', "`${1}$version`${2}")
        [System.IO.File]::WriteAllText($issPath, $issUpdated)
    }
}

function Resolve-BuildVersion {
    $current = Get-AppVersion
    $innoVersion = Get-InnoAppVersion
    if ($innoVersion -and $innoVersion -ne $current) {
        Write-Host "Note: installer.iss has AppVersion $innoVersion (package.json has $current)." -ForegroundColor Yellow
    }

    Write-Host "Current version: $current" -ForegroundColor Cyan

    $buildVersion = $Version
    if ([string]::IsNullOrWhiteSpace($buildVersion)) {
        $input = Read-Host "Build version (Enter to keep $current)"
        $buildVersion = if ([string]::IsNullOrWhiteSpace($input)) { $current } else { $input.Trim() }
    }

    if (-not (Test-VersionFormat $buildVersion)) {
        Fail "Invalid version '$buildVersion'. Use semantic format, e.g. 0.2.0"
    }

    if ($buildVersion -ne $current) {
        Write-Host "Updating version: $current -> $buildVersion"
        Set-AppVersion $buildVersion
    } else {
        Write-Host "Building version: $buildVersion"
    }

    return $buildVersion
}

Write-Host "=== AcDec Flashcard Generator - Windows installer build ===" -ForegroundColor Cyan
Write-Host ""

$buildVersion = Resolve-BuildVersion
Write-Host ""
Write-Host "[1/4] Building frontend..."
Push-Location "$root\frontend"
if (-not (Test-Path "node_modules")) {
    npm install
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "npm install failed." }
}
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Frontend build failed." }
Pop-Location

# 2. Python deps + PyInstaller
$python = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Fail "Virtualenv not found. Create .venv and install backend/requirements.txt (see README)."
}

Write-Host "[2/4] Installing build dependencies..."
& $python -m pip install -r "$root\packaging\requirements-build.txt" -q
if ($LASTEXITCODE -ne 0) { Fail "Failed to install PyInstaller." }

Write-Host "[3/4] Running PyInstaller..."
Stop-RunningApp

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$distRoot = "$root\packaging\dist-build\$stamp"
$workRoot = "$root\packaging\build-build\$stamp"
New-Item -ItemType Directory -Force -Path $distRoot, $workRoot | Out-Null

Push-Location "$root\packaging"
& $python -m PyInstaller --noconfirm acdec.spec --distpath $distRoot --workpath $workRoot
$pyiExit = $LASTEXITCODE
Pop-Location

$bundleDir = Join-Path $distRoot "AcDecFlashcards"
if ($pyiExit -ne 0 -or -not (Test-Path "$bundleDir\AcDecFlashcards.exe")) {
    Fail "PyInstaller build failed. See output above. Bundle path: $bundleDir"
}

# Best-effort: refresh packaging\dist for manual testing (skip if an old build is locked).
$legacyDist = "$root\packaging\dist\AcDecFlashcards"
if (Remove-BuildDir $legacyDist) {
    New-Item -ItemType Directory -Force -Path (Split-Path $legacyDist -Parent) | Out-Null
    Copy-Item -Path $bundleDir -Destination $legacyDist -Recurse -Force
}

Write-Host "PyInstaller bundle: $bundleDir"

# 3. Inno Setup
if ($SkipInno) {
    Write-Host "[4/4] Skipping Inno Setup (-SkipInno)."
    Write-Host ""
    Write-Host "PyInstaller bundle ready:" -ForegroundColor Green
    Write-Host "  $bundleDir\AcDecFlashcards.exe"
    Write-Host ""
    Write-Host "Install Inno Setup 6 and re-run without -SkipInno to produce Setup.exe."
    exit 0
}

$iscc = Find-InnoSetup
if (-not $iscc) {
    Fail "Inno Setup 6 not found. Install from https://jrsoftware.org/isinfo.php"
}

Write-Host "[4/4] Compiling installer with Inno Setup..."
Push-Location "$root\packaging"
& $iscc "/DAppSource=$bundleDir" "/DAppVersion=$buildVersion" "installer.iss"
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Inno Setup compilation failed." }
Pop-Location

$output = Get-ChildItem "$root\packaging\output\AcDecFlashcards-Setup-$buildVersion.exe" -ErrorAction SilentlyContinue
if (-not $output) {
    $output = Get-ChildItem "$root\packaging\output\AcDecFlashcards-Setup-*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
Write-Host ""
Write-Host "Done! (v$buildVersion)" -ForegroundColor Green
if ($output) {
    Write-Host "Installer: $($output.FullName)"
    Write-Host "Size: $([math]::Round($output.Length / 1MB, 1)) MB"
}
Write-Host ""
Write-Host "Give recipients ONLY the Setup.exe. Never include tools/ or license_private_key.pem."
