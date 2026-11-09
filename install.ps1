<#
.SYNOPSIS
    nfl-stat-cli Run-Once Installer for Windows.
    Usage:
      .\install.ps1        Compact UI (ASCII Art + Full-Width Progress Bar + 1-Line Live Command)
      .\install.ps1 -v     Verbose mode (full command and pip output)

    Options:
      -SkipLivePackages     Explicit sample mode: skip the live NFL data packages. nfl-stat then
                            runs on the small built-in SAMPLE dataset.
      -WithLegacyNflDataPy  Also install the deprecated nfl_data_py fallback loader (opt-in;
                            nflreadpy is preferred on all supported Pythons).
      -WithSLM              Pull a small local model through Ollama (optional).

    Failures are not swallowed: if a required step fails the installer stops with a non-zero
    exit code and shows the end of the install log. Live-data packages are required unless
    -SkipLivePackages is passed explicitly.
#>
param(
    [Alias("v")]
    [switch]$VerboseMode = $false,
    [switch]$WithSLM = $false,
    [switch]$SkipLivePackages = $false,
    [switch]$WithLegacyNflDataPy = $false
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ProjectRoot
$LogFile = Join-Path $env:TEMP "nfl_stat_cli_install.log"
"" | Set-Content -Path $LogFile -Encoding UTF8 -ErrorAction SilentlyContinue

# Python installer fallback (used only when winget is unavailable). The SHA-256 below was
# computed on 2026-11-09 from the HTTPS download of this exact file from python.org (python.org
# no longer lists checksums for Windows installers). When bumping the version, recompute it and
# cross-check against the .sigstore / .asc files next to the installer on python.org; the
# Authenticode signature (Python Software Foundation) is also required at install time.
# This is the amd64 installer only; ARM64 Windows is told to install Python manually.
$PythonInstallerVersion = "3.13.17"
$PythonInstallerSha256 = "5da012101ba2e17113a9a1cd901e9ce1441086f2b7ecb5de06ec94163899a190"
$script:InstallWarnings = New-Object System.Collections.Generic.List[string]

function Add-InstallWarning([string]$Message) {
    $script:InstallWarnings.Add($Message)
}

function Stop-Install([string]$Message, [int]$Code = 1) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-InstallWarnings
    if ((Test-Path $LogFile) -and ((Get-Item $LogFile).Length -gt 0)) {
        Write-Host "Last lines of the install log ($LogFile):" -ForegroundColor Yellow
        Get-Content -Path $LogFile -Tail 25 | ForEach-Object { Write-Host $_ }
    }
    exit $Code
}

function Write-InstallWarnings {
    if ($script:InstallWarnings.Count -gt 0) {
        Write-Host ""
        Write-Host "Warnings:" -ForegroundColor Yellow
        foreach ($w in $script:InstallWarnings) { Write-Host "  - $w" -ForegroundColor Yellow }
    }
}

$LiveHint = "No live NFL data loader is available. Install nflreadpy (requirements-live.txt), or re-run with -WithLegacyNflDataPy for the deprecated loader. To accept the built-in SAMPLE dataset on purpose, re-run with -SkipLivePackages."

function Find-RealPython {
    $MachinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $Combined = "$env:Path;$UserPath;$MachinePath"
    $env:Path = (($Combined -split ";") | Where-Object { $_ -ne "" } | Select-Object -Unique) -join ";"

    $candidates = @("python", "python3", "py")
    foreach ($cmd in $candidates) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found -and $found.Source -notmatch "WindowsApps") {
            try {
                $ver = & $found.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null | Select-Object -Last 1
                if ($LASTEXITCODE -eq 0 -and $ver -match "^3\.(\d+)$" -and [int]$Matches[1] -ge 10) {
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
    if ($VerboseMode) { Write-Host "[1/5] Python 3 not found. Installing Python 3.13..." -ForegroundColor Yellow }
    else { Update-CompactUI 10 "winget install -e --id Python.Python.3.13" }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        if ($VerboseMode) {
            & winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
        } else {
            & winget install -e --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements >>$LogFile 2>&1
        }
    }
    $PythonExe = Find-RealPython
    if (-not $PythonExe) {
        if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64" -or $env:PROCESSOR_ARCHITEW6432 -eq "ARM64") {
            Stop-Install "Python 3.10+ is not installed and the bundled fallback installer is x64-only. Install Python for ARM64 from https://www.python.org/downloads/ (or with winget) and re-run."
        }
        $installerName = "python-$PythonInstallerVersion-amd64.exe"
        if (-not $VerboseMode) { Update-CompactUI 15 "Downloading $installerName from python.org..." }
        $installerUrl = "https://www.python.org/ftp/python/$PythonInstallerVersion/$installerName"
        $installerPath = Join-Path $env:TEMP $installerName
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing -ErrorAction Stop
        } catch {
            Stop-Install "Could not download $installerName from python.org: $($_.Exception.Message). Install Python 3.10+ manually from https://www.python.org/downloads/ and re-run."
        }
        $actualHash = (Get-FileHash -Path $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $PythonInstallerSha256) {
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            Stop-Install "SHA-256 mismatch for the downloaded $installerName (expected $PythonInstallerSha256, got $actualHash). The installer was deleted and NOT run."
        }
        $signature = Get-AuthenticodeSignature -FilePath $installerPath
        if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "O=Python Software Foundation") {
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
            Stop-Install "The downloaded $installerName is not validly signed by the Python Software Foundation (status: $($signature.Status)). The installer was deleted and NOT run."
        }
        Start-Process -FilePath $installerPath -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_test=0" -Wait
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
        $PythonExe = Find-RealPython
    }
    if (-not $PythonExe) {
        Stop-Install "Could not automatically install Python 3.10 or newer. Install it from https://www.python.org/downloads/ and re-run."
    }
}
if ($VerboseMode) { Write-Host "[1/5] Using Python: $PythonExe" -ForegroundColor Green }
else { Update-CompactUI 20 "Using Python: $PythonExe" }

