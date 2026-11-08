<#
.SYNOPSIS
    nfl-stat-cli Run-Once Installer for Windows.
    Usage:
      .\install.ps1        Compact UI (ASCII Art + Full-Width Progress Bar + 1-Line Live Command)
      .\install.ps1 -v     Verbose mode (full command and pip output)
#>
param(
    [Alias("v")]
    [switch]$VerboseMode = $false,
    [switch]$WithSLM = $false,
    [switch]$SkipLivePackages = $false
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ProjectRoot

function Find-RealPython {
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

$BarInnerWidth = 82  # '[' (1) + 82 + '] ' (2) + '100%' (4) = 89 chars total (matches banner width)

function Update-CompactUI([int]$Percent, [string]$CommandText) {
    if ($VerboseMode) { return }
    $filled = [Math]::Floor(($Percent * $BarInnerWidth) / 100)
    $empty = $BarInnerWidth - $filled
    $barStr = "[" + ("#" * $filled) + ("-" * $empty) + ("] {0,3}%" -f $Percent)
    $cleanCmd = ($CommandText -replace "[\r\n]+", " ")
    if ($cleanCmd.Length -gt 85) {
        $cleanCmd = $cleanCmd.Substring(0, 85)
    }
    $esc = [char]27
    [Console]::Write("`r$esc[2K$esc[1A`r$esc[2K")
    Write-Host $barStr -ForegroundColor Yellow
    [Console]::Write("> " + $cleanCmd)
}

if ($VerboseMode) {
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "  NFL-STAT-CLI : One-Step Automated Installer (Windows) [VERBOSE MODE]" -ForegroundColor Yellow
    Write-Host "======================================================================" -ForegroundColor Cyan
} else {
    $PythonPreview = Find-RealPython
    if ($PythonPreview) {
        & $PythonPreview -c "import nfl_stat_cli; print(nfl_stat_cli.AsciiArtRenderer.banner())" 2>$null
    } else {
        Write-Host "+=======================================================================================+" -ForegroundColor Yellow
        Write-Host "|  NFL-STAT-CLI : nflverse (R) + sportsdataverse-py (Python) Custom Stat & Play Engine  |" -ForegroundColor Cyan
        Write-Host "+=======================================================================================+" -ForegroundColor Yellow
    }
    Write-Host ""
    Update-CompactUI 5 "Checking Python 3 installation..."
}

# 1. Ensure Python 3 is installed
$PythonExe = Find-RealPython
if (-not $PythonExe) {
    if ($VerboseMode) { Write-Host "[1/5] Python 3 not found. Installing Python 3.12..." -ForegroundColor Yellow }
    else { Update-CompactUI 10 "winget install -e --id Python.Python.3.12" }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        if ($VerboseMode) {
            & winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        } else {
            & winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements >$null 2>&1
        }
    }
    $PythonExe = Find-RealPython
    if (-not $PythonExe) {
        if (-not $VerboseMode) { Update-CompactUI 15 "Downloading python-3.12.8-amd64.exe from python.org..." }
        $installerUrl = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        $installerPath = Join-Path $env:TEMP "python-3.12.8-amd64.exe"
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing
        Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0" -Wait
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
        $PythonExe = Find-RealPython
    }
    if (-not $PythonExe) {
        Write-Host ""
        Write-Host "ERROR: Could not automatically install Python 3." -ForegroundColor Red
        exit 1
    }
}
if ($VerboseMode) { Write-Host "[1/5] Using Python: $PythonExe" -ForegroundColor Green }
else { Update-CompactUI 20 "Using Python: $PythonExe" }

# 2. Ensure pip is installed
if ($VerboseMode) { Write-Host "[2/5] Checking pip..." -ForegroundColor Cyan }
else { Update-CompactUI 28 "$PythonExe -m pip --version" }
& $PythonExe -m pip --version >$null 2>&1
if ($LASTEXITCODE -ne 0) {
    if (-not $VerboseMode) { Update-CompactUI 32 "$PythonExe -m ensurepip --upgrade" }
    & $PythonExe -m ensurepip --upgrade >$null 2>&1
}
if (-not $VerboseMode) { Update-CompactUI 40 "$PythonExe -m pip install --upgrade pip setuptools wheel" }
& $PythonExe -m pip install --upgrade pip setuptools wheel --quiet

# 3. Install required Python packages & nfl-stat-cli
if (-not $SkipLivePackages) {
    if ($VerboseMode) {
        Write-Host "[3/5] Installing NFL analytics Python packages (pandas, pyarrow, polars, nfl_data_py)..." -ForegroundColor Cyan
        & $PythonExe -m pip install --only-binary=:all: pandas pyarrow polars
        & $PythonExe -m pip install nfl_data_py
        & $PythonExe -m pip install --only-binary=:all: nflreadpy >$null 2>&1
    } else {
        Update-CompactUI 55 "pip install --only-binary=:all: pandas pyarrow polars"
        & $PythonExe -m pip install --only-binary=:all: pandas pyarrow polars --quiet
        Update-CompactUI 75 "pip install nfl_data_py"
        & $PythonExe -m pip install nfl_data_py --quiet
        Update-CompactUI 82 "pip install --only-binary=:all: nflreadpy"
        & $PythonExe -m pip install --only-binary=:all: nflreadpy >$null 2>&1
    }
}

if ($VerboseMode) {
    Write-Host "      Installing nfl-stat-cli package..." -ForegroundColor Cyan
    & $PythonExe -m pip install -e . --no-build-isolation
} else {
    Update-CompactUI 90 "pip install -e . --no-build-isolation"
    & $PythonExe -m pip install -e . --no-build-isolation >$null 2>&1
}

# 4. Optional R
$rscript = Get-Command Rscript -ErrorAction SilentlyContinue
if ($rscript) {
    if (-not $VerboseMode) { Update-CompactUI 95 "Rscript -e install.packages('nflreadr')" }
    & Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))" >$null 2>&1
}

