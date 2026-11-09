# Pro Football SLM 🏈

**Pro Football SLM: the American pro football stat engine.**

Not affiliated with or endorsed by the NFL.

A cross-platform (`*nix`, WSL, macOS, and Windows) command-line interface and interactive terminal analytics suite with **colorized ASCII art** (multi-angle play diagrams in **Behind-the-Offense**, **Behind-the-Defense**, and **Sideline** views, plus clean Unicode tables) and a **general-purpose composable Custom Stat Engine** powered by **[nflverse](https://nflverse.nflverse.com/) (R)**, **[nfl_data_py](https://github.com/nflverse/nfl_data_py) / [sportsdataverse-py](https://py.sportsdataverse.org/) (Python)**, and an optional **Local Small Language Model (SLM via Ollama)**.

## Core Highlights

- **One-Step Automated Installer (`install.sh` / `install.bat` / `install.ps1`)**:
  - **Compact Progress UI (Default)**: Displays the colorized `NFL-STAT-CLI` ASCII art banner, a full-width progress bar matched to the banner width, and a single overwriting status line showing the current installer command.
  - **Verbose Mode (`-v` / `--verbose`)**: Pass `-v` (`./install.sh -v` or `.\install.ps1 -v`) to view full step-by-step `pip` and environment logs.
  - **Zero-Prerequisite Setup**: Automatically detects or installs **Python 3** (`>=3.8`), bootstraps **`pip`**, creates/updates `.venv`, installs required Python packages (`pandas`, `pyarrow`, `polars`, `nfl_data_py`), and installs R's `nflreadr` if `Rscript` is present.
  - **`pro-football-slm` Command & Post-Install `PATH` Prompt**: Generates the `pro-football-slm` launcher in the project folder (`./pro-football-slm` on `*nix`/WSL and `.\pro-football-slm` on Windows) and, once installation verification succeeds, asks if you want to add `pro-football-slm` to your global `PATH` so you can run `pro-football-slm` from any directory.
- **General-Purpose Multi-Scope Composable Custom Stat Engine**:
  - Build custom stats across three evaluation scopes:
    1. **`season` scope**: Evaluate formulas across a player's, team's, or play concept's aggregated season metrics.
    2. **`game` scope**: Evaluate formulas or conditions **game-by-game** and aggregate (`sum`, `avg`, `count_true`, `rate`, `min`, `max`) across games (enabling stats like MLB-style Pitcher QB Meaningful Wins `MW`, Meaningful Losses `ML`, No-Decisions `ND`, Quality Starts, etc.).
    3. **`play` scope**: Evaluate formulas on each individual play and aggregate across filtered plays.
  - Filter by any play-level condition (`is_screen == 1`, `down == 3`, `qtr == 4`, `play_action == 1`, `conf == 'AFC'`, `red_zone == 1`, `air_yards >= 15`, etc.) and group by any dimension (`qb`, `team`, `defteam`, `receiver`, `rusher`, `player`, `play_concept`, `play_type`, `conference`, `division`, `down`, `qtr`, `game`).
  - Chain custom stats inside new custom stats with automatic AST dependency resolution.
- **Context-Aware Output (No Unnecessary ASCII Fields on Yearly Averages)**:
  - Queries for **season averages, leaderboards, or stat rankings across the year** output clean **tables and stat explanations only**—never cluttering the terminal with an ASCII football field.
  - Queries for a **specific play** (`pro-football-slm play ...` or asking to see/diagram a specific play) render the **colorized ASCII football field and play trajectory**.
- **Multi-Angle ASCII Play Visualizer (`behind-offense`, `behind-defense`, `sideline`)**:
  - **`--camera behind-offense`**: All-22 view behind the QB/Offense looking **upfield (`▲`)** toward the Defense (`DE`, `DT`, `LB`, `CB`, `FS`, `SS`) and Opponent End Zone.
  - **`--camera behind-defense`**: All-22 view behind the Defensive Secondary looking at the Offense driving **downward (`▼`)** toward the viewer, with laterally mirrored perspective (`DEF LEFT / OFF RIGHT` on the left, `DEF RIGHT / OFF LEFT` on the right).
  - **`--camera sideline`**: Classic 100-yard left-to-right broadcast view.
- **Natural-Language-First Interactive Interface + `/command` System**:
  - Launching `./pro-football-slm` (or `pro-football-slm`) drops directly into a natural-language prompt (`pro-football-slm > `) with full multi-line GNU `readline` line-wrap and backspace support.
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

Once the installer finishes verifying `pro-football-slm`, it will prompt:
```text
? Add pro-football-slm to your PATH so you can run it from anywhere? [y/N]:
```
- Choose **`y`** to run `pro-football-slm` from any directory.
- Choose **`N`** to run `./pro-football-slm` (`*nix`/WSL) or `.\pro-football-slm` (Windows) directly inside the installed folder.

## Quickstart Examples

```bash
# 1. Launch the interactive Natural Language + /command interface
./pro-football-slm
# (Or simply `pro-football-slm` if added to your PATH)
# Inside `pro-football-slm > `, ask anything in plain English or run `/help` to view all slash commands:
#   pro-football-slm > What is the average yards after catch on screen passes in 2025?
#   pro-football-slm > Show Lamar Jackson longest play from behind the defense
#   pro-football-slm > /help
#   pro-football-slm > /stat qb_impact_score
#   pro-football-slm > /create
#   pro-football-slm > /play mahomes behind-offense
#   pro-football-slm > close   (or /quit, quit, /close)

# 2. Evaluate any stat leaderboard across the season (outputs Table only — no ASCII field)
./pro-football-slm stat screen_yards_after_catch --season 2025
./pro-football-slm stat yards_per_play --conf AFC --group-by play_concept
./pro-football-slm qb-wins --season 2025

# 3. Diagram a specific play in Behind-the-Offense, Behind-the-Defense, or Sideline view
./pro-football-slm play --qb Mahomes --camera behind-offense
./pro-football-slm play --qb Goff --concept screen --camera behind-defense
./pro-football-slm play --conf AFC --sort-by yards_gained --camera sideline

# 4. Create a new game-scoped or filtered custom stat (like the example use cases)
./pro-football-slm create-stat \
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
./pro-football-slm ask "What is the average yards after catch on screen passes in 2025?"
./pro-football-slm ask "Show Lamar Jackson longest play from behind the defense"
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
pip install pro-football-slm
# Or with live data dependencies included:
pip install "pro-football-slm[live]"
```
*(Installing via `pip` registers both the `pro-football-slm` and `pro-football-slm` commands).*

## License

Released under the [MIT License](LICENSE). Play-by-play data provided via [nflverse/nflverse-data](https://github.com/nflverse/nflverse-data) (CC-BY 4.0) and [sportsdataverse-py](https://github.com/sportsdataverse/sportsdataverse-py).

## Command rename

The CLI entry points are `pro-football-slm` and the short alias `pfslm`. The old `nfl-stat` command still works for one release and prints a rename notice to stderr.
