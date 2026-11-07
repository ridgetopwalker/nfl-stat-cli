<#
.SYNOPSIS
    nfl-stat-cli Run-Once Installer for Windows.
    Automatically installs Python 3 (if missing), pip (if missing), all required
    Python analytics packages (pandas, polars, pyarrow, nflreadpy, sportsdataverse),
    R nflreadr (if R is installed), optional local SLM (Ollama qwen2.5:1.5b),
    and registers the nfl-stat-cli command.
#>
param(
    [switch]$WithSLM = $false,
    [switch]$SkipLivePackages = $false
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ProjectRoot

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  NFL-STAT-CLI : One-Step Automated Installer (Windows)" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan

function Find-RealPython {
    # Refresh PATH from Machine and User registries
    $MachinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$UserPath;$MachinePath"

    $candidates = @("python", "python3", "py")
    foreach ($cmd in $candidates) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found -and $found.Source -notmatch "WindowsApps") {
            try {
                $ver = & $found.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver -match "^3\.") {
                    return $found.Source
                }
            } catch {}
        }
    }

    # Check common installation paths directly
    $searchDirs = @(
        "$env:LocalAppData\Programs\Python\Python312\python.exe",
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "$env:LocalAppData\Programs\Python\Python310\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Python312\python.exe"
    )
    foreach ($p in $searchDirs) {
        if (Test-Path $p) {
            return $p
        }
    }
    return $null
}

# ---------------------------------------------------------------------------
# 1. Ensure Python 3 is installed
# ---------------------------------------------------------------------------
$PythonExe = Find-RealPython
if (-not $PythonExe) {
    Write-Host "[1/5] Python 3 not found. Installing Python 3.12 automatically..." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    }
    $PythonExe = Find-RealPython
    if (-not $PythonExe) {
        Write-Host "      Downloading official Python 3.12.8 installer from python.org..." -ForegroundColor Yellow
        $installerUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        $installerPath = Join-Path $env:TEMP "python-3.12.8-amd64.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Write-Host "      Running silent Python installation (including pip and PATH)..." -ForegroundColor Yellow
        Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0" -Wait
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
        $PythonExe = Find-RealPython
    }
    if (-not $PythonExe) {
        Write-Host "ERROR: Could not automatically install Python 3. Please install Python 3.10+ from https://www.python.org and re-run." -ForegroundColor Red
        exit 1
    }
}
Write-Host "[1/5] Using Python: $PythonExe" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2. Ensure pip is installed and up to date
# ---------------------------------------------------------------------------
Write-Host "[2/5] Checking pip..." -ForegroundColor Cyan
& $PythonExe -m pip --version >$null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "      pip not found. Bootstrapping pip via ensurepip..." -ForegroundColor Yellow
    & $PythonExe -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) {
        Write-Host "      Downloading get-pip.py from bootstrap.pypa.io..." -ForegroundColor Yellow
        $getPipPath = Join-Path $env:TEMP "get-pip.py"
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPipPath -UseBasicParsing
        & $PythonExe $getPipPath
        Remove-Item $getPipPath -Force -ErrorAction SilentlyContinue
    }
}
& $PythonExe -m pip install --upgrade pip setuptools wheel --quiet
Write-Host "[2/5] pip is ready." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 3. Install required Python packages & nfl-stat-cli
# ---------------------------------------------------------------------------
if (-not $SkipLivePackages) {
    Write-Host "[3/5] Installing NFL analytics Python packages (pandas, polars, pyarrow, nflreadpy, sportsdataverse)..." -ForegroundColor Cyan
    & $PythonExe -m pip install pandas polars pyarrow nflreadpy
    & $PythonExe -m pip install --pre sportsdataverse
} else {
    Write-Host "[3/5] Skipping optional live packages (offline mode ready)." -ForegroundColor Yellow
}

Write-Host "      Installing nfl-stat-cli package..." -ForegroundColor Cyan
& $PythonExe -m pip install -e . --no-build-isolation
if ($LASTEXITCODE -ne 0) {
    & $PythonExe -m pip install -e .
}
Write-Host "[3/5] Python packages & nfl-stat-cli installed." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 4. Optional R (nflverse / nflreadr) & Local SLM (Ollama) setup
# ---------------------------------------------------------------------------
Write-Host "[4/5] Checking optional R (nflreadr) and Local SLM (Ollama)..." -ForegroundColor Cyan
$rscript = Get-Command Rscript -ErrorAction SilentlyContinue
if ($rscript) {
    Write-Host "      Rscript found. Ensuring 'nflreadr' is installed..." -ForegroundColor Cyan
    & Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))"
} else {
    Write-Host "      Rscript not found (optional - Python sportsdataverse/nflreadpy and built-in dataset are active)." -ForegroundColor DarkGray
}

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if ($WithSLM -and -not $ollama) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "      Installing Ollama for local Small Language Model support..." -ForegroundColor Cyan
        & winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
        $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    }
}
if ($ollama -and $WithSLM) {
    Write-Host "      Pulling lightweight local SLM (qwen2.5:1.5b) for natural language stat queries..." -ForegroundColor Cyan
    & ollama pull qwen2.5:1.5b
}

# ---------------------------------------------------------------------------
# 5. Create launcher wrapper & verify installation
# ---------------------------------------------------------------------------
$LauncherPath = Join-Path $ProjectRoot "nfl-stat-cli.bat"
$LauncherContent = "@echo off`r`n`"$PythonExe`" `"%~dp0nfl_stat_cli.py`" %*`r`n"
Set-Content -Path $LauncherPath -Value $LauncherContent -Encoding ASCII

Write-Host "[5/5] Verifying nfl-stat-cli installation..." -ForegroundColor Cyan
& $PythonExe (Join-Path $ProjectRoot "nfl_stat_cli.py") list-stats

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Green
Write-Host "  [OK] INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "  Run interactively:   .\nfl-stat-cli.bat" -ForegroundColor Yellow
Write-Host "  Or via Python:       python nfl_stat_cli.py" -ForegroundColor Yellow
Write-Host "  Diagram a play:      python nfl_stat_cli.py play --qb Mahomes --camera behind-offense" -ForegroundColor Yellow
Write-Host "                       python nfl_stat_cli.py play --qb Goff --camera behind-defense" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Green
