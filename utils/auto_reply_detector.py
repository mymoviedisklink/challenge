"""
auto_reply_detector.py — Detect WhatsApp Business canned auto-replies.
"""

import re
from typing import List

# Common WhatsApp Business auto-reply phrases (case-insensitive)
AUTO_REPLY_PATTERNS = [
    r"thank you for contacting",
    r"our team will (respond|get back|reply)",
    r"we (are|will be) (currently )?unavailable",
    r"automated (message|response|reply)",
    r"we('ll| will) get back to you",
    r"this is an automated",
    r"your message has been received",
    r"currently out of office",
    r"away (message|reply)",
    r"auto.?reply",
    r"we have received your (message|inquiry|query)",
    r"main ek automated assistant hoon",
    r"yeh ek swachalit sandesh hai",
    r"hamari team aapko jald",
    r"aapki jaankari ke liye.*shukriya.*pahuncha",  # "we'll forward to our team"
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in AUTO_REPLY_PATTERNS]


def is_auto_reply(message: str) -> bool:
    """Return True if the message looks like a WhatsApp Business auto-reply."""
    msg = message.strip()
    for pattern in _COMPILED:
        if pattern.search(msg):
            return True
    return False


def count_consecutive_auto_replies(turns: List[dict]) -> int:
    """
    Count how many of the most-recent consecutive merchant turns are auto-replies.
    `turns` is a list of {from, body} dicts, most recent last.
    """
    count = 0
    for turn in reversed(turns):
        if turn.get("from") != "merchant":
            break
        if is_auto_reply(turn.get("body", "")):
            count += 1
        else:
            break
    return count


def same_message_repeated(message: str, turns: List[dict], min_repeats: int = 2) -> bool:
    """Return True if the same merchant message has appeared min_repeats times already."""
    merchant_msgs = [
        t["body"].strip() for t in turns
        if t.get("from") == "merchant" and t.get("body", "").strip()
    ]
    return merchant_msgs.count(message.strip()) >= min_repeats
