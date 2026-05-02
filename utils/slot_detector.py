"""
slot_detector.py — Extract slot/time/date mentions from customer messages.
"""

import re
from typing import Optional


# Day patterns
_DAY_PATTERN = re.compile(
    r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday'
    r'|mon|tue|wed|thu|fri|sat|sun)\b',
    re.IGNORECASE
)

# Time patterns: "5pm", "5:30 PM", "17:00", etc.
_TIME_PATTERN = re.compile(
    r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))\b'
    r'|'
    r'\b(\d{1,2}:\d{2})\b',
    re.IGNORECASE
)

# Period-of-day patterns
_PERIOD_PATTERN = re.compile(
    r'\b(morning|afternoon|evening|night)\b',
    re.IGNORECASE
)

# Date patterns: "5 Nov", "November 5", "5/11", "5th November"
_DATE_PATTERN = re.compile(
    r'\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+'
    r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?'
    r'|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b'
    r'|'
    r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?'
    r'|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+'
    r'(\d{1,2})(?:st|nd|rd|th)?\b',
    re.IGNORECASE
)

# Confirmation patterns — customer is confirming a slot
_CONFIRM_PATTERN = re.compile(
    r'\b(works|perfect|confirm|done|book|booked|great|okay|ok|yes|fine'
    r'|sounds good|that works|lock it|lock that|i.?ll take)\b',
    re.IGNORECASE
)


def extract_slot(message: str) -> Optional[dict]:
    """
    Extract slot/time/date from a customer message.
    Returns dict with keys: day, time, period, date, confirmed
    or None if no slot info found.
    """
    result = {}

    day_match = _DAY_PATTERN.search(message)
    if day_match:
        result["day"] = day_match.group(0).strip().capitalize()

    time_match = _TIME_PATTERN.search(message)
    if time_match:
        result["time"] = (time_match.group(1) or time_match.group(2)).strip()

    period_match = _PERIOD_PATTERN.search(message)
    if period_match:
        result["period"] = period_match.group(0).strip().lower()

    date_match = _DATE_PATTERN.search(message)
    if date_match:
        groups = date_match.groups()
        if groups[0] and groups[1]:
            result["date"] = f"{groups[0]} {groups[1].capitalize()}"
        elif groups[2] and groups[3]:
            result["date"] = f"{groups[3]} {groups[2].capitalize()}"

    result["confirmed"] = bool(_CONFIRM_PATTERN.search(message))

    if not result.get("day") and not result.get("time") and not result.get("period") and not result.get("date"):
        if result.get("confirmed"):
            return result
        return None

    return result


def format_slot_summary(slot: dict) -> str:
    """Format extracted slot info into a human-readable string."""
    parts = []
    if slot.get("day"):
        parts.append(slot["day"])
    if slot.get("date"):
        parts.append(slot["date"])
    if slot.get("time"):
        parts.append(slot["time"])
    elif slot.get("period"):
        parts.append(slot["period"])
    return " ".join(parts) if parts else ""
