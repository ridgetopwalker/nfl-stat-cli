# nfl-stat-cli 🏈

A cross-platform (`*nix` and Windows) command-line interface and interactive terminal analytics suite with **colorized ASCII art** (multi-angle play diagrams in **Behind-the-Offense**, **Behind-the-Defense**, and **Sideline** views, plus clean Unicode tables) and a **general-purpose composable Custom Stat Engine** powered by **[nflverse](https://nflverse.nflverse.com/) (R)**, **[sportsdataverse-py](https://py.sportsdataverse.org/) (Python)**, and an optional **Local Small Language Model (SLM via Ollama)**.

## Core Highlights

- **One-Step Automated Installer (`install.bat` / `install.ps1` / `install.sh`)**:
  - Run once and let it work: automatically detects or installs **Python 3**, bootstraps **`pip`**, installs all required Python packages (`pandas`, `polars`, `pyarrow`, `nflreadpy`, `sportsdataverse`), installs R's `nflreadr` if `Rscript` is present, and creates the `nfl-stat-cli` launcher.
- **General-Purpose Multi-Scope Composable Custom Stat Engine**:
  - Build custom stats across three evaluation scopes:
    1. **`season` scope**: Evaluate formulas across a player's, team's, or play concept's aggregated season metrics.
    2. **`game` scope**: Evaluate formulas or conditions **game-by-game** and aggregate (`sum`, `avg`, `count_true`, `rate`, `min`, `max`) across games (enabling stats like MLB-style Pitcher QB Meaningful Wins `MW`, Meaningful Losses `ML`, No-Decisions `ND`, Quality Starts, etc.).
    3. **`play` scope**: Evaluate formulas on each individual play and aggregate across filtered plays.
  - Filter by any play-level condition (`is_screen == 1`, `down == 3`, `qtr == 4`, `play_action == 1`, `conf == 'AFC'`, `red_zone == 1`, `air_yards >= 15`, etc.) and group by any dimension (`qb`, `team`, `defteam`, `receiver`, `rusher`, `player`, `play_concept`, `play_type`, `conference`, `division`, `down`, `qtr`, `game`).
  - Chain custom stats inside new custom stats with automatic AST dependency resolution.
- **Context-Aware Output (No Unnecessary ASCII Fields on Yearly Averages)**:
  - Queries for **season averages, leaderboards, or stat rankings across the year** output clean **tables and stat explanations only**—never cluttering the terminal with an ASCII football field.
  - Queries for a **specific play** (`nfl-stat-cli play ...` or asking to see/diagram a specific play) render the **colorized ASCII football field and play trajectory**.
- **Multi-Angle ASCII Play Visualizer (`behind-offense`, `behind-defense`, `sideline`)**:
  - **`--camera behind-offense`**: All-22 view behind the QB/Offense looking **upfield (`▲`)** toward the Defense (`DE`, `DT`, `LB`, `CB`, `FS`, `SS`) and Opponent End Zone.
  - **`--camera behind-defense`**: All-22 view behind the Defensive Secondary looking at the Offense driving **downward (`▼`)** toward the viewer, with laterally mirrored perspective (`DEF LEFT / OFF RIGHT` on the left, `DEF RIGHT / OFF LEFT` on the right).
  - **`--camera sideline`**: Classic 100-yard left-to-right broadcast view.
- **Hybrid Local Small Language Model (SLM) + Deterministic NL Parser**:
  - Automatically connects to a local Ollama SLM (`qwen2.5:1.5b`, `qwen2.5-coder:1.5b`, `llama3.2:1b`, `phi3:mini`, etc.) if running, or falls back to the zero-latency built-in AST/rule parser.

## One-Step Installation

### Windows (Run Once)
```bat
install.bat
```
*(Or in PowerShell: `.\install.ps1` — add `-WithSLM` to also install/pull a lightweight local Ollama SLM `qwen2.5:1.5b`)*

### Linux / macOS (`*nix`) (Run Once)
```bash
chmod +x install.sh && ./install.sh
```

## Quickstart Examples

```bash
# 1. Launch the interactive colorized TUI
python nfl_stat_cli.py

# 2. Evaluate any stat leaderboard across the season (outputs Table only — no ASCII field)
python nfl_stat_cli.py stat screen_yards_after_catch --season 2025
python nfl_stat_cli.py stat yards_per_play --conf AFC --group-by play_concept
python nfl_stat_cli.py qb-wins --season 2025

# 3. Diagram a specific play in Behind-the-Offense, Behind-the-Defense, or Sideline view
python nfl_stat_cli.py play --qb Mahomes --camera behind-offense
python nfl_stat_cli.py play --qb Goff --concept screen --camera behind-defense
python nfl_stat_cli.py play --conf AFC --sort-by yards_gained --camera sideline

# 4. Create a new game-scoped or filtered custom stat (like the example use cases)
python nfl_stat_cli.py create-stat \
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
python nfl_stat_cli.py ask "What is the average yards after catch on screen passes in 2025?"
python nfl_stat_cli.py ask "Show Lamar Jackson longest play from behind the defense"
```
