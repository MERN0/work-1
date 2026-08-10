"""Text normalisation shared by ingestion, selection, tracing and validation."""

from __future__ import annotations

import re
import unicodedata

#: Characters used in the requirement workbooks to mark "this row belongs to that
#: feature". The sheets mix the CJK circle, the geometric circle and a plain letter o,
#: so all of them count. ``✓``/``x`` show up in some projects' variants.
CIRCLE_MARKS = frozenset("○〇◯●◎oO0*✓✔xX")

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_FEATURE_NUM_RE = re.compile(r"^\s*0*(\d+)\s*$")


def clean(value: object) -> str:
    """Coerce a cell value to a trimmed string, collapsing internal whitespace.

    ``None`` and pandas/openpyxl empty markers become ``""``.
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    # Normalise unicode so full-width characters compare equal to ASCII.
    text = unicodedata.normalize("NFKC", text)
    return _WS_RE.sub(" ", text).strip()


def normalize(value: object) -> str:
    """Aggressively normalise for fuzzy comparison: lowercase, alphanumeric only."""
    return _NON_ALNUM_RE.sub("", clean(value).lower())


def normalize_loose(value: object) -> str:
    """Lowercase with single spaces — used for substring keyword matching."""
    return _NON_ALNUM_RE.sub(" ", clean(value).lower()).strip()


def is_marked(value: object) -> bool:
    """True when a feature-column cell carries a membership mark.

    Feature columns are sparse: an empty cell means "not part of this feature", and any
    of :data:`CIRCLE_MARKS` means it is. A dash or ``-`` explicitly means "not applicable".
    """
    text = clean(value)
    if not text or text in {"-", "--", "N/A", "n/a"}:
        return False
    return all(ch in CIRCLE_MARKS for ch in text)


def feature_key(value: object) -> str:
    """Canonical form of a feature number so ``5``, ``05``, ``"005"`` all match.

    Non-numeric headers (``Signal ID``, ``Remarks``) return ``""`` and are therefore
    never mistaken for feature columns.
    """
    text = clean(value)
    if not text:
        return ""
    # Excel often reads a "005" header as the number 5.0.
    if text.endswith(".0"):
        text = text[:-2]
    match = _FEATURE_NUM_RE.match(text)
    if not match:
        return ""
    return match.group(1)


def feature_label(key: str, width: int = 3) -> str:
    """Render a canonical feature key back as a zero-padded sheet name (``5`` -> ``005``)."""
    return key.zfill(width) if key.isdigit() else key


def split_list(value: object, separators: str = ",;/|") -> list[str]:
    """Split a cell holding a delimited list into cleaned, de-duplicated parts."""
    text = clean(value)
    if not text:
        return []
    pattern = f"[{re.escape(separators)}]"
    parts = [clean(p) for p in re.split(pattern, text)]
    return list(dict.fromkeys(p for p in parts if p))


def parse_enum_map(value: object) -> dict[str, str]:
    """Parse a *Configurations* cell such as ``0x00:H, 0x01:P, 0x10:Original Mode``.

    Returns ``{"0x00": "H", "0x01": "P", "0x10": "Original Mode"}``. Fragments without a
    colon are ignored rather than guessed at.
    """
    result: dict[str, str] = {}
    for part in split_list(value, ",;"):
        if ":" not in part:
            continue
        key, _, label = part.partition(":")
        key, label = clean(key), clean(label)
        if key:
            result[key] = label
    return result


def parse_tolerance_pair(value: object) -> tuple[str, str]:
    """Parse a tolerance ``Value`` cell like ``0.5,1.5`` into (positive, negative).

    A single value applies to both sides. Returns ``("", "")`` when unparseable.
    """
    parts = split_list(value, ",")
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], parts[1]


def truncate(text: str, max_chars: int, marker: str = " [...]") -> str:
    """Truncate to a character budget without splitting mid-word where avoidable."""
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - len(marker)]
    space = cut.rfind(" ")
    if space > max_chars * 0.6:
        cut = cut[:space]
    return cut.rstrip() + marker


def contains_any(haystack: str, needles: list[str]) -> str:
    """Return the first needle present in ``haystack`` (loose match), else ``""``."""
    hay = normalize_loose(haystack)
    if not hay:
        return ""
    for needle in needles:
        if normalize_loose(needle) in hay:
            return needle
    return ""


def sheet_safe(name: str, fallback: str = "Sheet1") -> str:
    """Coerce a string into a legal Excel sheet name (<=31 chars, no ``[]:*?/\\``)."""
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", clean(name)).strip("'")
    cleaned = cleaned[:31].strip()
    return cleaned or fallback
