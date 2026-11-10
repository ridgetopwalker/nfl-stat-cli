#!/usr/bin/env bash
# ==============================================================================
# pro-football-slm : Run-Once Installer for Linux, WSL & macOS (*nix)
# Usage:
#   ./install.sh        Compact UI (ASCII Art + 1 Progress Bar Line + 1 Command Line)
#   ./install.sh -v     Verbose mode (full command and pip output)
#
# Options:
#   --sample-only                Skip the live NFL data packages. pro-football-slm then runs on the
#                                small built-in SAMPLE dataset (it says so on every run).
#   --with-legacy-nfl-data-py    Also install the deprecated nfl_data_py fallback loader
#                                (opt-in; nflreadpy is preferred on all supported Pythons).
#   --yes                        Allow commands that need administrator rights (sudo) to run
#                                without asking (needed when stdin is not a terminal).
#
# Failures are NOT swallowed: if a required step fails the installer stops with a non-zero
# exit status and shows where to look. Live-data packages are required unless you pass
# --sample-only explicitly.
# ==============================================================================
set -e

VERBOSE=0
SAMPLE_ONLY=0
WITH_LEGACY=0
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        -v|--verbose)
            VERBOSE=1
            ;;
        --sample-only)
            SAMPLE_ONLY=1
            ;;
        --with-legacy-nfl-data-py)
            WITH_LEGACY=1
            ;;
        -y|--yes)
            ASSUME_YES=1
            ;;
        -h|--help)
            sed -n '2,/^set -e/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Unknown option: $arg (see ./install.sh --help)" >&2
            exit 2
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
    printf "${BOLD}${GOLD}╔═══════════════════════════════════════════════════════════════════════════════════════╗${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${CYAN}███╗   ██╗███████╗██╗         ███████╗████████╗ █████╗ ████████╗   ██████╗██╗     ██╗${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${CYAN}████╗  ██║██╔════╝██║         ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝  ██╔════╝██║     ██║${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${WHITE}██╔██╗ ██║█████╗  ██║   █████╗███████╗   ██║   ███████║   ██║     ██║     ██║     ██║${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${GREEN}██║╚██╗██║██╔══╝  ██║   ╚════╝╚════██║   ██║   ██╔══██║   ██║     ██║     ██║     ██║${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${BOLD}${GREEN}██║ ╚████║██║     ███████╗    ███████║   ██║   ██║  ██║   ██║     ╚██████╗███████╗██║${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}║${RESET} ${DIM}${WHITE}nflverse (R) + sportsdataverse-py (Python) • Custom Stat Engine & Play Visualizer    ${RESET} ${BOLD}${GOLD}║${RESET}\n"
    printf "${BOLD}${GOLD}╚═══════════════════════════════════════════════════════════════════════════════════════╝${RESET}\n"
}

create_local_launcher() {
    cat > "$SCRIPT_DIR/pro-football-slm" <<'EOF'
#!/usr/bin/env bash
# Launcher for pro-football-slm in the project directory or via PATH symlink
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

# Run the package in-place (works without `pip install`, from any directory).
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    exec "$SCRIPT_DIR/.venv/bin/python" -m pro_football_slm "$@"
else
    exec python3 -m pro_football_slm "$@"
fi
EOF
    chmod +x "$SCRIPT_DIR/pro-football-slm"
    for launcher_name in pfslm nfl-stat; do
        cp "$SCRIPT_DIR/pro-football-slm" "$SCRIPT_DIR/$launcher_name"
        chmod +x "$SCRIPT_DIR/$launcher_name"
    done
}

WARNINGS=()
LOG_FILE=""

warn() {
    WARNINGS+=("$1")
}

die() {
    printf "\n${BOLD}ERROR:${RESET} %s\n" "$1" >&2
    print_warnings >&2
    if [ -n "$LOG_FILE" ] && [ -s "$LOG_FILE" ]; then
        printf "Last lines of the install log (%s):\n" "$LOG_FILE" >&2
        tail -n 25 "$LOG_FILE" >&2
    fi
    exit 1
}

print_warnings() {
    if [ "${#WARNINGS[@]}" -gt 0 ]; then
        printf "\n${BOLD}Warnings:${RESET}\n"
        for w in "${WARNINGS[@]}"; do
            printf "  - %s\n" "$w"
        done
    fi
}

# Commands that need administrator rights are never run silently.
confirm_sudo() {
    local what="$1"
    if [ "$ASSUME_YES" -eq 1 ]; then
        return 0
    fi
    if [ ! -t 0 ]; then
        die "Python 3 is missing and installing it needs administrator rights ($what). Install Python 3.10+ yourself, or re-run with --yes."
    fi
    printf "\n${BOLD}${CYAN}?${RESET} Python 3 is missing. Run '%s' with administrator rights? [y/N]: " "$what"
    read -r ans || ans=""
    case "$ans" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) die "Cancelled: install Python 3.10+ yourself and re-run ./install.sh." ;;
    esac
}

