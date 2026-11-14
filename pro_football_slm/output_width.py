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

def display_sequences(text):
    """Keep bases with selectors, combining marks and joined continuations."""
    part = ""
    for c in text:
        if part and not (unicodedata.combining(c) or
                         c in "\u200b\u200c\u200d\ufe0e\ufe0f" or
                         0x1F3FB <= ord(c) <= 0x1F3FF or part.endswith("\u200d")):
            yield part
            part = ""
        part += c
    if part:
        yield part


def chunks(text, cols):
    part = ""
    for sequence in display_sequences(text):
        if part and width(part + sequence) > cols:
            yield part
            part = ""
        part += sequence
    if part:
        yield part


def fit(text, cols=123):
    """Wrap prose only; renderers must construct drawings within their budget."""
    cols = max(1, int(cols))
    if all(width(_ANSI.sub("", line)) <= cols for line in text.splitlines()):
        return text
    lines = _ANSI.sub("", text).split("\n")
    out = []
    for line in lines:
        # Structural rows belong to their renderer; never slice or reflow them.
        if line.lstrip().startswith(tuple("┌┐└┘├┤┬┴┼│╔╗╚╝║╠╣")) or width(line) <= cols:
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
    return "\n".join(out)

def panel(lines, cols=None):
    """Wrap semantic content before constructing a complete, budget-sized frame."""
    budget = max(20, int(cols if cols is not None else columns()))
    inner = budget - 4
    body = fit("\n".join(str(line).strip() for line in lines), inner)
    rows = _ANSI.sub("", body).splitlines()
    return "\n".join(["┌" + "─" * (budget - 2) + "┐"] +
                     ["│ " + row + " " * (inner - width(row)) + " │" for row in rows] +
                     ["└" + "─" * (budget - 2) + "┘"])


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