# 2. Ensure virtual environment (.venv) and pip are ready
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    if ($VerboseMode) { Write-Host "[2/5] Creating virtual environment in .venv..." -ForegroundColor Cyan }
    else { Update-CompactUI 25 "$PythonExe -m venv .venv" }
    & $PythonExe -m venv $VenvDir >>$LogFile 2>&1
    if ($LASTEXITCODE -ne 0) {
        Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
        Add-InstallWarning "Could not create a .venv; installing into the system Python instead."
    }
}
if (Test-Path $VenvPy) {
    & $VenvPy -m pip --version >>$LogFile 2>&1
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = $VenvPy
    } else {
        Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
        Add-InstallWarning "The existing .venv had no working pip and was removed; installing into the system Python instead."
    }
}

if ($VerboseMode) { Write-Host "[2/5] Checking pip..." -ForegroundColor Cyan }
else { Update-CompactUI 28 "$PythonExe -m pip --version" }
& $PythonExe -m pip --version >>$LogFile 2>&1
if ($LASTEXITCODE -ne 0) {
    if (-not $VerboseMode) { Update-CompactUI 32 "$PythonExe -m ensurepip --upgrade" }
    & $PythonExe -m ensurepip --upgrade >>$LogFile 2>&1
    if ($LASTEXITCODE -ne 0) { Stop-Install "pip is not available and ensurepip failed. Reinstall Python with pip included and re-run." }
}
if (-not $VerboseMode) { Update-CompactUI 40 "$PythonExe -m pip install --upgrade pip setuptools wheel" }
& $PythonExe -m pip install --upgrade pip setuptools wheel --quiet >>$LogFile 2>&1
if ($LASTEXITCODE -ne 0) { Add-InstallWarning "Could not upgrade pip/setuptools/wheel; continuing with the installed versions." }

# 3. Install required Python packages & nfl-stat-cli
$RequirementsLive = Join-Path $ProjectRoot "requirements-live.txt"
if ($SkipLivePackages) {
    Add-InstallWarning "-SkipLivePackages: nfl-stat will use the built-in SAMPLE dataset, not live NFL data."
    if ($VerboseMode) { Write-Host "[3/5] -SkipLivePackages: skipping live NFL data packages (sample dataset only)." -ForegroundColor DarkYellow }
} else {
    if (-not (Test-Path $RequirementsLive)) { Stop-Install "requirements-live.txt not found next to install.ps1." }
    if ($VerboseMode) {
        Write-Host "[3/5] Installing live NFL data packages from requirements-live.txt (pandas, pyarrow, polars, nflreadpy)..." -ForegroundColor Cyan
        & $PythonExe -m pip install --only-binary=:all: -r $RequirementsLive
    } else {
        Update-CompactUI 55 "pip install --only-binary=:all: -r requirements-live.txt"
        & $PythonExe -m pip install --only-binary=:all: -r $RequirementsLive --quiet >>$LogFile 2>&1
    }
    if ($LASTEXITCODE -ne 0) { Stop-Install $LiveHint }
    if ($WithLegacyNflDataPy) {
        if (-not $VerboseMode) { Update-CompactUI 80 "pip install nfl_data_py (legacy, requested)" }
        & $PythonExe -m pip install "nfl_data_py>=0.3.0,<0.4" --quiet >>$LogFile 2>&1
        if ($LASTEXITCODE -ne 0) { Stop-Install "Could not install the requested legacy nfl_data_py." }
    }
}

