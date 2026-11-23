"""Check that every number in an answer came from a tool result.

The assistant is told to use only numbers the tools returned. This module checks it
after the fact: it pulls the numbers out of the answer and looks for each one among the
numbers in the tool results (also as öre <-> kronor and ratio <-> percent, and allowing
for rounding). Numbers that cannot be found are returned so the UI can mark them as
unverified instead of presenting them as facts.

Deliberately ignored: clock times (14:15), dates (2025-10-04), numbers the user wrote in
the question (e.g. "2 hours"), area names (SE3) and small integers up to 10, which are
mostly counts and durations. This is a safety net, not a proof.
"""

import re
from collections.abc import Iterable
from typing import Any

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b")
_TIME = re.compile(r"\b\d{1,2}[:.]\d{2}\b(?![.,]\d)")
_NUMBER = re.compile(
    r"(?<![\w.,])-?\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|(?<![\w.,])-?\d+(?:[.,]\d+)?"
)
_SMALL_INT_LIMIT = 10


def extract_numbers(text: str) -> list[tuple[str, float]]:
    """Numbers as written in `text` (Swedish or English style), minus dates and times."""
    cleaned = _TIME.sub(" ", _DATE.sub(" ", text))
    out = []
    for match in _NUMBER.finditer(cleaned):
        raw = match.group(0)
        normal = re.sub(r"[   ]", "", raw).replace(",", ".")
        try:
            out.append((raw.strip(), float(normal)))
        except ValueError:
            continue
    return out


def numbers_in(obj: Any) -> set[float]:
    """Every numeric value in a (nested) tool result, plus unit conversions of it."""
    found: set[float] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, int | float):
            v = float(value)
            found.update({v, v / 100, v * 100})  # öre <-> kr, ratio <-> percent
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list | tuple):
            for v in value:
                walk(v)

    walk(obj)
    return found


def _matches(value: float, known: Iterable[float]) -> bool:
    for k in known:
        tolerance = max(0.051, abs(k) * 0.005)
        if abs(value - k) <= tolerance or abs(abs(value) - abs(k)) <= tolerance and value * k < 0:
            return True
    return False


def check(answer: str, tool_results: list[Any], question: str = "") -> dict:
    known = set()
    for result in tool_results:
        known |= numbers_in(result)
    asked = {v for _, v in extract_numbers(question)}
    checked, ungrounded = 0, []
    for raw, value in extract_numbers(answer):
        if value in asked or (value.is_integer() and abs(value) <= _SMALL_INT_LIMIT):
            continue
        checked += 1
        if not _matches(value, known):
            ungrounded.append(raw)
    return {"numbers_checked": checked, "ungrounded": ungrounded, "ok": not ungrounded}
