#!/usr/bin/env bash
# ==============================================================================
# nfl-stat-cli : Run-Once Installer for Linux, WSL & macOS (*nix)
# Usage:
#   ./install.sh        Compact UI (ASCII Art + Full-Width Progress Bar + 1-Line Live Command)
#   ./install.sh -v     Verbose mode (full command and pip output)
# ==============================================================================
set -e

VERBOSE=0
for arg in "$@"; do
    case "$arg" in
        -v|--verbose)
            VERBOSE=1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ANSI Colors
RESET="\033[0m"
BOLD="\033[1m"
DIM="\033[2m"
GOLD="\033[38;5;220m"
CYAN="\033[96m"
GREEN="\033[92m"
WHITE="\033[97m"
GRAY="\033[90m"
RED="\033[91m"

BANNER_WIDTH=90
BAR_INNER_WIDTH=83  # '[' (1) + 83 + '] ' (2) + '100%' (4) = 90 chars total (matches banner width)

print_banner() {
    printf "${BOLD}${GOLD}╔════════════════════════════════════════════════════════════════════════════════════════╗${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET}  ${BOLD}${CYAN}███╗   ██╗███████╗██╗         ███████╗████████╗ █████╗ ████████╗   ██████╗██╗     ██╗${RESET}  ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET}  ${BOLD}${CYAN}████╗  ██║██╔════╝██║         ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝  ██╔════╝██║     ██║${RESET}  ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET}  ${BOLD}${WHITE}██╔██╗ ██║█████╗  ██║   █████╗███████╗   ██║   ███████║   ██║     ██║     ██║     ██║${RESET}  ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET}  ${BOLD}${GREEN}██║╚██╗██║██╔══╝  ██║   ╚════╝╚════██║   ██║   ██╔══██║   ██║     ██║     ██║     ██║${RESET}  ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET}  ${BOLD}${GREEN}██║ ╚████║██║     ███████╗    ███████║   ██║   ██║  ██║   ██║     ╚██████╗███████╗██║${RESET}  ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET}  ${DIM}${WHITE}nflverse (R) + sportsdataverse-py (Python) • Custom Stat Engine & Play Visualizer     ${RESET}${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}╚════════════════════════════════════════════════════════════════════════════════════════╝${RESET}\n"
}

# Draw the 90-char progress bar on line 1 and the single overwriting command line on line 2
update_ui() {
    local pct="$1"
    local cmd_text="$2"
    if [ "$VERBOSE" -eq 1 ]; then
        return
    fi

    local filled=$(( (pct * BAR_INNER_WIDTH) / 100 ))
    local empty=$(( BAR_INNER_WIDTH - filled ))

    local bar_fill=""
    local bar_empty=""
    local i=0
    while [ $i -lt $filled ]; do
        bar_fill="${bar_fill}█"
        i=$(( i + 1 ))
    done
    i=0
    while [ $i -lt $empty ]; do
        bar_empty="${bar_empty}░"
        i=$(( i + 1 ))
    done

    # Truncate command text so it never wraps past 90 columns
    local clean_cmd
    clean_cmd="$(printf "%s" "$cmd_text" | tr -d '\r\n' | cut -c 1-86)"

    # Move cursor up 2 lines, clear & draw progress bar, move down & clear & draw single command line
    printf "\033[2A\r\033[2K"
    printf "${BOLD}${GOLD}[${GREEN}%s${GRAY}%s${GOLD}] %3d%%${RESET}\n" "$bar_fill" "$bar_empty" "$pct"
    printf "\r\033[2K${CYAN}❯${RESET} ${DIM}%s${RESET}\n" "$clean_cmd"
}

# Run a command: in verbose mode show all output; in default mode update the single command line live
run_cmd() {
    local pct_start="$1"
    local pct_end="$2"
    local display_cmd="$3"
    shift 3

    if [ "$VERBOSE" -eq 1 ]; then
        echo "  -> $display_cmd"
        "$@"
        return $?
    fi

    update_ui "$pct_start" "$display_cmd"
    set +e
    "$@" 2>&1 | while IFS= read -r line; do
        if [ -n "$line" ]; then
            update_ui "$pct_start" "$display_cmd  [$line]"
        fi
    done
    local status=${PIPESTATUS[0]}
    set -e
    update_ui "$pct_end" "$display_cmd"
    return $status
}