if ($VerboseMode) {
    Write-Host "      Installing nfl-stat-cli package..." -ForegroundColor Cyan
    & $PythonExe -m pip install -e . --no-build-isolation
} else {
    Update-CompactUI 90 "pip install -e . --no-build-isolation"
    & $PythonExe -m pip install -e . --no-build-isolation >>$LogFile 2>&1
}
if ($LASTEXITCODE -ne 0) {
    # Retry with build isolation (needs network) before giving up.
    & $PythonExe -m pip install -e . >>$LogFile 2>&1
    if ($LASTEXITCODE -ne 0) { Stop-Install "Could not install nfl-stat-cli itself (pip install -e . failed)." }
}

# 4. Optional R & Optional Local SLM (Ollama)
$rscript = Get-Command Rscript -ErrorAction SilentlyContinue
if ($rscript) {
    if (-not $VerboseMode) { Update-CompactUI 94 "Rscript -e install.packages('nflreadr')" }
    & Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))" >>$LogFile 2>&1
    if ($LASTEXITCODE -ne 0) { Add-InstallWarning "Could not install the optional R package nflreadr (the R data bridge will be unavailable)." }
}

if ($WithSLM) {
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollama) {
        if ($VerboseMode) { Write-Host "[4/5] Pulling local SLM model (qwen2.5:1.5b) via Ollama..." -ForegroundColor Cyan }
        else { Update-CompactUI 96 "ollama pull qwen2.5:1.5b" }
        & ollama pull qwen2.5:1.5b >>$LogFile 2>&1
        if ($LASTEXITCODE -ne 0) { Add-InstallWarning "'ollama pull qwen2.5:1.5b' failed; the local language model is unavailable." }
    } elseif ($VerboseMode) {
        Write-Host "[4/5] Note: Ollama not found on PATH; skipping local SLM model pull." -ForegroundColor DarkYellow
    }
}

# 5. Ensure portable local folder launchers (nfl-stat.bat & nfl-stat-cli.bat) & verify
$LauncherContent = @"
@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0nfl_stat_cli.py" %*
) else (
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        py -3 "%~dp0nfl_stat_cli.py" %*
    ) else (
        python "%~dp0nfl_stat_cli.py" %*
    )
)
"@
Set-Content -Path (Join-Path $ProjectRoot "nfl-stat.bat") -Value $LauncherContent -Encoding ASCII
Set-Content -Path (Join-Path $ProjectRoot "nfl-stat-cli.bat") -Value $LauncherContent -Encoding ASCII

if ($VerboseMode) {
    Write-Host "[5/5] Verifying nfl-stat-cli installation..." -ForegroundColor Cyan
    & (Join-Path $ProjectRoot "nfl-stat.bat") list-stats
    $VerifyCode = $LASTEXITCODE
    if ($VerifyCode -eq 0) {
        Write-Host "  [OK] INSTALLATION COMPLETE! Run: .\nfl-stat" -ForegroundColor Green
    } else {
        Write-Host "  [!] Verification failed (see $LogFile)." -ForegroundColor Red
        exit $VerifyCode
    }
} else {
    Update-CompactUI 98 ".\nfl-stat.bat --version"
    & (Join-Path $ProjectRoot "nfl-stat.bat") --version >>$LogFile 2>&1
    $VerifyCode = $LASTEXITCODE
    if ($VerifyCode -eq 0) {
        Update-CompactUI 100 "Done! Run: .\nfl-stat  (or .\install.ps1 -v for verbose)"
        Write-Host ""
    } else {
        Update-CompactUI 100 "ERROR: Verification failed (log: $LogFile)."
        Write-Host ""
        exit $VerifyCode
    }
}

# A "successful" install must not silently leave the user on the built-in sample dataset.
if (-not $SkipLivePackages) {
    & $PythonExe -c "import nflreadpy" 2>$null
    $LiveOk = ($LASTEXITCODE -eq 0)
    if (-not $LiveOk -and $WithLegacyNflDataPy) {
        & $PythonExe -c "import nfl_data_py" 2>$null
        $LiveOk = ($LASTEXITCODE -eq 0)
    }
    if (-not $LiveOk) {
        Stop-Install "Installation finished but no live data loader can be imported, so nfl-stat would silently fall back to SAMPLE data. $LiveHint"
    }
}
Write-InstallWarnings

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
