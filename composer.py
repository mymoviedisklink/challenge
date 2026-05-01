"""
composer.py — LLM-powered message composition engine.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv
from openai import OpenAI

from prompts.system_prompt import build_system_prompt
from prompts.trigger_prompts import build_user_prompt
from utils.validators import validate_action, parse_llm_json

load_dotenv()

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "test"),
            base_url=os.getenv("OPENAI_API_BASE", "http://103.42.50.229:8000"),
        )
    return _client


def _call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
    client = _get_client()
    model = os.getenv("LLM_MODEL", "Qwen3.6-35B-A3B")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=8192,
        extra_body={
            "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    return response.choices[0].message.content or ""


def _determine_send_as(trigger: dict, customer: dict | None) -> str:
    scope = trigger.get("scope", "merchant")
    if scope == "customer" and customer:
        return "merchant_on_behalf"
    return "vera"


def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: dict | None = None,
) -> dict:
    """
    Compose a WhatsApp message from 4 contexts.
    Returns a dict with: body, cta, send_as, suppression_key, rationale,
                         template_name, template_params.
    """
    send_as = _determine_send_as(trigger, customer)
    system_prompt = build_system_prompt(category, send_as=send_as)
    user_prompt = build_user_prompt(category, merchant, trigger, customer)

    # First attempt
    raw = _call_llm(system_prompt, user_prompt)
    action = parse_llm_json(raw)

    if action is None:
        # Re-prompt asking for clean JSON
        retry_prompt = (
            f"{user_prompt}\n\n"
            "IMPORTANT: Your previous response was not valid JSON. "
            "Return ONLY a JSON object with keys: body, cta, send_as, "
            "suppression_key, rationale, template_name, template_params. "
            "No markdown, no text outside the JSON."
        )
        raw = _call_llm(system_prompt, retry_prompt)
        action = parse_llm_json(raw)

    if action is None:
        # Hard fallback
        merchant_name = merchant.get("identity", {}).get("owner_first_name", "there")
        return {
            "body": f"Hi {merchant_name}, quick update from Vera — checking in on your business. Want me to run a profile audit?",
            "cta": "binary_yes_no",
            "send_as": send_as,
            "suppression_key": trigger.get("suppression_key", f"fallback:{trigger.get('id')}"),
            "rationale": "Fallback message — LLM composition failed",
            "template_name": "vera_fallback_v1",
            "template_params": [merchant_name],
        }

    # Enforce correct send_as
    action["send_as"] = send_as
    # Enforce suppression_key from trigger
    if not action.get("suppression_key"):
        action["suppression_key"] = trigger.get("suppression_key", "")

    # Validate
    errors = validate_action(action, category)
    if errors:
        # One re-prompt with specific corrections
        correction_prompt = (
            f"{user_prompt}\n\n"
            f"CORRECTION NEEDED: Fix these issues in your response:\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\nReturn corrected JSON only."
        )
        raw2 = _call_llm(system_prompt, correction_prompt)
        action2 = parse_llm_json(raw2)
        if action2:
            action2["send_as"] = send_as
            if not action2.get("suppression_key"):
                action2["suppression_key"] = trigger.get("suppression_key", "")
            action = action2

    # Ensure required fields exist with defaults
    action.setdefault("template_name", f"vera_{trigger.get('kind', 'generic')}_v1")
    action.setdefault("template_params", [])
    action.setdefault("rationale", "Composed from 4 contexts")

    return action


def compose_reply(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: dict | None,
    conversation_history: list[dict],
    merchant_message: str,
    conversation_mode: str = "normal",
) -> dict:
    """
    Compose a reply within an ongoing conversation.
    conversation_mode: "action" (merchant committed) | "normal"
    Returns: {action: send|wait|end, body?, cta?, rationale}
    """
    send_as = _determine_send_as(trigger, customer)
    system_prompt = build_system_prompt(category, send_as=send_as)

    history_str = "\n".join(
        f"[{t.get('from', 'unknown').upper()}]: {t.get('body', '')[:120]}"
        for t in conversation_history[-6:]  # last 6 turns
    )

    mode_instruction = ""
    if conversation_mode == "action":
        mode_instruction = (
            "\nIMPORTANT: The merchant has committed to an action. "
            "DO NOT ask more qualifying questions. "
            "Draft a concrete artifact or confirm the next step immediately."
        )

    reply_prompt = f"""You are continuing an ongoing conversation. The merchant just replied.

CONVERSATION HISTORY (last {min(6, len(conversation_history))} turns):
{history_str}

MERCHANT'S LATEST MESSAGE: "{merchant_message}"
{mode_instruction}

MERCHANT CONTEXT:
- Name: {merchant.get('identity', {}).get('name')}
- Owner: {merchant.get('identity', {}).get('owner_first_name')}
- Languages: {merchant.get('identity', {}).get('languages', ['en'])}

TRIGGER (original reason for conversation):
- Kind: {trigger.get('kind')} | Suppression key: {trigger.get('suppression_key')}

TASK: Respond to the merchant's message. Choose ONE action:

Option A — Send a follow-up message:
{{"action": "send", "body": "<message>", "cta": "<cta_type>", "rationale": "<why>"}}

Option B — Wait before responding (merchant asked for time):
{{"action": "wait", "wait_seconds": <seconds>, "rationale": "<why>"}}

Option C — End the conversation (merchant opted out or conversation complete):
{{"action": "end", "rationale": "<why>"}}

Return ONLY valid JSON with the chosen option. No markdown."""

    raw = _call_llm(system_prompt, reply_prompt)
    result = parse_llm_json(raw)

    if result is None or result.get("action") not in ("send", "wait", "end"):
        # Default: acknowledge and continue
        return {
            "action": "send",
            "body": f"Got it! Let me draft the next step for you to confirm.",
            "cta": "open_ended",
            "rationale": "Fallback reply — parse failed",
        }

    return result
