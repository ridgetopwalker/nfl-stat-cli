"""Manual benchmark for #15 (not collected by pytest): leaderboard time with requested-stat-only vs full evaluation.

    python tests/bench_leaderboard.py [groups] [plays_per_group]
"""
import copy
import sys
import time
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import nfl_stat_cli as cli  # noqa: E402


def synthetic_plays(groups: int, per_group: int):
    base = [p for p in cli.SAMPLE_PBP_PLAYS if p.get("qb_name")]
    plays = []
    for g in range(groups):
        for i in range(per_group):
            p = copy.copy(base[i % len(base)])
            p["qb_name"] = f"QB{g:03d}"
            p["game_id"] = f"G{g:03d}_{i // 40}"
            plays.append(p)
    return plays


def main() -> None:
    groups = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    per_group = int(sys.argv[2]) if len(sys.argv) > 2 else 420
    plays = synthetic_plays(groups, per_group)
    eng = cli.StatEngine(storage_dir=Path(tempfile.mkdtemp()))
    for n, s in cli.EXAMPLE_CUSTOM_STATS.items():
        eng.stats[n] = s
    t0 = time.perf_counter()
    eng.evaluate_stat_leaderboard("yards_per_play", plays, group_override="qb")
    fast = time.perf_counter() - t0
    orig = cli.StatEngine.evaluate_all_metrics_for_group
    cli.StatEngine.evaluate_all_metrics_for_group = lambda self, p, only=None, _closure=None: orig(self, p, only=None)
    t0 = time.perf_counter()
    eng.evaluate_stat_leaderboard("yards_per_play", plays, group_override="qb")
    full = time.perf_counter() - t0
    cli.StatEngine.evaluate_all_metrics_for_group = orig
    print(f"(speedup depends on how many stats are registered) {groups} groups, {len(plays)} plays: requested-stat-only {fast * 1000:.0f} ms, all-stats {full * 1000:.0f} ms ({full / max(fast, 1e-9):.1f}x)")


if __name__ == "__main__":
    main()
