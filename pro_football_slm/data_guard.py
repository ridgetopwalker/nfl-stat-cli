"""Repository hygiene for data artifacts. Never print row contents on failure."""
from pathlib import Path
import re

MAX_DATA_BYTES = 1024 * 1024
DATA_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv", ".parquet", ".arrow", ".feather",
                 ".gz", ".zip", ".bz2", ".xz", ".pkl", ".pickle"}
PARTICIPATION_COLUMN = re.compile(
    rb"(?i)(?<![a-z0-9_])(?:offense|defense)_(?:players|names|positions|jersey_numbers|formation|personnel)(?![a-z0-9_])"
)


def check_data_artifacts(root, paths):
    """Check git's tracked-file inventory, including newly staged files.

    Participation fixtures belong in test-generated temporary files. Compressed and
    binary data are rejected because a plain byte scan cannot validate their schema.
    """
    root = Path(root).resolve()
    failures = []
    for name in paths:
        path = root / name
        if path.suffix.lower() not in DATA_SUFFIXES:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            failures.append(f"{name}: data path escapes repository")
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_DATA_BYTES:
            failures.append(f"{name}: oversized data artifact")
            continue
        if path.suffix.lower() not in {".json", ".jsonl", ".csv", ".tsv"}:
            failures.append(f"{name}: binary or compressed data artifact requires removal")
            continue
        if PARTICIPATION_COLUMN.search(path.read_bytes()):
            failures.append(f"{name}: participation columns must not be committed")
    return failures