check_python_version() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
        || die "Python 3.10 or newer is required ($1 reports $("$1" --version 2>&1))."
}

install_live_requirements_hint() {
    echo "No live NFL data loader is available. Install nflreadpy (pandas, pyarrow, polars, nflreadpy in requirements-live.txt), or re-run with --with-legacy-nfl-data-py for the deprecated loader. To accept the built-in SAMPLE dataset on purpose, re-run with --sample-only."
}

verify_live_data() {
    if [ "$SAMPLE_ONLY" -eq 1 ]; then
        warn "Sample-only install: pro-football-slm will use the built-in SAMPLE dataset, not live NFL data."
        return 0
    fi
    if "$PYTHON_BIN" -c 'import nflreadpy' >/dev/null 2>&1; then
        return 0
    fi
    if [ "$WITH_LEGACY" -eq 1 ] && "$PYTHON_BIN" -c 'import nfl_data_py' >/dev/null 2>&1; then
        return 0
    fi
    die "Installation finished but no live data loader can be imported, so pro-football-slm would silently fall back to SAMPLE data. $(install_live_requirements_hint)"
}

link_path_command() {
    local destination="$1"
    local command_name="$2"
    local target="$destination/$command_name"
    if [ ! -e "$target" ] || [ -L "$target" ]; then
        ln -sfn "$SCRIPT_DIR/$command_name" "$target" || warn "Could not link $target."
    else
        printf 'Warning: keeping existing command %s; skipping link.\n' "$target" >&2
    fi
}

prompt_add_to_path() {
    if [ ! -t 0 ]; then
        return 0
    fi
    printf "${BOLD}${CYAN}?${RESET} Add ${BOLD}pro-football-slm${RESET} to your PATH so you can run it from anywhere? [y/N]: "
    read -r ans || true
    case "$ans" in
        [yY]|[yY][eE][sS])
            mkdir -p "$HOME/.local/bin"
            for command in pro-football-slm pfslm nfl-stat; do
                link_path_command "$HOME/.local/bin" "$command"
            done
            for rc_file in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
                if [ -f "$rc_file" ] && ! grep -q '\.local/bin' "$rc_file" 2>/dev/null; then
                    printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc_file"
                fi
            done
            if [ -w "/usr/local/bin" ]; then
                for command in pro-football-slm pfslm nfl-stat; do
                    link_path_command "/usr/local/bin" "$command"
                done
            fi
            printf "${GREEN}✔ Added 'pro-football-slm' to PATH (~/.local/bin/pro-football-slm)! You can now run 'pro-football-slm' from anywhere (or './pro-football-slm' here).${RESET}\n"
            ;;
        *)
            printf "${DIM}Skipped adding to global PATH. You can run './pro-football-slm' in this folder anytime.${RESET}\n"
            ;;
    esac
}

bootstrap_pip_safe() {
    # ensurepip ships with Python. We deliberately do not download and execute get-pip.py:
    # it has no published checksum, so there is nothing to verify it against.
    local py_bin="$1"
    "$py_bin" -m ensurepip --upgrade || {
        echo "pip is not available for $py_bin and ensurepip failed." >&2
        echo "Install pip with your package manager (e.g. python3-pip / python3-venv) and re-run ./install.sh." >&2
        return 1
    }
}

