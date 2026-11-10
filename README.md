# nfl-stat-cli 🏈

A cross-platform (`*nix`, WSL, macOS, and Windows) command-line interface and interactive terminal analytics suite with **colorized ASCII art** (multi-angle play diagrams in **Behind-the-Offense**, **Behind-the-Defense**, and **Sideline** views, plus clean Unicode tables) and a **general-purpose composable Custom Stat Engine** powered by **[nflverse](https://nflverse.nflverse.com/) (R)**, **[nfl_data_py](https://github.com/nflverse/nfl_data_py) / [sportsdataverse-py](https://py.sportsdataverse.org/) (Python)**, and an optional **Local Small Language Model (SLM via Ollama)**.

## Core Highlights

- **One-Step Automated Installer (`install.sh` / `install.bat` / `install.ps1`)**:
  - **Compact Progress UI (Default)**: Displays the colorized `NFL-STAT-CLI` ASCII art banner, a full-width progress bar matched to the banner width, and a single overwriting status line showing the current installer command.
  - **Verbose Mode (`-v` / `--verbose`)**: Pass `-v` (`./install.sh -v` or `.\install.ps1 -v`) to view full step-by-step `pip` and environment logs.
  - **Zero-Prerequisite Setup**: Automatically detects or installs **Python 3** (`>=3.10`), bootstraps **`pip`**, creates/updates `.venv`, installs required Python packages (`pandas`, `pyarrow`, `polars`, `nfl_data_py`), and installs R's `nflreadr` if `Rscript` is present.
  - **`nfl-stat` Command & Post-Install `PATH` Prompt**: Generates the `nfl-stat` launcher in the project folder (`./nfl-stat` on `*nix`/WSL and `.\nfl-stat` on Windows) and, once installation verification succeeds, asks if you want to add `nfl-stat` to your global `PATH` so you can run `nfl-stat` from any directory.
- **General-Purpose Multi-Scope Composable Custom Stat Engine**:
  - Build custom stats across three evaluation scopes:
    1. **`season` scope**: Evaluate formulas across a player's, team's, or play concept's aggregated season metrics.
    2. **`game` scope**: Evaluate formulas or conditions **game-by-game** and aggregate (`sum`, `avg`, `count_true`, `rate`, `min`, `max`) across games (enabling stats like MLB-style Pitcher QB Meaningful Wins `MW`, Meaningful Losses `ML`, No-Decisions `ND`, Quality Starts, etc.).
    3. **`play` scope**: Evaluate formulas on each individual play and aggregate across filtered plays.
  - Filter by any play-level condition (`is_screen == 1`, `down == 3`, `qtr == 4`, `play_action == 1`, `conf == 'AFC'`, `red_zone == 1`, `air_yards >= 15`, etc.) and group by any dimension (`qb`, `team`, `defteam`, `receiver`, `rusher`, `player`, `play_concept`, `play_type`, `conference`, `division`, `down`, `qtr`, `game`).
  - Chain custom stats inside new custom stats with automatic AST dependency resolution.
- **Context-Aware Output (No Unnecessary ASCII Fields on Yearly Averages)**:
  - Queries for **season averages, leaderboards, or stat rankings across the year** output clean **tables and stat explanations only**—never cluttering the terminal with an ASCII football field.
  - Queries for a **specific play** (`nfl-stat play ...` or asking to see/diagram a specific play) render the **colorized ASCII football field and play trajectory**.
- **Multi-Angle ASCII Play Visualizer (`behind-offense`, `behind-defense`, `sideline`)**:
  - **`--camera behind-offense`**: All-22 view behind the QB/Offense looking **upfield (`▲`)** toward the Defense (`DE`, `DT`, `LB`, `CB`, `FS`, `SS`) and Opponent End Zone.
  - **`--camera behind-defense`**: All-22 view behind the Defensive Secondary looking at the Offense driving **downward (`▼`)** toward the viewer, with laterally mirrored perspective (`DEF LEFT / OFF RIGHT` on the left, `DEF RIGHT / OFF LEFT` on the right).
  - **`--camera sideline`**: Classic 100-yard left-to-right broadcast view.
- **Natural-Language-First Interactive Interface + `/command` System**:
  - Launching `./nfl-stat` (or `nfl-stat`) drops directly into a natural-language prompt (`nfl-stat > `) with full multi-line GNU `readline` line-wrap and backspace support.
  - Type any NFL stat question, play diagram request, or custom stat definition in plain English, or use `/commands` (`/help` lists all commands; `/quit`, `quit`, `/close`, or `close` exits).
  - Automatically connects to a local Ollama SLM (`qwen2.5:1.5b`, `qwen2.5-coder:1.5b`, `llama3.2:1b`, `phi3:mini`, etc.) if running, or falls back to the zero-latency built-in AST/rule parser.

## One-Step Installation

### Linux / WSL / macOS (`*nix`)
```bash
# Compact installer (ASCII art banner + full-width progress bar + 1-line command status)
./install.sh

# Or run with full verbose output:
./install.sh -v
```

### Windows
```bat
REM Compact installer (or double-click install.bat in Explorer)
install.bat

REM Or run with full verbose output:
install.bat -v
```
*(In PowerShell: `.\install.ps1` or `.\install.ps1 -v` — add `-WithSLM` to also install/pull a lightweight local Ollama SLM `qwen2.5:1.5b`)*

Once the installer finishes verifying `nfl-stat`, it will prompt:
```text
? Add nfl-stat to your PATH so you can run it from anywhere? [y/N]:
```
- Choose **`y`** to run `nfl-stat` from any directory.
- Choose **`N`** to run `./nfl-stat` (`*nix`/WSL) or `.\nfl-stat` (Windows) directly inside the installed folder.

### Live data vs. sample data

The installers install the live NFL data packages listed in [`requirements-live.txt`](requirements-live.txt) (`pandas`, `pyarrow`, `polars`, `nflreadpy`; `nflreadpy` needs Python 3.10+). If that step fails, the installer **stops with an error** instead of leaving you on the small built-in sample dataset. To use the sample dataset on purpose, pass `--sample-only` (`./install.sh --sample-only`) or `-SkipLivePackages` (`.\install.ps1 -SkipLivePackages`). The deprecated `nfl_data_py` loader is no longer installed by default; add `--with-legacy-nfl-data-py` / `-WithLegacyNflDataPy` if you need the opt-in fallback. Steps that need administrator rights (`sudo` to install Python on Linux) ask first; pass `--yes` to allow them when running non-interactively.

## Quickstart Examples

```bash
# 1. Launch the interactive Natural Language + /command interface
./nfl-stat
# (Or simply `nfl-stat` if added to your PATH)
# Inside `nfl-stat > `, ask anything in plain English or run `/help` to view all slash commands:
#   nfl-stat > What is the average yards after catch on screen passes in 2025?
#   nfl-stat > Show Lamar Jackson longest play from behind the defense
#   nfl-stat > /help
#   nfl-stat > /stat qb_impact_score
#   nfl-stat > /create
#   nfl-stat > /play mahomes behind-offense
#   nfl-stat > close   (or /quit, quit, /close)

# 2. Evaluate any stat leaderboard across the season (outputs Table only — no ASCII field)
./nfl-stat stat screen_yards_after_catch --season 2025
./nfl-stat stat yards_per_play --conf AFC --group-by play_concept
./nfl-stat qb-wins --season 2025

# 3. Diagram a specific play in Behind-the-Offense, Behind-the-Defense, or Sideline view
./nfl-stat play --qb Mahomes --camera behind-offense
./nfl-stat play --qb Goff --concept screen --camera behind-defense
./nfl-stat play --conf AFC --sort-by yards_gained --camera sideline

# 4. Create a new game-scoped or filtered custom stat (like the example use cases)
./nfl-stat create-stat \
  --name "qb_quality_start" \
  --title "QB Quality Start (QS)" \
  --group-by qb \
  --scope game \
  --agg sum \
  --formula "ifelse((qb_impact_score >= 60.0) and (turnover_rate == 0), 1, 0)" \
  --description "Counts games where a QB posts a 60+ Game Impact Score with zero turnovers." \
  --explained "Evaluated per game (scope=game, agg=sum): awards 1 QS when game qb_impact_score >= 60 and turnover_rate == 0." \
  --unit "QS"

# 5. Ask natural language questions (Table for yearly averages; ASCII Field for specific plays)
./nfl-stat ask "What is the average yards after catch on screen passes in 2025?"
./nfl-stat ask "Show Lamar Jackson longest play from behind the defense"
```

## Building & Publishing to PyPI

This project is configured with PEP 621 / `setuptools` metadata in `pyproject.toml`, `MANIFEST.in`, and `LICENSE` so it can be built and published directly to PyPI (or TestPyPI):

```bash
# Install build and twine
python -m pip install --upgrade build twine

# Build source distribution (.tar.gz) and wheel (.whl) into dist/
python -m build

# Validate package metadata and README rendering
python -m twine check dist/*

# Upload to PyPI (or TestPyPI with --repository testpypi)
python -m twine upload dist/*
```

Once published, any user can install it directly with:

```bash
pip install nfl-stat-cli
# Or with live data dependencies included:
pip install "nfl-stat-cli[live]"
```
*(Installing via `pip` registers both the `nfl-stat` and `nfl-stat-cli` commands).*

## License

Released under the [MIT License](LICENSE). Play-by-play data provided via [nflverse/nflverse-data](https://github.com/nflverse/nflverse-data) (CC-BY 4.0) and [sportsdataverse-py](https://github.com/sportsdataverse/sportsdataverse-py).
