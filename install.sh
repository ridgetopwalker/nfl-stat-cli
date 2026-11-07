#!/usr/bin/env bash
# ==============================================================================
# nfl-stat-cli : Run-Once Installer for Linux & macOS (*nix)
# Automatically installs Python 3 (if missing), pip (if missing), all required
# Python analytics packages (pandas, polars, pyarrow, nflreadpy, sportsdataverse),
# R nflreadr (if R is installed), and sets up nfl-stat-cli.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================================"
echo "  NFL-STAT-CLI : One-Step Automated Installer (*nix)"
echo "======================================================================"

# 1. Ensure Python 3 is installed
if ! command -v python3 >/dev/null 2>&1; then
    echo "[1/5] Python 3 not found. Installing Python 3..."
    if command -v brew >/dev/null 2>&1; then
        brew install python
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Sy --noconfirm python python-pip
    elif command -v apk >/dev/null 2>&1; then
        sudo apk add --no-cache python3 py3-pip
    else
        echo "ERROR: Could not detect system package manager to install Python 3."
        exit 1
    fi
fi
PYTHON_BIN="$(command -v python3)"
echo "[1/5] Using Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

# 2. Ensure pip is available
echo "[2/5] Checking pip..."
if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    echo "      Bootstrapping pip..."
    "$PYTHON_BIN" -m ensurepip --upgrade || {
        curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
        "$PYTHON_BIN" /tmp/get-pip.py --user
        rm -f /tmp/get-pip.py
    }
fi

# Create or use local virtual environment (.venv) if system Python is externally managed (PEP 668)
PIP_ARGS=""
if [ ! -d ".venv" ]; then
    if "$PYTHON_BIN" -m venv .venv >/dev/null 2>&1; then
        echo "      Created virtual environment in $SCRIPT_DIR/.venv"
    fi
fi
if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
fi

"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel --quiet || true
echo "[2/5] pip is ready."

# 3. Install required Python packages & nfl-stat-cli
echo "[3/5] Installing NFL analytics Python packages (pandas, polars, pyarrow, nfl_data_py, sportsdataverse)..."
"$PYTHON_BIN" -m pip install pandas polars pyarrow || true
"$PYTHON_BIN" -m pip install nfl_data_py || true
"$PYTHON_BIN" -m pip install --pre sportsdataverse || true
"$PYTHON_BIN" -m pip install nflreadpy >/dev/null 2>&1 || true
"$PYTHON_BIN" -m pip install -e . --no-build-isolation || "$PYTHON_BIN" -m pip install -e .
echo "[3/5] Python packages & nfl-stat-cli installed."

# 4. Optional R (nflreadr) check
echo "[4/5] Checking optional R (nflreadr)..."
if command -v Rscript >/dev/null 2>&1; then
    Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))" || true
fi

# 5. Create executable launcher & verify
chmod +x "$SCRIPT_DIR/nfl_stat_cli.py"
echo "[5/5] Verifying nfl-stat-cli installation..."
"$PYTHON_BIN" "$SCRIPT_DIR/nfl_stat_cli.py" list-stats

echo ""
echo "======================================================================"
echo "  ✔ INSTALLATION COMPLETE!"
echo "  Run interactively:   $PYTHON_BIN nfl_stat_cli.py"
echo "  Diagram a play:      $PYTHON_BIN nfl_stat_cli.py play --qb Mahomes --camera behind-offense"
echo "                       $PYTHON_BIN nfl_stat_cli.py play --qb Goff --camera behind-defense"
echo "======================================================================"
