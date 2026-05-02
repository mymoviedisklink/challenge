"""
conversation_handlers.py — Multi-turn conversation state and reply logic.

Differentiates between merchant and customer replies (from_role).
"""
from __future__ import annotations

from utils.auto_reply_detector import (
    is_auto_reply,
    count_consecutive_auto_replies,
    same_message_repeated,
)
from utils.intent_detector import detect_intent
from utils.slot_detector import extract_slot, format_slot_summary


def handle_reply(
    conversation_id: str,
    merchant_id: str,
    customer_id: str | None,
    from_role: str,
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
    Routes to customer-specific or merchant-specific handler based on from_role.
    Returns a response dict with action: send|wait|end.
    """
    # Don't respond to ended conversations
    if conversation_id in ended_conversations:
        return {"action": "end", "rationale": "Conversation already ended"}

    # Get conversation history
    history = conversations.get(conversation_id, [])

    # Append this message
    history.append({"from": from_role, "body": message})
    conversations[conversation_id] = history

    # Route by from_role
    if from_role == "customer":
        return _handle_customer_reply(
            conversation_id=conversation_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            message=message,
            turn_number=turn_number,
            history=history,
            conversations=conversations,
            contexts=contexts,
            ended_conversations=ended_conversations,
            suppressed_keys=suppressed_keys,
            composer_module=composer_module,
        )
    else:
        return _handle_merchant_reply(
            conversation_id=conversation_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            message=message,
            turn_number=turn_number,
            history=history,
            conversations=conversations,
            contexts=contexts,
            ended_conversations=ended_conversations,
            suppressed_keys=suppressed_keys,
            composer_module=composer_module,
        )


# ─── Customer reply handler ─────────────────────────────────────────────────

def _handle_customer_reply(
    conversation_id: str,
    merchant_id: str,
    customer_id: str | None,
    message: str,
    turn_number: int,
    history: list,
    conversations: dict,
    contexts: dict,
    ended_conversations: set,
    suppressed_keys: set,
    composer_module,
) -> dict:
    """Handle a reply from a customer. Respond AS the merchant (on-behalf)."""

    # Load customer context
    customer = None
    customer_name = "there"
    if customer_id:
        cust_entry = contexts.get(("customer", customer_id))
        if cust_entry:
            customer = cust_entry["payload"]
            customer_name = customer.get("identity", {}).get("name", "there")

    # Load merchant context for on-behalf replies
    merchant = contexts.get(("merchant", merchant_id), {}).get("payload", {})
    merchant_name = merchant.get("identity", {}).get("name", "our clinic")
    category_slug = merchant.get("category_slug", "")
    category = contexts.get(("category", category_slug), {}).get("payload", {})

    # Find trigger
    trigger_id = _find_trigger_for_conversation(conversation_id, contexts)
    trigger = contexts.get(("trigger", trigger_id), {}).get("payload", {}) if trigger_id else {}

    # ── 1. Slot pick detection ───────────────────────────────────────────────
    slot = extract_slot(message)
    if slot:
        slot_summary = format_slot_summary(slot)

        # Build a personalized confirmation
        if slot_summary:
            confirmation = (
                f"{customer_name}, your appointment for {slot_summary} is confirmed! "
                f"We'll send you a reminder beforehand. "
                f"See you then!"
            )
        else:
            # Customer confirmed but no specific slot extracted
            confirmation = (
                f"{customer_name}, got it — we've noted your preference. "
                f"We'll confirm the exact slot shortly. See you soon!"
            )

        history.append({"from": "vera", "body": confirmation})
        conversations[conversation_id] = history

        return {
            "action": "send",
            "body": confirmation,
            "cta": "none",
            "rationale": (
                f"Customer {customer_name} picked a slot "
                f"({slot_summary or 'confirmed'}). "
                f"Personalized confirmation addressing customer by name and echoing slot."
            ),
        }

    # ── 2. Hostile / opt-out from customer ───────────────────────────────────
    intent = detect_intent(message)
    if intent == "hostile":
        ended_conversations.add(conversation_id)
        return {
            "action": "end",
            "rationale": f"Customer {customer_name} opted out. Ending gracefully.",
        }

    # ── 3. LLM-powered customer reply ────────────────────────────────────────
    if merchant and category:
        result = composer_module.compose_reply(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            conversation_history=history,
            merchant_message=message,
            conversation_mode="normal",
            from_role="customer",
            customer_name=customer_name,
        )

        if result.get("action") == "send" and result.get("body"):
            history.append({"from": "vera", "body": result["body"]})
            conversations[conversation_id] = history

        if result.get("action") == "end":
            ended_conversations.add(conversation_id)

        return result

    # Fallback: personalized even without full context
    fallback_body = (
        f"{customer_name}, thank you for your message! "
        f"We'll get back to you shortly with the details."
    )
    history.append({"from": "vera", "body": fallback_body})
    conversations[conversation_id] = history

    return {
        "action": "send",
        "body": fallback_body,
        "cta": "none",
        "rationale": f"Customer {customer_name} replied — personalized acknowledgement (context not fully loaded)",
    }


# ─── Merchant reply handler ─────────────────────────────────────────────────

def _handle_merchant_reply(
    conversation_id: str,
    merchant_id: str,
    customer_id: str | None,
    message: str,
    turn_number: int,
    history: list,
    conversations: dict,
    contexts: dict,
    ended_conversations: set,
    suppressed_keys: set,
    composer_module,
) -> dict:
    """Handle a reply from a merchant. Respond AS Vera."""

    # ── 1. Auto-reply detection ──────────────────────────────────────────────
    consecutive_auto = count_consecutive_auto_replies(history)
    is_same_repeated = same_message_repeated(message, history[:-1], min_repeats=2)
    is_first_message = len(history) == 1

    # End: 3+ consecutive auto-replies OR same auto-reply repeated
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

    # Wait: second auto-reply
    if consecutive_auto == 2:
        return {
            "action": "wait",
            "wait_seconds": 86400,
            "rationale": "Auto-reply received again — owner not at phone. Waiting 24h before retry.",
        }

    # First message is auto-reply → wait
    if is_auto_reply(message) and is_first_message:
        return {
            "action": "wait",
            "wait_seconds": 3600,
            "rationale": "First message of conversation is a WhatsApp Business auto-reply. Waiting 1h for owner to engage.",
        }

    # First auto-reply in established conversation → nudge
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

    # ── 3. Load contexts ─────────────────────────────────────────────────────
    trigger_id = _find_trigger_for_conversation(conversation_id, contexts)
    trigger = contexts.get(("trigger", trigger_id), {}).get("payload", {}) if trigger_id else {}
    merchant = contexts.get(("merchant", merchant_id), {}).get("payload", {})
    category_slug = merchant.get("category_slug", "")
    category = contexts.get(("category", category_slug), {}).get("payload", {})
    cust_id = customer_id or (trigger.get("customer_id") if trigger else None)
    customer = contexts.get(("customer", cust_id), {}).get("payload", {}) if cust_id else None

    # Determine conversation mode
    conversation_mode = "action" if intent == "commitment" else "normal"

    # ── 4. Out-of-scope ──────────────────────────────────────────────────────
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

    # ── 5. Commitment with context → merchant-specific action ────────────────
    if intent == "commitment" and merchant and category:
        merchant_name = merchant.get("identity", {}).get("owner_first_name", "there")
        trigger_kind = trigger.get("kind", "campaign") if trigger else "campaign"

        result = composer_module.compose_reply(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            conversation_history=history,
            merchant_message=message,
            conversation_mode="action",
            from_role="merchant",
            customer_name=None,
        )

        if result.get("action") == "send" and result.get("body"):
            history.append({"from": "vera", "body": result["body"]})
            conversations[conversation_id] = history

        return result

    # ── 6. Commitment without context → smart fallback ───────────────────────
    if intent == "commitment":
        merchant_name = merchant.get("identity", {}).get("owner_first_name", "there") if merchant else "there"
        trigger_kind = trigger.get("kind", "campaign") if trigger else "campaign"
        kind_label = trigger_kind.replace("_", " ")

        return {
            "action": "send",
            "body": (
                f"Done, {merchant_name} — I'm putting together the {kind_label} "
                f"details for you right now. You'll have the full draft to review "
                f"within the hour. Confirm once you see it and we go live."
            ),
            "cta": "binary_confirm_cancel",
            "rationale": (
                f"Merchant {merchant_name} committed to {kind_label}. "
                f"Switched to action mode with merchant-specific next step."
            ),
        }

    # ── 7. LLM-powered reply ────────────────────────────────────────────────
    if not merchant or not category:
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
        from_role="merchant",
        customer_name=None,
    )

    # Track Vera's reply in history
    if result.get("action") == "send" and result.get("body"):
        history.append({"from": "vera", "body": result["body"]})
        conversations[conversation_id] = history

    if result.get("action") == "end":
        ended_conversations.add(conversation_id)

    return result


# ─── Helpers ─────────────────────────────────────────────────────────────────

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
