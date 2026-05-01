"""
validators.py — Post-LLM output validation for composed messages.
"""

import json
import re
from typing import Optional


VALID_CTA_VALUES = {
    "binary_yes_no", "binary_confirm_cancel", "open_ended",
    "multi_choice_slot", "none"
}

VALID_SEND_AS_VALUES = {"vera", "merchant_on_behalf"}


def validate_action(action: dict, category: dict) -> list[str]:
    """
    Validate a composed action dict. Returns a list of error strings.
    Empty list = valid.
    """
    errors = []

    body = action.get("body", "")
    if not body or not body.strip():
        errors.append("body is empty")

    if len(body) > 2000:
        errors.append(f"body too long ({len(body)} chars)")

    cta = action.get("cta", "")
    if cta not in VALID_CTA_VALUES:
        errors.append(f"invalid cta '{cta}' — must be one of {VALID_CTA_VALUES}")

    send_as = action.get("send_as", "")
    if send_as not in VALID_SEND_AS_VALUES:
        errors.append(f"invalid send_as '{send_as}'")

    if not action.get("suppression_key"):
        errors.append("suppression_key is missing")

    if not action.get("rationale"):
        errors.append("rationale is missing")

    # Check for taboo words from category voice
    taboo_words = category.get("voice", {}).get("vocab_taboo", [])
    body_lower = body.lower()
    for word in taboo_words:
        if word.lower() in body_lower:
            errors.append(f"taboo word found: '{word}'")

    # Check for URLs (Meta rejects them)
    if re.search(r'https?://', body):
        errors.append("body contains URL — Meta will reject")

    return errors


def parse_llm_json(response: str) -> Optional[dict]:
    """
    Parse JSON from LLM response. Tries strict parse, then extracts first JSON block.
    """
    # Try direct parse first
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass

    # Extract JSON block from markdown code fence
    match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', response)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: try finding the first { and parsing from there by iteratively trimming
    start = response.find('{')
    while start != -1:
        end = response.rfind('}')
        if end > start:
            try:
                return json.loads(response[start:end+1])
            except json.JSONDecodeError:
                pass
        # If that failed, find the next {
        start = response.find('{', start + 1)

    return None
