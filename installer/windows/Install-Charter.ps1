# Charter - AI Governance Layer - Windows Installer
# Double-click Install-Charter.bat to run this script.

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  Charter - AI Governance Layer" -ForegroundColor Green
Write-Host "  Installing..." -ForegroundColor Gray
Write-Host ""

# Step 1: Find Python
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 9) {
                $python = $cmd
                Write-Host "  Found $ver" -ForegroundColor Green
                break
            }
        }
    } catch {
        continue
    }
}

if (-not $python) {
    Write-Host ""
    Write-Host "  Python 3.9 or later is required." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Please install Python from:" -ForegroundColor Yellow
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Make sure to check 'Add Python to PATH' during install." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit 1
}

# Step 2: Install charter-governance
Write-Host "  Installing charter-governance from PyPI..." -ForegroundColor Gray
try {
    & $python -m pip install --upgrade charter-governance 2>&1 | Out-Null
    Write-Host "  Installed successfully." -ForegroundColor Green
} catch {
    Write-Host "  Trying with --user flag..." -ForegroundColor Yellow
    try {
        & $python -m pip install --user --upgrade charter-governance 2>&1 | Out-Null
        Write-Host "  Installed successfully (user mode)." -ForegroundColor Green
    } catch {
        Write-Host "  Installation failed. Check your Python and pip setup." -ForegroundColor Red
        Read-Host "  Press Enter to exit"
        exit 1
    }
}

# Step 3: Initialize Charter
$charterDir = Join-Path $env:USERPROFILE ".charter"
if (-not (Test-Path (Join-Path $charterDir "identity.json"))) {
    Write-Host "  Setting up your governance identity..." -ForegroundColor Gray
    try {
        & $python -m charter init --domain general --non-interactive 2>&1 | Out-Null
        Write-Host "  Identity created." -ForegroundColor Green
    } catch {
        Write-Host "  Could not initialize. Run 'charter init' manually." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Governance identity already exists." -ForegroundColor Green
}

# Done
Write-Host ""
Write-Host "  ============================================" -ForegroundColor Green
Write-Host "  Charter is installed and ready." -ForegroundColor Green
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Your governance data: $charterDir" -ForegroundColor Gray
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "    charter status     - See your governance status" -ForegroundColor Gray
Write-Host "    charter serve      - Open the dashboard" -ForegroundColor Gray
Write-Host "    charter update     - Check for updates" -ForegroundColor Gray
Write-Host ""
Write-Host "  If you use VS Code, search 'Charter Governance'" -ForegroundColor Gray
Write-Host "  in the Extensions panel to install the indicator." -ForegroundColor Gray
Write-Host ""
