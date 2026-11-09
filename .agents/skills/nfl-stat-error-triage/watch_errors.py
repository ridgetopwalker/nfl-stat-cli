#!/usr/bin/env python3
"""Block until a new nfl-stat /error report appears (Windows or WSL), print it, then exit.

Run as a background task; the agent is notified when it exits.
Usage: py -3 watch_errors.py [--interval 5]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

WIN_PENDING = Path(r"C:\Users\mccla\sources\nfl-stat-cli\.error_ipc\pending")
WSL_PENDING = "/home/sean/nfl-stat-cli/.error_ipc/pending"


def win_reports():
    out = {}
    if WIN_PENDING.exists():
        for p in WIN_PENDING.glob("err_*.json"):
            try:
                out[p.stem] = ("windows", json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def wsl_reports():
    out = {}
    try:
        r = subprocess.run(
            ["wsl.exe", "bash", "-c",
             f"for f in {WSL_PENDING}/err_*.json; do [ -f \"$f\" ] && cat \"$f\" && echo '@@END@@'; done"],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        for chunk in r.stdout.split("@@END@@"):
            chunk = chunk.strip()
            if chunk.startswith("{"):
                try:
                    d = json.loads(chunk)
                    out[d["id"]] = ("wsl", d)
                except Exception:
                    pass
    except Exception:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()
    while True:
        found = {**win_reports(), **wsl_reports()}
        if found:
            for rid, (src, data) in found.items():
                print(f"NEW_ERROR_REPORT source={src} id={rid}")
                print(json.dumps(data, indent=2))
            sys.stdout.flush()
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