# ==============================================================================
# VERBOSE MODE (-v / --verbose): Full-log installer
# ==============================================================================
if [ "$VERBOSE" -eq 1 ]; then
    echo "======================================================================"
    echo "  Pro Football SLM : One-Step Automated Installer (*nix) [VERBOSE MODE]"
    echo "======================================================================"

    if ! command -v python3 >/dev/null 2>&1; then
        echo "[1/5] Python 3 not found. Installing Python 3..."
        if command -v brew >/dev/null 2>&1; then
            brew install python || die "Python 3 installation failed (brew install python)."
        elif command -v apt-get >/dev/null 2>&1; then
            confirm_sudo "sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv"
            sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv
        elif command -v dnf >/dev/null 2>&1; then
            confirm_sudo "sudo dnf install -y python3 python3-pip"
            sudo dnf install -y python3 python3-pip
        elif command -v yum >/dev/null 2>&1; then
            confirm_sudo "sudo yum install -y python3 python3-pip"
            sudo yum install -y python3 python3-pip
        elif command -v pacman >/dev/null 2>&1; then
            confirm_sudo "sudo pacman -Sy --noconfirm python python-pip"
            sudo pacman -Sy --noconfirm python python-pip
        elif command -v apk >/dev/null 2>&1; then
            confirm_sudo "sudo apk add --no-cache python3 py3-pip"
            sudo apk add --no-cache python3 py3-pip
        else
            echo "ERROR: Could not detect system package manager to install Python 3."
            exit 1
        fi
    fi
    PYTHON_BIN="$(command -v python3)" || die "python3 is still not on PATH after the install step."
    check_python_version "$PYTHON_BIN"
    echo "[1/5] Using Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

    echo "[2/5] Checking pip and virtual environment..."
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        echo "      Bootstrapping pip..."
        bootstrap_pip_safe "$PYTHON_BIN" || die "Could not bootstrap pip."
    fi

    if [ ! -d ".venv" ]; then
        if "$PYTHON_BIN" -m venv .venv >/dev/null 2>&1; then
            echo "      Created virtual environment in $SCRIPT_DIR/.venv"
        else
            rm -rf .venv
            warn "Could not create a .venv (python3-venv missing?); installing into the system Python instead."
        fi
    fi
    if [ -x ".venv/bin/python" ]; then
        if ".venv/bin/python" -m pip --version >/dev/null 2>&1; then
            PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
        else
            rm -rf .venv
        fi
    fi

    "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel --quiet \
        || warn "Could not upgrade pip/setuptools/wheel; continuing with the installed versions."
    echo "[2/5] pip is ready."

    if [ "$SAMPLE_ONLY" -eq 1 ]; then
        echo "[3/5] --sample-only: skipping live NFL data packages (pro-football-slm will use the built-in SAMPLE dataset)."
    else
        echo "[3/5] Installing live NFL data packages from requirements-live.txt (pandas, pyarrow, polars, nflreadpy)..."
        [ -f "$SCRIPT_DIR/requirements-live.txt" ] || die "requirements-live.txt not found next to install.sh."
        "$PYTHON_BIN" -m pip install --only-binary=:all: -r "$SCRIPT_DIR/requirements-live.txt" \
            || die "$(install_live_requirements_hint)"
        if [ "$WITH_LEGACY" -eq 1 ]; then
            "$PYTHON_BIN" -m pip install "nfl_data_py>=0.3.0,<0.4" || die "Could not install the requested legacy nfl_data_py."
        fi
    fi
    "$PYTHON_BIN" -m pip install -e . --no-build-isolation || "$PYTHON_BIN" -m pip install -e . \
        || die "Could not install pro-football-slm itself (pip install -e . failed)."
    echo "[3/5] Python packages & pro-football-slm installed."

    echo "[4/5] Checking optional R (nflreadr)..."
    if command -v Rscript >/dev/null 2>&1; then
        Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))" \
            || warn "Could not install the optional R package nflreadr (the R data bridge will be unavailable)."
    fi

    create_local_launcher
    echo "[5/5] Verifying pro-football-slm installation..."
    "$SCRIPT_DIR/pro-football-slm" list-stats || die "pro-football-slm failed its verification run."
    verify_live_data
    print_warnings

    echo ""
    echo "======================================================================"
    echo "  ✔ INSTALLATION COMPLETE!"
    echo "  Run in this folder:  ./pro-football-slm"
    echo "  Diagram a play:      ./pro-football-slm play --qb Mahomes --camera behind-offense"
    echo "                       ./pro-football-slm play --qb Goff --camera behind-defense"
    echo "======================================================================"
    prompt_add_to_path
    exit 0
fi

# ==============================================================================
# DEFAULT COMPACT MODE:
# 1. Prints the ASCII art banner
# 2. Below that: ONE progress bar line (exact width of banner, capped to terminal width so it never wraps)
# 3. Below that: ONE command line that overwrites itself in-place
# ==============================================================================
LOG_FILE="$(mktemp "${TMPDIR:-/tmp}/pro_football_slm_install.XXXXXX.log" 2>/dev/null || echo "${TMPDIR:-/tmp}/pro_football_slm_install.$$.log")"
: > "$LOG_FILE"

TERM_COLS="$(tput cols 2>/dev/null || echo 89)"
TARGET_WIDTH=89
if [ "$TERM_COLS" -lt 90 ] 2>/dev/null; then
    TARGET_WIDTH=$(( TERM_COLS - 1 ))
fi
if [ "$TARGET_WIDTH" -lt 30 ]; then
    TARGET_WIDTH=30
fi
# '[' (1) + BAR_INNER_WIDTH + '] ' (2) + '100%' (4) = TARGET_WIDTH
BAR_INNER_WIDTH=$(( TARGET_WIDTH - 7 ))
CMD_MAX_LEN=$(( TARGET_WIDTH - 4 ))

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
printf "\n"

