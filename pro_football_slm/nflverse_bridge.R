#!/usr/bin/env Rscript
# nflverse_bridge.R — R Data & Modeling Bridge for pro-football-slm
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
    "drive", "fixed_drive", "old_game_id", "order_sequence", "game_seconds_remaining", "time",
    "passer_player_id", "rusher_player_id", "receiver_player_id", "player_id", "penalty_player_id",
    "kicker_player_id", "punter_player_id", "kickoff_returner_player_id", "punt_returner_player_id", "blocked_player_id",
    "kicker_player_name", "punter_player_name", "kickoff_returner_player_name", "punt_returner_player_name", "blocked_player_name",
    "sack_player_id", "sack_player_1_id", "sack_player_2_id", "interception_player_id",
    "solo_tackle_1_player_id", "solo_tackle_2_player_id", "qb_hit_1_player_id", "qb_hit_2_player_id",
    "pass_defense_1_player_id", "pass_defense_2_player_id",
    "assist_tackle_1_player_id", "assist_tackle_2_player_id", "assist_tackle_3_player_id", "assist_tackle_4_player_id",
    "tackle_with_assist_1_player_id", "tackle_with_assist_2_player_id",
    "forced_fumble_player_1_player_id", "forced_fumble_player_2_player_id",
    "fumbled_1_player_id", "fumbled_2_player_id", "fumble_recovery_1_player_id", "fumble_recovery_2_player_id",
    "lateral_receiver_player_id", "lateral_rusher_player_id", "lateral_returner_player_id", "lateral_recovery_player_id",
    "kick_distance", "return_yards", "field_goal_result", "extra_point_result", "field_goal_attempt", "extra_point_attempt",
    "kickoff_attempt", "punt_attempt", "punt_blocked", "punt_inside_twenty", "punt_fair_catch",
    "punt_in_endzone", "punt_out_of_bounds", "punt_downed", "kickoff_in_endzone", "kickoff_inside_twenty",
    "kickoff_fair_catch", "kickoff_out_of_bounds", "kickoff_downed", "touchback",
    "lateral_return", "lateral_reception", "lateral_rush", "lateral_recovery",
    "conf", "division", "qb_name", "passer_player_name", "receiver_player_name", "rusher_player_name",
    "play_type", "play_direction", "is_screen", "shotgun", "no_huddle", "qb_scramble",
    "air_yards", "yards_after_catch", "xyac_mean_yardage",
    "yards_gained", "epa", "wpa", "cpoe", "complete_pass", "pass_attempt",
    "rush_attempt", "down", "ydstogo", "yardline_100", "success", "series_success", "first_down",
    "touchdown", "pass_touchdown", "rush_touchdown", "return_touchdown", "td_team",
    "interception", "fumble_lost", "sack", "team_win",
    "home_score", "away_score", "score_differential", "qtr", "desc",
    "penalty", "penalty_type", "penalty_yards", "penalty_team", "penalty_player_name",
    "timeout", "timeout_team", "posteam_timeouts_remaining", "defteam_timeouts_remaining"),
  names(pbp)
)

# Export every event; the Python stats loader applies the shared
# play-inclusion predicate (_pbp_row_is_playable) so all backends keep the same rows.
out_df <- as.data.frame(pbp)[, keep_cols, drop = FALSE]
write.csv(out_df, file = output_csv, row.names = FALSE, na = "")
message(sprintf("[nflverse-bridge] Exported %d plays to %s", nrow(out_df), output_csv))
