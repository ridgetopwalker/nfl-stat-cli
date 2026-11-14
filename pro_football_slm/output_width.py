"""Shared display-column budget for terminal renderers (no data loading)."""
from contextvars import ContextVar
from functools import wraps
import re
import unicodedata

_COLUMNS = ContextVar("output_columns", default=123)
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

def columns():
    return _COLUMNS.get()

def width(text):
    return sum(0 if unicodedata.combining(c) or c in "\u200b\u200c\u200d\ufe0e\ufe0f" else
               2 if unicodedata.east_asian_width(c) in "WF" or text[i+1:i+2] == "\ufe0f" else 1
               for i, c in enumerate(text))

def chunks(text, cols):
    part = ""
    for c in text:
        if width(part + c) > cols:
            yield part
            part = ""
        part += c
    if part:
        yield part

def fit(text, cols=123):
    """Wrap prose; show oversized drawings in successive horizontal panels.

    Panels preserve every drawing character without wrapping individual drawing rows.
    Normal-width drawings pass through unchanged. ANSI is removed only when resizing.
    """
    cols = max(20, int(cols))
    if all(width(_ANSI.sub("", line)) <= cols for line in text.splitlines()):
        return text
    lines = _ANSI.sub("", text).split("\n")
    out = []
    drawing = []
    def flush():
        if not drawing:
            return
        panels = [list(chunks(line, cols)) or [""] for line in drawing]
        for i in range(max(map(len, panels))):
            if i:
                out.append("")
            out.extend(p[i] if i < len(p) else "" for p in panels)
        drawing.clear()
    for line in lines:
        if any("\u2500" <= c <= "\u259f" or c == "|" for c in line):
            drawing.append(line)
            continue
        flush()
        if width(line) <= cols:
            out.append(line)
            continue
        current = ""
        for word in line.split():
            if current and width(current + " " + word) > cols:
                out.append(current)
                current = ""
            parts = list(chunks(word, cols))
            if len(parts) > 1:
                out.extend(parts[:-1])
            word = parts[-1] if parts else ""
            current = current + " " + word if current else word
        if current:
            out.append(current)
    flush()
    return "\n".join(out)

def bounded(fn):
    """Render with keyword-only cols=123; nested renderers inherit that budget."""
    @wraps(fn)
    def render(*args, cols=None, **kwargs):
        budget = max(20, int(cols if cols is not None else columns()))
        token = _COLUMNS.set(budget)
        try:
            return fit(fn(*args, **kwargs), budget)
        finally:
            _COLUMNS.reset(token)
    return render
