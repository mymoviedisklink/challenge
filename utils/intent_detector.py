"""
intent_detector.py — Detect merchant intent transitions during conversation.
"""

import re
from typing import Literal

# Strong commitment / action signals
COMMITMENT_PATTERNS = [
    r"\blet'?s do it\b",
    r"\bgo ahead\b",
    r"\bproceed\b",
    r"\byes[,!.]?\s*(please|do it|go|sure|ok|okay)?\b",
    r"\bok(ay)?[,.]?\s*(let'?s|do it|go|sure|yes|haan)?\b",
    r"\bsounds good\b",
    r"\bi'?m in\b",
    r"\bsign me up\b",
    r"\bdo it\b",
    r"\bjust do it\b",
    r"\bconfirm\b",
    r"\bapprove\b",
    # Hindi
    r"\bhaan\b",
    r"\bkaro\b",
    r"\bkar do\b",
    r"\bchalo\b",
    r"\btheek hai\b",
    r"\bbilkul\b",
    r"\bji haan\b",
]

# Qualifying / still-exploring signals
QUALIFYING_PATTERNS = [
    r"\bwould you\b",
    r"\bdo you\b",
    r"\bcan you tell\b",
    r"\bwhat if\b",
    r"\bhow about\b",
    r"\btell me more\b",
    r"\bhow does it work\b",
    r"\bwhat would it\b",
    r"\bhow much\b",
    r"\bwhat are\b",
    r"\bexplain\b",
]

# Hostile / opt-out signals
HOSTILE_PATTERNS = [
    r"\bstop (messaging|sending|contacting)\b",
    r"\bnot interested\b",
    r"\bdo not (message|contact|send)\b",
    r"\bremove (me|my number)\b",
    r"\bunsubscribe\b",
    r"\bspam\b",
    r"\buseless\b",
    r"\bwaste (of time|my time)\b",
    r"\bleave me alone\b",
    r"\bband karo\b",  # "stop it" in Hindi
    r"\bmat bhejo\b",  # "don't send" in Hindi
    r"\bpareshaan mat karo\b",  # "don't bother me" in Hindi
]

# Out-of-scope requests
OUT_OF_SCOPE_PATTERNS = [
    r"\bgst (filing|return|payment)\b",
    r"\bincome tax\b",
    r"\bloan\b",
    r"\binsurance\b",
    r"\blegal advice\b",
    r"\bca (sahab|ji)?\b",
    r"\baccountant\b",
]

_COMMITMENT = [re.compile(p, re.IGNORECASE) for p in COMMITMENT_PATTERNS]
_QUALIFYING = [re.compile(p, re.IGNORECASE) for p in QUALIFYING_PATTERNS]
_HOSTILE = [re.compile(p, re.IGNORECASE) for p in HOSTILE_PATTERNS]
_OUT_OF_SCOPE = [re.compile(p, re.IGNORECASE) for p in OUT_OF_SCOPE_PATTERNS]


def detect_intent(message: str) -> Literal["commitment", "qualifying", "hostile", "out_of_scope", "neutral"]:
    """Classify merchant message intent."""
    msg = message.strip()

    for pattern in _HOSTILE:
        if pattern.search(msg):
            return "hostile"

    for pattern in _COMMITMENT:
        if pattern.search(msg):
            return "commitment"

    for pattern in _OUT_OF_SCOPE:
        if pattern.search(msg):
            return "out_of_scope"

    for pattern in _QUALIFYING:
        if pattern.search(msg):
            return "qualifying"

    return "neutral"
