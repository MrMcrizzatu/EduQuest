import re
from functools import lru_cache
from pathlib import Path


FILTER_DIR = Path(__file__).resolve().parents[1] / "Filter"
FILTER_FILES = (
    "filter_profanity_russian.txt",
    "filter_banned_russian.txt",
    "filter_profanity_english.txt",
    "filter_banned_english.txt",
)

REGEX_MARKERS = set("\\|?*+[](){}^$")
LEET_MAP = str.maketrans({
    "0": "о",
    "3": "е",
    "4": "а",
    "6": "б",
    "@": "а",
    "$": "s",
})


def _normalize(text):
    return re.sub(r"[^0-9a-zа-яё]+", "", text.lower().translate(LEET_MAP))


def _word_tokens(text):
    return set(re.findall(r"[0-9a-zа-яё]+", text.lower().translate(LEET_MAP), re.IGNORECASE))


def _looks_like_regex(line):
    return any(ch in REGEX_MARKERS for ch in line)


@lru_cache(maxsize=1)
def _load_filters():
    literals = []
    regexes = []

    for filename in FILTER_FILES:
        path = FILTER_DIR / filename
        if not path.exists():
            continue

        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip().lower().lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue

            if _looks_like_regex(line):
                try:
                    regexes.append((line, re.compile(line, re.IGNORECASE | re.UNICODE)))
                except re.error:
                    normalized = _normalize(line)
                    if normalized:
                        literals.append((line, normalized))
            else:
                normalized = _normalize(line)
                if normalized:
                    literals.append((line, normalized))

    unique_literals = {}
    for original, normalized in literals:
        unique_literals.setdefault(normalized, original)

    return [(original, normalized) for normalized, original in unique_literals.items()], regexes


def check_text_for_profanity(text):
    """
    Returns a list of bad words or patterns found in the text.
    Uses local dictionaries from the Filter directory and does not depend on
    external profanity libraries.
    """
    if not text:
        return []

    literals, regexes = _load_filters()
    lowered_text = text.lower()
    compact_text = _normalize(text)
    tokens = _word_tokens(text)
    found = []

    for original, normalized in literals:
        if len(normalized) <= 3:
            if normalized in tokens:
                found.append(original)
        elif normalized in compact_text:
            found.append(original)

        if len(found) >= 10:
            return sorted(set(found))

    for original, pattern in regexes:
        match = pattern.search(lowered_text) or pattern.search(compact_text)
        if match:
            found.append(match.group(0) or original)

        if len(found) >= 10:
            break

    return sorted(set(found))