# 5. Create local folder launchers (nfl-stat.bat & nfl-stat-cli.bat) & verify
$LauncherContent = "@echo off`r`n`"$PythonExe`" `"%~dp0nfl_stat_cli.py`" %*`r`n"
Set-Content -Path (Join-Path $ProjectRoot "nfl-stat.bat") -Value $LauncherContent -Encoding ASCII
Set-Content -Path (Join-Path $ProjectRoot "nfl-stat-cli.bat") -Value $LauncherContent -Encoding ASCII

if ($VerboseMode) {
    Write-Host "[5/5] Verifying nfl-stat-cli installation..." -ForegroundColor Cyan
    & (Join-Path $ProjectRoot "nfl-stat.bat") list-stats
    $VerifyCode = $LASTEXITCODE
    if ($VerifyCode -eq 0) {
        Write-Host "  [OK] INSTALLATION COMPLETE! Run: .\nfl-stat" -ForegroundColor Green
    }
} else {
    Update-CompactUI 98 ".\nfl-stat.bat --version"
    & (Join-Path $ProjectRoot "nfl-stat.bat") --version >$null 2>&1
    $VerifyCode = $LASTEXITCODE
    if ($VerifyCode -eq 0) {
        Update-CompactUI 100 "Done! Run: .\nfl-stat  (or .\install.ps1 -v for verbose)"
    } else {
        Update-CompactUI 100 "ERROR: Verification failed."
    }
    Write-Host ""
}

if ($VerifyCode -eq 0 -and [Environment]::UserInteractive) {
    $ans = Read-Host "? Add 'nfl-stat' to your PATH so you can run it from anywhere? [y/N]"
    if ($ans -match "^[yY]") {
        $CurrentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
        $PathParts = ($CurrentUserPath -split ";") | Where-Object { $_ -ne "" }
        if ($PathParts -notcontains $ProjectRoot) {
            $NewUserPath = ($PathParts + $ProjectRoot) -join ";"
            [System.Environment]::SetEnvironmentVariable("Path", $NewUserPath, "User")
        }
        if (($env:Path -split ";") -notcontains $ProjectRoot) {
            $env:Path = "$ProjectRoot;$env:Path"
        }
        Write-Host "[OK] Added '$ProjectRoot' to your PATH! You can now run 'nfl-stat' from anywhere." -ForegroundColor Green
    } else {
        Write-Host "Skipped adding to global PATH. You can run '.\nfl-stat' in this folder anytime." -ForegroundColor DarkGray
    }
}
