"""PII detection and redaction.

Pattern matching with validators (Luhn for cards, mod-97 for IBAN, area/group
rules for SSN) rather than raw regex, so the false-positive rate stays low
enough for the results to be worth acting on. Everything here is stdlib, so the
tool works in a bare install.

When ``presidio-analyzer`` is importable the detector adds its NER pass on top,
which catches the entities patterns cannot reach — person names, locations,
organisations. The pattern pass always runs, so installing Presidio widens
coverage without changing existing behaviour.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Match model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PiiMatch:
    """One detected entity, located by character offset in the source text."""

    entity_type: str
    start: int
    end: int
    value: str
    confidence: float
    detector: str = "pattern"

    def overlaps(self, other: PiiMatch) -> bool:
        return self.start < other.end and other.start < self.end


# --------------------------------------------------------------------------- #
# Validators
# --------------------------------------------------------------------------- #


def _luhn_ok(digits: str) -> bool:
    """Luhn checksum — rejects the many 16-digit numbers that are not cards."""
    nums = [int(c) for c in digits if c.isdigit()]
    if len(nums) < 12:
        return False
    checksum = 0
    parity = len(nums) % 2
    for index, digit in enumerate(nums):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _iban_ok(candidate: str) -> bool:
    """ISO 13616 mod-97 check."""
    compact = re.sub(r"\s+", "", candidate).upper()
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    converted = "".join(
        str(ord(char) - 55) if char.isalpha() else char for char in rearranged
    )
    if not converted.isdigit():
        return False
    return int(converted) % 97 == 1


def _us_ssn_ok(candidate: str) -> bool:
    """Reject the ranges the SSA never issues (000/666/900-999 area, 00 group, 0000 serial)."""
    digits = re.sub(r"\D", "", candidate)
    if len(digits) != 9:
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area in {"000", "666"} or area.startswith("9"):
        return False
    return group != "00" and serial != "0000"


def _always(_: str) -> bool:
    return True


# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Pattern:
    entity_type: str
    regex: re.Pattern[str]
    confidence: float
    validator: Callable[[str], bool] = _always
    # Which capture group holds the entity; 0 means the whole match. Used where
    # the regex needs leading context (a "SSN:" label) that is not itself PII.
    group: int = 0


_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern(
        "EMAIL_ADDRESS",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        0.95,
    ),
    _Pattern(
        "CREDIT_CARD",
        re.compile(r"\b(?:\d[ \-]?){13,19}\b"),
        0.9,
        _luhn_ok,
    ),
    _Pattern(
        "US_SSN",
        re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b"),
        0.85,
        _us_ssn_ok,
    ),
    _Pattern(
        "IBAN",
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
        0.9,
        _iban_ok,
    ),
    _Pattern(
        # E.164 and common national forms. Requires a separator or a + prefix so
        # bare order numbers do not match.
        "PHONE_NUMBER",
        re.compile(
            r"(?<!\d)(?<!\d\.)(?:\+\d{1,3}[ .\-]?)?(?:\(\d{2,4}\)[ .\-]?|\d{2,4}[ .\-])\d{3,4}[ .\-]?\d{3,4}(?!\d)(?!\.\d)"
        ),
        0.6,
    ),
    _Pattern(
        # Bare E.164 (+8801712345678) — no separators, so the form above misses it.
        "PHONE_NUMBER",
        re.compile(r"\+\d{8,15}(?!\d)"),
        0.7,
    ),
    _Pattern(
        "IP_ADDRESS",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b"
        ),
        0.7,
    ),
    _Pattern(
        "IP_ADDRESS",
        re.compile(r"\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b"),
        0.8,
    ),
    _Pattern(
        "DATE_OF_BIRTH",
        re.compile(
            r"\b(?:date\s+of\s+birth|birth\s*date|dob|born)\b\W{0,10}"
            r"(\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4})",
            re.IGNORECASE,
        ),
        0.8,
        group=1,
    ),
    _Pattern(
        "US_PASSPORT",
        re.compile(r"\bpassport\s*(?:no\.?|number|#)?\W{0,6}([A-Z0-9]{6,9})\b", re.IGNORECASE),
        0.7,
        group=1,
    ),
    _Pattern(
        "BD_NID",
        re.compile(
            r"\b(?:nid|national\s+id)\b\W{0,10}(\d{10}|\d{13}|\d{17})\b",
            re.IGNORECASE,
        ),
        0.8,
        group=1,
    ),
    _Pattern(
        "AWS_ACCESS_KEY",
        re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA|ACCA)[A-Z0-9]{16}\b"),
        0.95,
    ),
    _Pattern(
        "API_KEY",
        re.compile(
            r"\b(?:sk|pk|rk|api|key|token)[-_](?:live|test|proj|or|ant)?[-_]?[A-Za-z0-9]{16,}\b",
            re.IGNORECASE,
        ),
        0.75,
    ),
    _Pattern(
        "PRIVATE_KEY",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        0.99,
    ),
    _Pattern(
        "JWT",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
        0.9,
    ),
    _Pattern(
        "MEDICAL_RECORD_NUMBER",
        re.compile(r"\b(?:mrn|medical\s+record(?:\s+(?:no\.?|number|#))?)\W{0,6}([A-Z0-9\-]{5,15})\b", re.IGNORECASE),
        0.7,
        group=1,
    ),
)


SUPPORTED_ENTITIES: tuple[str, ...] = tuple(
    dict.fromkeys(pattern.entity_type for pattern in _PATTERNS)
)

# Entity types only Presidio's NER can reach. Listed so callers can request them
# and get a clear "install presidio-analyzer" answer instead of silent misses.
NER_ONLY_ENTITIES: tuple[str, ...] = ("PERSON", "LOCATION", "ORGANIZATION", "NRP")


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #


def _presidio_analyzer() -> Any | None:
    """Return a cached Presidio analyzer, or None when it is not installed."""
    global _ANALYZER_CACHE
    if _ANALYZER_CACHE is not _UNSET:
        return _ANALYZER_CACHE
    try:
        from presidio_analyzer import AnalyzerEngine

        _ANALYZER_CACHE = AnalyzerEngine()
    except Exception:  # ImportError, or a missing spaCy model at load time
        _ANALYZER_CACHE = None
    return _ANALYZER_CACHE


_UNSET = object()
_ANALYZER_CACHE: Any = _UNSET


def _pattern_matches(text: str, wanted: set[str] | None) -> Iterator[PiiMatch]:
    for pattern in _PATTERNS:
        if wanted is not None and pattern.entity_type not in wanted:
            continue
        for found in pattern.regex.finditer(text):
            value = found.group(pattern.group)
            if not value or not pattern.validator(value):
                continue
            yield PiiMatch(
                entity_type=pattern.entity_type,
                start=found.start(pattern.group),
                end=found.end(pattern.group),
                value=value,
                confidence=pattern.confidence,
            )


def _ner_matches(text: str, wanted: set[str] | None) -> Iterator[PiiMatch]:
    analyzer = _presidio_analyzer()
    if analyzer is None:
        return
    entities = sorted(wanted) if wanted else None
    try:
        results = analyzer.analyze(text=text, entities=entities, language="en")
    except Exception:
        return
    for result in results:
        yield PiiMatch(
            entity_type=result.entity_type,
            start=result.start,
            end=result.end,
            value=text[result.start : result.end],
            confidence=float(result.score),
            detector="ner",
        )


def _dedupe(matches: Iterable[PiiMatch]) -> list[PiiMatch]:
    """Keep the strongest match per overlapping span.

    Two detectors finding the same substring is the common case (a pattern hit
    and a Presidio hit on one email), and emitting both would double-count and
    corrupt redaction offsets.
    """
    ordered = sorted(matches, key=lambda m: (-m.confidence, m.start, -(m.end - m.start)))
    kept: list[PiiMatch] = []
    for candidate in ordered:
        if not any(candidate.overlaps(existing) for existing in kept):
            kept.append(candidate)
    return sorted(kept, key=lambda m: m.start)


def find_pii(
    text: str,
    entity_types: Iterable[str] | None = None,
    min_confidence: float = 0.5,
    use_ner: bool = True,
) -> list[PiiMatch]:
    """Locate PII in ``text``. The building block the tool functions share."""
    if not text:
        return []
    wanted = {entity.strip().upper() for entity in entity_types if entity.strip()} if entity_types else None
    if wanted == set():
        wanted = None

    found = list(_pattern_matches(text, wanted))
    if use_ner:
        found.extend(_ner_matches(text, wanted))
    return [match for match in _dedupe(found) if match.confidence >= min_confidence]


# --------------------------------------------------------------------------- #
# Redaction strategies
# --------------------------------------------------------------------------- #


def _mask(value: str, keep_last: int = 0) -> str:
    if keep_last <= 0:
        return "*" * len(value)
    visible = value[-keep_last:]
    return "*" * max(len(value) - keep_last, 0) + visible


def _hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _apply_strategy(match: PiiMatch, strategy: str, counters: dict[str, int]) -> str:
    if strategy == "remove":
        return ""
    if strategy == "mask":
        # Card and phone tails stay visible: they are how a human confirms the
        # right record without the redaction leaking the identifier.
        keep = 4 if match.entity_type in {"CREDIT_CARD", "PHONE_NUMBER"} else 0
        return _mask(match.value, keep)
    if strategy == "hash":
        return f"<{match.entity_type}:{_hash(match.value)}>"
    if strategy == "label":
        counters[match.entity_type] = counters.get(match.entity_type, 0) + 1
        return f"<{match.entity_type}_{counters[match.entity_type]}>"
    return f"<{match.entity_type}>"


REDACTION_STRATEGIES: tuple[str, ...] = ("mask", "label", "hash", "remove", "placeholder")


# --------------------------------------------------------------------------- #
# Tool entrypoints
# --------------------------------------------------------------------------- #


def detect_pii(text: str, entity_types: str = "", min_confidence: float = 0.5) -> str:
    """
    Scan text for personally identifiable information and report what was found.

    Values are reported truncated, never in full, so calling this tool does not
    itself copy the sensitive value into the transcript.

    Args:
        text: The text to scan.
        entity_types: Optional comma-separated filter, e.g. "EMAIL_ADDRESS,CREDIT_CARD".
            Empty means every supported type.
        min_confidence: Drop matches below this score (0.0-1.0, default 0.5).

    Returns:
        JSON: {"found": bool, "count": int, "entities": [...], "summary": {...}}
    """
    requested = [part for part in entity_types.split(",") if part.strip()] if entity_types else None
    try:
        matches = find_pii(text, requested, min_confidence)
    except Exception as exc:  # keep tool failures legible to the agent
        return json.dumps({"error": f"PII scan failed: {exc}"})

    summary: dict[str, int] = {}
    for match in matches:
        summary[match.entity_type] = summary.get(match.entity_type, 0) + 1

    entities = [
        {
            "entity_type": match.entity_type,
            "start": match.start,
            "end": match.end,
            "confidence": round(match.confidence, 3),
            "detector": match.detector,
            "preview": _mask(match.value, keep_last=min(2, len(match.value))),
        }
        for match in matches
    ]
    return json.dumps(
        {
            "found": bool(matches),
            "count": len(matches),
            "entities": entities,
            "summary": summary,
            "ner_available": _presidio_analyzer() is not None,
        },
        indent=2,
    )


def redact_pii(text: str, strategy: str = "mask", entity_types: str = "", min_confidence: float = 0.5) -> str:
    """
    Remove personally identifiable information from text and return the clean version.

    Args:
        text: The text to redact.
        strategy: How to replace each hit —
            "mask" (asterisks, card/phone keep the last 4),
            "label" (numbered <EMAIL_ADDRESS_1> placeholders),
            "hash" (stable pseudonym, same value maps to the same token),
            "remove" (delete outright),
            "placeholder" (bare <EMAIL_ADDRESS> tag).
        entity_types: Optional comma-separated filter. Empty means every supported type.
        min_confidence: Drop matches below this score (0.0-1.0, default 0.5).

    Returns:
        JSON: {"redacted": str, "redaction_count": int, "summary": {...}}
    """
    if strategy not in REDACTION_STRATEGIES:
        return json.dumps(
            {"error": f"Unknown strategy '{strategy}'. Use one of: {', '.join(REDACTION_STRATEGIES)}"}
        )

    requested = [part for part in entity_types.split(",") if part.strip()] if entity_types else None
    try:
        matches = find_pii(text, requested, min_confidence)
    except Exception as exc:
        return json.dumps({"error": f"PII redaction failed: {exc}"})

    counters: dict[str, int] = {}
    summary: dict[str, int] = {}
    pieces: list[str] = []
    cursor = 0
    # Matches are start-ordered and non-overlapping, so a single forward pass
    # rebuilds the string without any offset bookkeeping.
    for match in matches:
        pieces.append(text[cursor : match.start])
        pieces.append(_apply_strategy(match, strategy, counters))
        summary[match.entity_type] = summary.get(match.entity_type, 0) + 1
        cursor = match.end
    pieces.append(text[cursor:])

    return json.dumps(
        {
            "redacted": "".join(pieces),
            "redaction_count": len(matches),
            "summary": summary,
            "strategy": strategy,
        },
        indent=2,
    )


def list_pii_entity_types() -> str:
    """
    List every PII entity type this tool can detect.

    Returns:
        JSON with the pattern-backed types, the NER-only types, and whether the
        optional NER backend is currently installed.
    """
    return json.dumps(
        {
            "pattern_entities": list(SUPPORTED_ENTITIES),
            "ner_entities": list(NER_ONLY_ENTITIES),
            "ner_available": _presidio_analyzer() is not None,
            "strategies": list(REDACTION_STRATEGIES),
            "note": (
                "NER entities require the optional 'presidio-analyzer' package. "
                "Pattern entities always work."
            ),
        },
        indent=2,
    )


def as_dicts(matches: Iterable[PiiMatch]) -> list[dict[str, Any]]:
    """Serialise matches for callers that want the raw structure (e.g. guardrails)."""
    return [asdict(match) for match in matches]
