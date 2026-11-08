#!/usr/bin/env Rscript
# nflverse_bridge.R — R Data & Modeling Bridge for nfl-stat-cli
# Uses {nflverse}, {nflreadr}, and {nflfastR} to pull play-by-play data,
# EPA/WPA/CPOE/xYAC models, and screen-pass / play-direction flags.

args <- commandArgs(trailingOnly = TRUE)

seasons <- c(2024, 2025)
output_csv <- "nflverse_pbp.csv"

i <- 1
while (i <= length(args)) {
  if (args[i] == "--seasons" && i < length(args)) {
    seasons <- as.integer(unlist(strsplit(args[i + 1], ",")))
    i <- i + 2
  } else if (args[i] == "--output" && i < length(args)) {
    output_csv <- args[i + 1]
    i <- i + 2
  } else {
    i <- i + 1
  }
}

if (!requireNamespace("nflreadr", quietly = TRUE)) {
  stop("Package 'nflreadr' (part of nflverse) is required. Install in R via: install.packages('nflreadr', repos = c('https://nflverse.r-universe.dev', getOption('repos')))")
}

suppressPackageStartupMessages({
  library(nflreadr)
})

message(sprintf("[nflverse-bridge] Loading play-by-play for seasons: %s", paste(seasons, collapse = ", ")))
pbp <- nflreadr::load_pbp(seasons = seasons)
teams <- nflreadr::load_teams()

# Merge team conference (AFC / NFC) and division
if ("team_abbr" %in% names(teams) && "team_conf" %in% names(teams)) {
  conf_map <- setNames(teams$team_conf, teams$team_abbr)
  pbp$conf <- unname(conf_map[pbp$posteam])
}
if ("team_abbr" %in% names(teams) && "team_division" %in% names(teams)) {
  div_map <- setNames(teams$team_division, teams$team_abbr)
  pbp$division <- unname(div_map[pbp$posteam])
}

# Screen pass identification (via desc + air_yards)
pbp$is_screen <- ifelse(
  grepl("screen", tolower(ifelse(is.na(pbp$desc), "", pbp$desc))) |
    (pbp$pass_attempt == 1 & !is.na(pbp$air_yards) & pbp$air_yards <= 0 & pbp$complete_pass == 1),
  1L, 0L
)

# Play direction (left / middle / right)
pbp$play_direction <- ifelse(
  !is.na(pbp$pass_location), as.character(pbp$pass_location),
  ifelse(!is.na(pbp$run_location), as.character(pbp$run_location), "middle")
)

# Determine team win flag per game_id + posteam
pbp$team_win <- ifelse(
  (pbp$posteam == pbp$home_team & pbp$result > 0) |
    (pbp$posteam == pbp$away_team & pbp$result < 0),
  1L, 0L
)

pbp$qb_name <- ifelse(
  !is.na(pbp$passer_player_name) & pbp$passer_player_name != "",
  pbp$passer_player_name,
  ifelse(!is.na(pbp$qb_scramble) & pbp$qb_scramble == 1 & !is.na(pbp$rusher_player_name), pbp$rusher_player_name, "")
)

keep_cols <- intersect(
  c("play_id", "season", "week", "game_id", "posteam", "defteam", "home_team", "away_team", "result",
    "conf", "division", "qb_name", "passer_player_name", "receiver_player_name", "rusher_player_name",
    "play_type", "play_direction", "is_screen", "shotgun", "no_huddle", "qb_scramble",
    "air_yards", "yards_after_catch", "xyac_mean_yardage",
    "yards_gained", "epa", "wpa", "cpoe", "complete_pass", "pass_attempt",
    "rush_attempt", "down", "ydstogo", "yardline_100", "success", "series_success", "first_down",
    "touchdown", "pass_touchdown", "rush_touchdown", "interception", "fumble_lost", "sack", "team_win",
    "home_score", "away_score", "score_differential", "qtr", "desc"),
  names(pbp)
)

out_df <- pbp[!is.na(pbp$posteam) & ((!is.na(pbp$pass_attempt) & pbp$pass_attempt == 1) | (!is.na(pbp$rush_attempt) & pbp$rush_attempt == 1)), keep_cols]
write.csv(out_df, file = output_csv, row.names = FALSE, na = "")
message(sprintf("[nflverse-bridge] Exported %d plays to %s", nrow(out_df), output_csv))
