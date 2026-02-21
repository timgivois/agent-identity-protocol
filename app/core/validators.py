"""
Heuristic validators for agent output.

These run automatically after an agent produces output — before it reaches a human gate.
They catch ~80% of errors cheaply (no human cost).

Supported checks:
  - min_words / max_words
  - required_keywords
  - forbidden_keywords
  - min_chars / max_chars
  - must_contain_url
  - sentiment (positive / negative / neutral) — basic keyword heuristic
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    passed: bool
    checks: list[dict] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "checks": self.checks,
            "summary": self.summary,
        }


def _word_count(text: str) -> int:
    return len(text.split())


def _char_count(text: str) -> int:
    return len(text)


POSITIVE_WORDS = {"great", "excellent", "good", "amazing", "fantastic", "perfect",
                  "wonderful", "outstanding", "superb", "brilliant"}
NEGATIVE_WORDS = {"terrible", "awful", "bad", "horrible", "dreadful", "poor",
                  "disappointing", "mediocre", "failure", "worst"}


def _sentiment(text: str) -> str:
    words = set(text.lower().split())
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    if pos > neg:
        return "positive"
    elif neg > pos:
        return "negative"
    return "neutral"


def run_heuristics(output_text: str, config: dict) -> ValidationResult:
    """
    Run all configured heuristic checks on agent output.
    config is a dict loaded from role.heuristic_config.
    """
    if not config:
        return ValidationResult(passed=True, summary="No heuristics configured — auto-pass")

    checks = []
    all_passed = True

    # Word count
    if "min_words" in config or "max_words" in config:
        count = _word_count(output_text)
        if "min_words" in config and count < config["min_words"]:
            checks.append({"check": "min_words", "passed": False,
                           "detail": f"Got {count} words, need ≥{config['min_words']}"})
            all_passed = False
        elif "max_words" in config and count > config["max_words"]:
            checks.append({"check": "max_words", "passed": False,
                           "detail": f"Got {count} words, need ≤{config['max_words']}"})
            all_passed = False
        else:
            checks.append({"check": "word_count", "passed": True, "detail": f"{count} words ✓"})

    # Char count
    if "min_chars" in config or "max_chars" in config:
        count = _char_count(output_text)
        if "min_chars" in config and count < config["min_chars"]:
            checks.append({"check": "min_chars", "passed": False,
                           "detail": f"Got {count} chars, need ≥{config['min_chars']}"})
            all_passed = False
        elif "max_chars" in config and count > config["max_chars"]:
            checks.append({"check": "max_chars", "passed": False,
                           "detail": f"Got {count} chars, need ≤{config['max_chars']}"})
            all_passed = False
        else:
            checks.append({"check": "char_count", "passed": True, "detail": f"{count} chars ✓"})

    # Required keywords
    if "required_keywords" in config:
        text_lower = output_text.lower()
        missing = [kw for kw in config["required_keywords"] if kw.lower() not in text_lower]
        if missing:
            checks.append({"check": "required_keywords", "passed": False,
                           "detail": f"Missing keywords: {missing}"})
            all_passed = False
        else:
            checks.append({"check": "required_keywords", "passed": True,
                           "detail": f"All {len(config['required_keywords'])} keywords present ✓"})

    # Forbidden keywords
    if "forbidden_keywords" in config:
        text_lower = output_text.lower()
        found = [kw for kw in config["forbidden_keywords"] if kw.lower() in text_lower]
        if found:
            checks.append({"check": "forbidden_keywords", "passed": False,
                           "detail": f"Forbidden keywords found: {found}"})
            all_passed = False
        else:
            checks.append({"check": "forbidden_keywords", "passed": True,
                           "detail": "No forbidden keywords ✓"})

    # URL presence
    if config.get("must_contain_url"):
        url_pattern = re.compile(r'https?://\S+')
        if not url_pattern.search(output_text):
            checks.append({"check": "must_contain_url", "passed": False,
                           "detail": "No URL found in output"})
            all_passed = False
        else:
            checks.append({"check": "must_contain_url", "passed": True, "detail": "URL found ✓"})

    # Sentiment
    if "required_sentiment" in config:
        detected = _sentiment(output_text)
        expected = config["required_sentiment"]
        if detected != expected:
            checks.append({"check": "sentiment", "passed": False,
                           "detail": f"Detected '{detected}', expected '{expected}'"})
            all_passed = False
        else:
            checks.append({"check": "sentiment", "passed": True,
                           "detail": f"Sentiment is '{detected}' ✓"})

    passed_count = sum(1 for c in checks if c["passed"])
    summary = f"{passed_count}/{len(checks)} checks passed" if checks else "No checks run"

    return ValidationResult(passed=all_passed, checks=checks, summary=summary)
