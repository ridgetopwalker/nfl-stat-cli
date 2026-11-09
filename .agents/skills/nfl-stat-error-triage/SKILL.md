---
name: nfl-stat-error-triage
description: Connect to the user's WSL instance of nfl-stat, watch for /error reports filed from either Windows or WSL, fix the natural-language parsing bug, push, and signal the waiting nfl-stat session. Use when the user mentions /error reports, "fix error", nfl-stat, or the WSL nfl-stat instance.
---

# nfl-stat error triage

## Environment (remember this)
- Windows repo: `<local-path>\sources\nfl-stat-cli` (git remote `ridgetopwalker/nfl-stat-cli`, branches `master` and `main`).
- The user usually runs nfl-stat in **WSL Ubuntu**: repo `<local-path>/nfl-stat-cli`, python `<local-path>/nfl-stat-cli/.venv/bin/python`, launched as `.venv/bin/python nfl_stat_cli.py`.
- Reach WSL only via `wsl.exe` (e.g. `wsl bash -c "..."`, `wsl git -C <local-path>/nfl-stat-cli ...`). Pipes like `| grep` must be inside `bash -c`.
- Each side has its own `.error_ipc/{pending,resolved,history}`. The report JSON holds `id`, `query`, `user_explanation`, `parsed` (the AST output). The WSL session lives in a separate process: it only sees resolutions written into **its own** `.error_ipc/resolved/`.

## Workflow
1. Start (or restart) the watcher as a **background task**: `py -3 .agents/skills/nfl-stat-error-triage/watch_errors.py`. It exits when a pending report appears (Windows or WSL), printing `NEW_ERROR_REPORT source=<windows|wsl> id=<id>` plus the JSON. You are notified automatically when it exits.
2. Reproduce: `NaturalLanguageStatAssistant.interpret_query(query, StatEngine(), slm_model="off")` then `handle_nl_query_result(parsed, engine, SAMPLE_PBP_PLAYS)`.
3. Fix in `nfl_stat_cli/__init__.py`; add a regression test in `tests/test_cli.py`.
4. Verify: 0 CRLF in modified files, `py -3 -m pytest` fully green.
5. Rebuild `nfl-stat-cli.zip` (file list as in earlier turns), commit, `git push origin master` and `git push origin master:main`.
6. Signal: `py -3 .agents/skills/nfl-stat-error-triage/resolve.py <source> <id> <commit> "<summary>"` (pulls master into WSL when source is wsl, then writes the resolution there). The waiting nfl-stat session hot-reloads and re-runs the query.
7. Restart the watcher (step 1) so the loop continues.

## Notes
- If the report is vague, still make a best-effort fix from `user_explanation` + `parsed`; mention assumptions in the resolution summary.
- Only act on reports in the two known `.error_ipc/pending` dirs; never touch other processes.