update_ui 5 "Checking Python 3 installation..."
if ! command -v python3 >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
        run_step 5 15 "brew install python" brew install python || die "Python 3 installation failed."
    elif command -v apt-get >/dev/null 2>&1; then
        confirm_sudo "sudo apt-get install -y python3 python3-pip python3-venv"
        run_step 5 15 "sudo apt-get install -y python3 python3-pip python3-venv" bash -c "sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv" || die "Python 3 installation failed."
    elif command -v dnf >/dev/null 2>&1; then
        confirm_sudo "sudo dnf install -y python3 python3-pip"
        run_step 5 15 "sudo dnf install -y python3 python3-pip" sudo dnf install -y python3 python3-pip || die "Python 3 installation failed."
    elif command -v yum >/dev/null 2>&1; then
        confirm_sudo "sudo yum install -y python3 python3-pip"
        run_step 5 15 "sudo yum install -y python3 python3-pip" sudo yum install -y python3 python3-pip || die "Python 3 installation failed."
    elif command -v pacman >/dev/null 2>&1; then
        confirm_sudo "sudo pacman -Sy --noconfirm python python-pip"
        run_step 5 15 "sudo pacman -Sy --noconfirm python python-pip" sudo pacman -Sy --noconfirm python python-pip || die "Python 3 installation failed."
    elif command -v apk >/dev/null 2>&1; then
        confirm_sudo "sudo apk add --no-cache python3 py3-pip"
        run_step 5 15 "sudo apk add --no-cache python3 py3-pip" sudo apk add --no-cache python3 py3-pip || die "Python 3 installation failed."
    else
        update_ui 15 "ERROR: Could not detect package manager to install Python 3."
        printf "\n"
        exit 1
    fi
fi

PYTHON_BIN="$(command -v python3)" || die "python3 is still not on PATH after the install step."
check_python_version "$PYTHON_BIN"
update_ui 15 "command -v python3 -> $PYTHON_BIN"

if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    run_step 15 25 "$PYTHON_BIN -m ensurepip --upgrade" bootstrap_pip_safe "$PYTHON_BIN" || die "Could not bootstrap pip."
fi

if [ ! -d ".venv" ]; then
    run_step 25 32 "$PYTHON_BIN -m venv .venv" "$PYTHON_BIN" -m venv .venv || {
        rm -rf .venv
        warn "Could not create a .venv (python3-venv missing?); installing into the system Python instead."
    }
fi
if [ -x ".venv/bin/python" ]; then
    if ".venv/bin/python" -m pip --version >/dev/null 2>&1; then
        PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
    else
        rm -rf .venv
    fi
fi

run_step 32 45 "pip install --upgrade pip setuptools wheel" "$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel \
    || warn "Could not upgrade pip/setuptools/wheel; continuing with the installed versions."
if [ "$SAMPLE_ONLY" -eq 1 ]; then
    update_ui 84 "--sample-only: skipping live NFL data packages"
else
    [ -f "$SCRIPT_DIR/requirements-live.txt" ] || die "requirements-live.txt not found next to install.sh."
    run_step 45 84 "pip install --only-binary=:all: -r requirements-live.txt" "$PYTHON_BIN" -m pip install --only-binary=:all: -r "$SCRIPT_DIR/requirements-live.txt" \
        || die "$(install_live_requirements_hint)"
    if [ "$WITH_LEGACY" -eq 1 ]; then
        run_step 84 88 "pip install nfl_data_py (legacy, requested)" "$PYTHON_BIN" -m pip install "nfl_data_py>=0.3.0,<0.4" \
            || die "Could not install the requested legacy nfl_data_py."
    fi
fi
run_step 90 96 "pip install -e . --no-build-isolation" "$PYTHON_BIN" -m pip install -e . --no-build-isolation \
    || run_step 92 96 "pip install -e ." "$PYTHON_BIN" -m pip install -e . \
    || die "Could not install pro-football-slm itself (pip install -e . failed)."

if command -v Rscript >/dev/null 2>&1; then
    run_step 96 98 "Rscript -e install.packages('nflreadr')" Rscript -e "if (!requireNamespace('nflreadr', quietly=TRUE)) install.packages('nflreadr', repos=c('https://nflverse.r-universe.dev', 'https://cloud.r-project.org'))" \
        || warn "Could not install the optional R package nflreadr (the R data bridge will be unavailable)."
fi

create_local_launcher
if run_step 98 100 "./pro-football-slm --version" "$SCRIPT_DIR/pro-football-slm" --version; then
    verify_live_data
    rm -f "$LOG_FILE"
    update_ui 100 "Done! Run: ./pro-football-slm  (or ./install.sh -v for verbose)"
    printf "\n"
    print_warnings
    prompt_add_to_path
else
    update_ui 100 "ERROR: Verification failed (see $LOG_FILE)"
    printf "\n"
    exit 1
fi
