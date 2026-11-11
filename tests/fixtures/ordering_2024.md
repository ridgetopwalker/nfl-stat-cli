# Known-game ordering fixture

ordering_2024.csv is a seven-column projection of all events for three complete
regular-season games from the staged nflverse play_by_play_2024.parquet. No
betting, player, roster, or participation fields are included.

Numeric play_id vs numeric order_sequence disagree at 20/178 positions for
BAL-KC, 26/196 for GB-PHI, and 22/153 for NE-CIN. Most changes place no_play
records before a same-clock event. NE-CIN also moves play 3150 to sequence 2867
and reorders late fourth-quarter events: play_id ordering has two clock
increases, while order_sequence has none. All three games have nonincreasing
remaining time under order_sequence. Thus prefer numeric order_sequence with
numeric play_id fallback, stable input-order ties, and unidentified events last.
Clock is not a sort key. These checks establish the local cache evidence; they
do not claim independent verification against official gamebooks.
