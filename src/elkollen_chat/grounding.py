"""Check that every number and date in an answer came from the tools.

The assistant is told to use only what the tools returned. This module checks it after
the fact and returns what it could not verify, so the UI can mark it instead of
presenting it as fact.

* Numbers: each number in the answer must match a number in the tool results, allowing
  for rounding and for öre <-> kronor and ratio <-> percent. "1,045" is accepted as
  either 1045 or 1.045 (English thousands vs Swedish decimals).
* Dates: ISO dates (2026-11-24), day-month dates ("24 nov", "24 november") and years
  (2026) must match a date that appears in the tool arguments or results.

Ignored: clock times (14:15), numbers the user wrote in the question ("4 hours"), area
names (SE3) and small integers up to 10 (mostly counts and durations). This is a safety
net, not a proof.
"""

import re
from collections.abc import Iterable
from datetime import date
from typing import Any

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_SPACES = re.compile(r"[   ]")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b")
_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "januari", "january"),
            ("feb", "februari", "february"),
            ("mar", "mars", "march"),
            ("apr", "april"),
            ("maj", "may"),
            ("jun", "juni", "june"),
            ("jul", "juli", "july"),
            ("aug", "augusti", "august"),
            ("sep", "sept", "september"),
            ("okt", "oct", "oktober", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\.?\s+("
    + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")\b\.?",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(20\d{2})\b")
_TIME = re.compile(r"\b\d{1,2}[:.]\d{2}\b(?![.,]\d)")
_NUMBER = re.compile(r"(?<![\w.,])-?\d{1,3}(?: \d{3})+(?:[.,]\d+)?|(?<![\w.,])-?\d+(?:[.,]\d+)?")
_SMALL_INT_LIMIT = 10


def _normalise(text: str) -> str:
    return _SPACES.sub(" ", text.translate(_DASHES))


def _strip_dates(text: str) -> tuple[str, list[str], list[tuple[int, int]], list[int]]:
    iso = [m.group(0)[:10] for m in _ISO_DATE.finditer(text)]
    text = _ISO_DATE.sub(" ", text)
    day_month = [(int(d), _MONTHS[m.lower()]) for d, m in _DAY_MONTH.findall(text)]
    text = _DAY_MONTH.sub(" ", text)
    years = [int(y) for y in _YEAR.findall(text)]
    text = _YEAR.sub(" ", text)
    return text, iso, day_month, years


_DURATION_AFTER = re.compile(
    r"\s*-?\s*(?:days?|dagars?|dygn|hours?|h\b|timmes?|timmar|timmars|minutes?|minuter|min\b"
    r"|weeks?|veckor|veckors|months?|månader|månaders)",
    re.IGNORECASE,
)


def _readings(raw: str) -> list[tuple[float, float]]:
    """Possible values of a written number, each with the rounding tolerance its written
    precision allows ("11" covers 10.5-11.5, "11.2" covers 11.15-11.25)."""
    compact = raw.replace(" ", "")
    texts = {compact.replace(",", ".")}
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", compact):  # 1,045 could be English 1045
        texts.add(compact.replace(",", ""))
    out = []
    for t in texts:
        try:
            value = float(t)
        except ValueError:
            continue
        decimals = len(t.split(".")[1]) if "." in t else 0
        out.append((value, 0.5 * 10**-decimals))
    return out


def extract_numbers(text: str) -> list[tuple[str, list[float]]]:
    """Numbers as written, each with its possible values, minus dates, times and
    durations ("30-day", "4 timmar")."""
    cleaned, *_ = _strip_dates(_normalise(text))
    cleaned = _TIME.sub(" ", cleaned)
    out = []
    for match in _NUMBER.finditer(cleaned):
        if _DURATION_AFTER.match(cleaned, match.end()):
            continue
        raw = match.group(0).strip()
        values = [v for v, _ in _readings(raw)]
        if values:
            out.append((raw, values))
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
            if 0 < v < 10:  # a ratio of 1.44 is "44 % above"; 0.8 is "20 % below"
                found.update({round((v - 1) * 100, 6), round((1 - v) * 100, 6)})
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list | tuple):
            for v in value:
                walk(v)

    walk(obj)
    return found


def dates_in(obj: Any) -> set[date]:
    """Every ISO date (or datetime prefix) in a nested structure of strings."""
    found: set[date] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            for y, m, d in _ISO_DATE.findall(value):
                try:
                    found.add(date(int(y), int(m), int(d)))
                except ValueError:
                    continue
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list | tuple):
            for v in value:
                walk(v)

    walk(obj)
    return found


def _matches(readings: Iterable[tuple[float, float]], known: Iterable[float]) -> bool:
    """True if some reading equals a known number once rounded to the written precision
    (or within 0.5 % for large numbers)."""
    known = list(known)
    for value, tolerance in readings:
        for k in known:
            if abs(value - k) <= max(tolerance + 1e-9, abs(k) * 0.005):
                return True
    return False


def check(answer: str, evidence: list[Any], question: str = "") -> dict:
    """`evidence`: tool results and tool arguments the answer may draw on."""
    known_numbers: set[float] = set()
    known_dates: set[date] = set()
    for item in evidence:
        known_numbers |= numbers_in(item)
        known_dates |= dates_in(item)
    asked = {v for _, values in extract_numbers(question) for v in values}

    checked, ungrounded = 0, []
    for raw, values in extract_numbers(answer):
        if any(v in asked for v in values) or any(
            v.is_integer() and abs(v) <= _SMALL_INT_LIMIT for v in values
        ):
            continue
        checked += 1
        if not _matches(_readings(raw), known_numbers):
            ungrounded.append(raw)

    _, iso, day_month, years = _strip_dates(_normalise(answer))
    _, _, _, asked_years = _strip_dates(_normalise(question))
    unverified_dates = [d for d in iso if _safe_date(d) not in known_dates]
    unverified_dates += [
        f"{d}/{m}"
        for d, m in day_month
        if not any(k.day == d and k.month == m for k in known_dates)
    ]
    unverified_dates += [
        str(y) for y in years if y not in asked_years and not any(k.year == y for k in known_dates)
    ]
    return {
        "numbers_checked": checked,
        "ungrounded": ungrounded,
        "unverified_dates": unverified_dates,
        "ok": not ungrounded and not unverified_dates,
    }


def _safe_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None