# ==============================================================================
# VERBOSE MODE (-v / --verbose): Original full-log installer
# ==============================================================================
if [ "$VERBOSE" -eq 1 ]; then
    echo "======================================================================"
    echo "  NFL-STAT-CLI : One-Step Automated Installer (*nix) [VERBOSE MODE]"
    echo "======================================================================"

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

    echo "[2/5] Checking pip..."
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        echo "      Bootstrapping pip..."
        "$PYTHON_BIN" -m ensurepip --upgrade || {
            curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
            "$PYTHON_BIN" /tmp/get-pip.py --user
            rm -f /tmp/get-pip.py
        }
    fi

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

    echo "[3/5] Installing NFL analytics Python packages (pandas, pyarrow, polars, nfl_data_py)..."
    "$PYTHON_BIN" -m pip install --only-binary=:all: pandas pyarrow polars || "$PYTHON_BIN" -m pip install pandas pyarrow polars || true
    "$PYTHON_BIN" -m pip install nfl_data_py || true
    "$PYTHON_BIN" -m pip install --only-binary=:all: nflreadpy >/dev/null 2>&1 || true
    "$PYTHON_BIN" -m pip install -e . --no-build-isolation || "$PYTHON_BIN" -m pip install -e .
    echo "[3/5] Python packages & nfl-stat-cli installed."

    echo "[4/5] Checking optional R (nflreadr)..."
    if command -v Rscript >/dev/null 2>&1; then
        Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))" || true
    fi

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
    exit 0
fi

# ==============================================================================
# DEFAULT COMPACT MODE: ASCII Art + Full-Width Progress Bar + Single-Line Command
# ==============================================================================
print_banner
# Reserve 2 lines below the ASCII art (Line 1: Progress Bar, Line 2: Latest Command)
printf "\n\n"
update_ui 2 "Checking Python 3 installation..."

if ! command -v python3 >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
        run_cmd 4 12 "brew install python" brew install python
    elif command -v apt-get >/dev/null 2>&1; then
        run_cmd 4 12 "sudo apt-get install -y python3 python3-pip python3-venv" bash -c "sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv"
    elif command -v dnf >/dev/null 2>&1; then
        run_cmd 4 12 "sudo dnf install -y python3 python3-pip" sudo dnf install -y python3 python3-pip
    elif command -v yum >/dev/null 2>&1; then
        run_cmd 4 12 "sudo yum install -y python3 python3-pip" sudo yum install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        run_cmd 4 12 "sudo pacman -Sy --noconfirm python python-pip" sudo pacman -Sy --noconfirm python python-pip
    elif command -v apk >/dev/null 2>&1; then
        run_cmd 4 12 "sudo apk add --no-cache python3 py3-pip" sudo apk add --no-cache python3 py3-pip
    else
        update_ui 12 "ERROR: Could not detect package manager to install Python 3."
        exit 1
    fi
fi

PYTHON_BIN="$(command -v python3)"
update_ui 15 "Found Python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"

if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    run_cmd 16 22 "$PYTHON_BIN -m ensurepip --upgrade" "$PYTHON_BIN" -m ensurepip --upgrade || {
        run_cmd 18 22 "curl https://bootstrap.pypa.io/get-pip.py && $PYTHON_BIN get-pip.py" bash -c "curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && $PYTHON_BIN /tmp/get-pip.py --user && rm -f /tmp/get-pip.py"
    }
fi

if [ ! -d ".venv" ]; then
    run_cmd 22 28 "$PYTHON_BIN -m venv .venv" "$PYTHON_BIN" -m venv .venv || true
fi
if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
fi

run_cmd 30 42 "pip install --upgrade pip setuptools wheel" "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel || true
run_cmd 42 68 "pip install --only-binary=:all: pandas pyarrow polars" "$PYTHON_BIN" -m pip install --only-binary=:all: pandas pyarrow polars || true
run_cmd 68 82 "pip install nfl_data_py" "$PYTHON_BIN" -m pip install nfl_data_py || true
run_cmd 82 88 "pip install --only-binary=:all: nflreadpy" "$PYTHON_BIN" -m pip install --only-binary=:all: nflreadpy || true
run_cmd 88 95 "pip install -e . --no-build-isolation" "$PYTHON_BIN" -m pip install -e . --no-build-isolation || run_cmd 90 95 "pip install -e ." "$PYTHON_BIN" -m pip install -e .

if command -v Rscript >/dev/null 2>&1; then
    run_cmd 95 98 "Rscript -e install.packages('nflreadr')" Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))" || true
fi

chmod +x "$SCRIPT_DIR/nfl_stat_cli.py"
run_cmd 98 100 "$PYTHON_BIN nfl_stat_cli.py --version" "$PYTHON_BIN" "$SCRIPT_DIR/nfl_stat_cli.py" --version
update_ui 100 "✔ Installed! Run: $PYTHON_BIN nfl_stat_cli.py  (use ./install.sh -v for verbose output)"
