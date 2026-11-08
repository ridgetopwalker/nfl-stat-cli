#!/usr/bin/env bash
# ==============================================================================
# nfl-stat-cli : Run-Once Installer for Linux, WSL & macOS (*nix)
# Usage:
#   ./install.sh        Compact UI (ASCII Art + 1 Progress Bar Line + 1 Command Line)
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

print_banner() {
    printf "${BOLD}${GOLD}╔══════════════════════════════════════════════════════════════════════════════════════╗${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${CYAN}███╗   ██╗███████╗██╗         ███████╗████████╗ █████╗ ████████╗   ██████╗██╗     ██╗${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${CYAN}████╗  ██║██╔════╝██║         ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝  ██╔════╝██║     ██║${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${WHITE}██╔██╗ ██║█████╗  ██║   █████╗███████╗   ██║   ███████║   ██║     ██║     ██║     ██║${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${GREEN}██║╚██╗██║██╔══╝  ██║   ╚════╝╚════██║   ██║   ██╔══██║   ██║     ██║     ██║     ██║${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${GREEN}██║ ╚████║██║     ███████╗    ███████║   ██║   ██║  ██║   ██║     ╚██████╗███████╗██║${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${DIM}${WHITE}nflverse (R) + sportsdataverse-py (Python) • Custom Stat Engine & Play Visualizer   ${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}╚══════════════════════════════════════════════════════════════════════════════════════╝${RESET}\n"
}

# ==============================================================================
# VERBOSE MODE (-v / --verbose): Full-log installer
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
# DEFAULT COMPACT MODE:
# 1. Prints the ASCII art banner
# 2. Below that: ONE progress bar line (exact width of banner, capped to terminal width so it never wraps)
# 3. Below that: ONE command line that overwrites itself in-place
# ==============================================================================
LOG_FILE="/tmp/nfl_stat_cli_install.log"
: > "$LOG_FILE"

TERM_COLS="$(tput cols 2>/dev/null || echo 88)"
TARGET_WIDTH=88
if [ "$TERM_COLS" -lt 89 ] 2>/dev/null; then
    TARGET_WIDTH=$(( TERM_COLS - 1 ))
fi
if [ "$TARGET_WIDTH" -lt 30 ]; then
    TARGET_WIDTH=30
fi
# '[' (1) + BAR_INNER_WIDTH + '] ' (2) + '100%' (4) = TARGET_WIDTH
BAR_INNER_WIDTH=$(( TARGET_WIDTH - 7 ))
CMD_MAX_LEN=$(( TARGET_WIDTH - 4 ))

# Redraw the single progress bar line (Line 1) and single command line (Line 2) in-place
update_ui() {
    local pct="$1"
    local cmd_text="$2"

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

    local clean_cmd="${cmd_text:0:$CMD_MAX_LEN}"

    # Cursor rests on Line 2 (command line).
    # Clear Line 2, move up 1 line to Line 1 (progress bar), clear Line 1, print bar + \n, print command (no \n).
    printf "\r\033[2K\033[1A\r\033[2K"
    printf "${BOLD}${GOLD}[${GREEN}%s${GRAY}%s${GOLD}] %3d%%${RESET}\n" "$bar_fill" "$bar_empty" "$pct"
    printf "${CYAN}❯${RESET} ${DIM}%s${RESET}" "$clean_cmd"
}

run_step() {
    local pct_start="$1"
    local pct_end="$2"
    local display_cmd="$3"
    shift 3

    update_ui "$pct_start" "$display_cmd"
    "$@" >>"$LOG_FILE" 2>&1
    local rc=$?
    update_ui "$pct_end" "$display_cmd"
    return $rc
}

print_banner
# Create Line 1 (progress bar) and move cursor onto Line 2 (command line)
printf "\n"

update_ui 5 "Checking Python 3 installation..."
if ! command -v python3 >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
        run_step 5 15 "brew install python" brew install python
    elif command -v apt-get >/dev/null 2>&1; then
        run_step 5 15 "sudo apt-get install -y python3 python3-pip python3-venv" bash -c "sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv"
    elif command -v dnf >/dev/null 2>&1; then
        run_step 5 15 "sudo dnf install -y python3 python3-pip" sudo dnf install -y python3 python3-pip
    elif command -v yum >/dev/null 2>&1; then
        run_step 5 15 "sudo yum install -y python3 python3-pip" sudo yum install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        run_step 5 15 "sudo pacman -Sy --noconfirm python python-pip" sudo pacman -Sy --noconfirm python python-pip
    elif command -v apk >/dev/null 2>&1; then
        run_step 5 15 "sudo apk add --no-cache python3 py3-pip" sudo apk add --no-cache python3 py3-pip
    else
        update_ui 15 "ERROR: Could not detect package manager to install Python 3."
        printf "\n"
        exit 1
    fi
fi

PYTHON_BIN="$(command -v python3)"
update_ui 15 "command -v python3 -> $PYTHON_BIN"

if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    run_step 15 25 "$PYTHON_BIN -m ensurepip --upgrade" "$PYTHON_BIN" -m ensurepip --upgrade || {
        run_step 18 25 "curl https://bootstrap.pypa.io/get-pip.py && $PYTHON_BIN get-pip.py" bash -c "curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && $PYTHON_BIN /tmp/get-pip.py --user && rm -f /tmp/get-pip.py"
    }
fi

if [ ! -d ".venv" ]; then
    run_step 25 32 "$PYTHON_BIN -m venv .venv" "$PYTHON_BIN" -m venv .venv || true
fi
if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
fi

run_step 32 45 "pip install --upgrade pip setuptools wheel" "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel || true
run_step 45 70 "pip install --only-binary=:all: pandas pyarrow polars" "$PYTHON_BIN" -m pip install --only-binary=:all: pandas pyarrow polars || true
run_step 70 84 "pip install nfl_data_py" "$PYTHON_BIN" -m pip install nfl_data_py || true
run_step 84 90 "pip install --only-binary=:all: nflreadpy" "$PYTHON_BIN" -m pip install --only-binary=:all: nflreadpy || true
run_step 90 96 "pip install -e . --no-build-isolation" "$PYTHON_BIN" -m pip install -e . --no-build-isolation || run_step 92 96 "pip install -e ." "$PYTHON_BIN" -m pip install -e .

if command -v Rscript >/dev/null 2>&1; then
    run_step 96 98 "Rscript -e install.packages('nflreadr')" Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))" || true
fi

chmod +x "$SCRIPT_DIR/nfl_stat_cli.py"
run_step 98 100 "$PYTHON_BIN nfl_stat_cli.py --version" "$PYTHON_BIN" "$SCRIPT_DIR/nfl_stat_cli.py" --version
update_ui 100 "Done! Run: $PYTHON_BIN nfl_stat_cli.py  (or ./install.sh -v for verbose)"
printf "\n"
