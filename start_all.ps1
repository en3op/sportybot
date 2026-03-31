# SportyBot Local Launcher - PowerShell Wrapper
# Checks prerequisites and starts all services

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "SportyBot Local Launcher" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Check Tesseract
$TesseractPath = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (Test-Path $TesseractPath) {
    Write-Host "[OK] Tesseract found: $TesseractPath" -ForegroundColor Green
} else {
    Write-Host "[WARN] Tesseract not found at: $TesseractPath" -ForegroundColor Yellow
    Write-Host "       OCR features will not work. Install from:" -ForegroundColor Yellow
    Write-Host "       https://github.com/UB-Mannheim/tesseract/wiki" -ForegroundColor Yellow
}

# Check Python
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    Write-Host "[ERROR] Python not found in PATH" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python: $($PythonCmd.Source)" -ForegroundColor Green

# Check virtual environment
$VenvPath = Join-Path $ProjectDir "venv"
$VenvActivate = Join-Path $VenvPath "Scripts\Activate.ps1"

if (Test-Path $VenvActivate) {
    Write-Host "[OK] Virtual environment found, activating..." -ForegroundColor Green
    & $VenvActivate
} else {
    Write-Host "[INFO] No virtual environment found, using system Python" -ForegroundColor Yellow
}

# Check dependencies
$RequirementsPath = Join-Path $ProjectDir "requirements.txt"
if (Test-Path $RequirementsPath) {
    Write-Host "[INFO] Checking dependencies..." -ForegroundColor Cyan
    $RequiredPkgs = @("python-telegram-bot", "Pillow", "requests", "flask", "schedule")
    
    foreach ($Pkg in $RequiredPkgs) {
        $Installed = pip show $Pkg 2>$null
        if (-not $Installed) {
            Write-Host "[WARN] Missing package: $Pkg" -ForegroundColor Yellow
        }
    }
}

# Create logs directory
$LogsDir = Join-Path $ProjectDir "logs"
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null
    Write-Host "[OK] Created logs directory" -ForegroundColor Green
}

Write-Host ""
Write-Host "Starting all services..." -ForegroundColor Cyan
Write-Host ""

# Run the Python launcher
Set-Location $ProjectDir
& python run_local.py
