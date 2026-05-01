"""
conversation_handlers.py — Multi-turn conversation state and reply logic.
"""
from __future__ import annotations

from utils.auto_reply_detector import (
    is_auto_reply,
    count_consecutive_auto_replies,
    same_message_repeated,
)
from utils.intent_detector import detect_intent


def handle_reply(
    conversation_id: str,
    merchant_id: str,
    message: str,
    turn_number: int,
    conversations: dict,
    contexts: dict,
    ended_conversations: set,
    suppressed_keys: set,
    composer_module,
) -> dict:
    """
    Main entry point for /v1/reply.
    Returns a response dict with action: send|wait|end.
    """
    # Don't respond to ended conversations
    if conversation_id in ended_conversations:
        return {"action": "end", "rationale": "Conversation already ended"}

    # Get conversation history
    history = conversations.get(conversation_id, [])

    # Append this merchant message
    history.append({"from": "merchant", "body": message})
    conversations[conversation_id] = history

    # ── 1. Auto-reply detection ──────────────────────────────────────────────
    consecutive_auto = count_consecutive_auto_replies(history)
    is_same_repeated = same_message_repeated(message, history[:-1], min_repeats=2)
    is_first_message = len(history) == 1  # Only the merchant message we just appended

    # End: 3+ consecutive auto-replies OR same auto-reply repeated in this conversation
    if consecutive_auto >= 3 or (consecutive_auto >= 1 and is_same_repeated):
        ended_conversations.add(conversation_id)
        return {
            "action": "end",
            "rationale": (
                f"Auto-reply detected {consecutive_auto}x consecutively "
                "(canned WhatsApp Business response). "
                "No real merchant engagement. Closing conversation."
            ),
        }

    # Wait: second auto-reply in the same conversation
    if consecutive_auto == 2:
        return {
            "action": "wait",
            "wait_seconds": 86400,
            "rationale": "Auto-reply received again — owner not at phone. Waiting 24h before retry.",
        }

    # If the very first message of a fresh conversation is an auto-reply,
    # wait immediately (no point nudging an empty thread)
    if is_auto_reply(message) and is_first_message:
        return {
            "action": "wait",
            "wait_seconds": 3600,
            "rationale": "First message of conversation is a WhatsApp Business auto-reply. Waiting 1h for owner to engage.",
        }

    # First auto-reply in an established conversation → nudge for the owner
    if is_auto_reply(message) and consecutive_auto == 1:
        nudge = "Looks like an auto-reply. When the owner sees this, just reply 'Yes' to continue."
        history.append({"from": "vera", "body": nudge})
        conversations[conversation_id] = history
        return {
            "action": "send",
            "body": nudge,
            "cta": "binary_yes_no",
            "rationale": "Detected WhatsApp Business auto-reply. Leaving a note for the owner.",
        }

    # ── 2. Intent detection ──────────────────────────────────────────────────
    intent = detect_intent(message)

    if intent == "hostile":
        ended_conversations.add(conversation_id)
        return {
            "action": "end",
            "rationale": "Merchant expressed frustration/opt-out. Closing gracefully.",
        }

    # ── 3. Load contexts for LLM reply ──────────────────────────────────────
    # Find the trigger associated with this conversation
    trigger_id = _find_trigger_for_conversation(conversation_id, contexts)
    trigger = contexts.get(("trigger", trigger_id), {}).get("payload", {}) if trigger_id else {}
    merchant = contexts.get(("merchant", merchant_id), {}).get("payload", {})
    category_slug = merchant.get("category_slug", "")
    category = contexts.get(("category", category_slug), {}).get("payload", {})
    customer_id = trigger.get("customer_id") if trigger else None
    customer = contexts.get(("customer", customer_id), {}).get("payload", {}) if customer_id else None

    # Determine conversation mode
    conversation_mode = "action" if intent == "commitment" else "normal"

    # ── 4. Out-of-scope ─────────────────────────────────────────────────────
    if intent == "out_of_scope":
        topic = trigger.get("kind", "the topic") if trigger else "this"
        return {
            "action": "send",
            "body": (
                f"That's outside what I can help with directly — "
                f"you'll need a specialist for that. "
                f"Coming back to {topic.replace('_', ' ')} — "
                f"want me to pick up where we left off?"
            ),
            "cta": "binary_yes_no",
            "rationale": "Out-of-scope request politely declined. Redirecting to original trigger topic.",
        }

    # ── 5. LLM-powered reply ────────────────────────────────────────────────
    if not merchant or not category:
        # Minimal fallback if contexts aren't loaded — still handle commitment
        if intent == "commitment":
            return {
                "action": "send",
                "body": (
                    "Done — proceeding right now. Here's what I'll draft next: "
                    "a customized campaign based on your profile. "
                    "Confirm and I'll send you the full plan."
                ),
                "cta": "binary_confirm_cancel",
                "rationale": "Merchant committed — switched to action mode (context not fully loaded)",
            }
        return {
            "action": "send",
            "body": "Got it! Here's the next step — let me pull up your details and proceed.",
            "cta": "open_ended",
            "rationale": "Context not loaded — generic acknowledgment with next-step framing",
        }

    result = composer_module.compose_reply(
        category=category,
        merchant=merchant,
        trigger=trigger,
        customer=customer,
        conversation_history=history,
        merchant_message=message,
        conversation_mode=conversation_mode,
    )

    # Track Vera's reply in history
    if result.get("action") == "send" and result.get("body"):
        history.append({"from": "vera", "body": result["body"]})
        conversations[conversation_id] = history

    if result.get("action") == "end":
        ended_conversations.add(conversation_id)

    return result


def _find_trigger_for_conversation(conversation_id: str, contexts: dict) -> str | None:
    """
    Extract trigger_id from conversation_id naming convention:
    conv_{merchant_id}_{trigger_id} → returns trigger_id portion.
    Also checks the stored conversation metadata.
    """
    # Try to parse from naming convention: conv_<merchant_id>_<trigger_id>
    if conversation_id.startswith("conv_"):
        parts = conversation_id[5:]  # strip "conv_"
        # Find matching trigger_id in contexts
        for (scope, ctx_id), _ in contexts.items():
            if scope == "trigger" and ctx_id in parts:
                return ctx_id
    return None
