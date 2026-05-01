"""
bot.py — Vera bot server for the magicpin AI Challenge.

Implements all 5 required endpoints:
  GET  /v1/healthz
  GET  /v1/metadata
  POST /v1/context
  POST /v1/tick
  POST /v1/reply

Run with: uvicorn bot:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Vera Bot", version="1.0.0")
START_TIME = time.time()

# ─── In-memory state ─────────────────────────────────────────────────────────
# (scope, context_id) → {version, payload}
contexts: dict[tuple[str, str], dict] = {}
# conversation_id → list of {from, body} turns
conversations: dict[str, list] = {}
# conversation_id → trigger_id (for lookup in reply handler)
conv_trigger_map: dict[str, str] = {}
# suppression keys that have been used
suppressed_keys: set[str] = set()
# conversation_ids that have been ended
ended_conversations: set[str] = set()

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

# ─── Lazy imports (avoid loading LLM at startup) ─────────────────────────────
_composer = None

def get_composer():
    global _composer
    if _composer is None:
        import composer as c
        _composer = c
    return _composer


# ─── Endpoint schemas ────────────────────────────────────────────────────────

class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/v1/healthz")
async def healthz():
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _) in contexts:
        if scope in counts:
            counts[scope] += 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts,
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Vera Bot",
        "team_members": ["Anupam"],
        "model": os.getenv("LLM_MODEL", "Qwen3.6-35B-A3B"),
        "approach": (
            "FastAPI bot with trigger-kind dispatch: 20+ specialized prompt templates "
            "per trigger kind (research_digest, recall_due, perf_dip, etc.). "
            "Auto-reply detection, intent transition handling, post-LLM validation."
        ),
        "contact_email": "anupam@example.com",
        "version": "1.0.0",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/context")
async def push_context(body: ContextBody):
    if body.scope not in VALID_SCOPES:
        return {"accepted": False, "reason": "invalid_scope", "details": f"scope must be one of {VALID_SCOPES}"}

    key = (body.scope, body.context_id)
    current = contexts.get(key)

    if current and current["version"] >= body.version:
        return {
            "accepted": False,
            "reason": "stale_version",
            "current_version": current["version"],
        }

    contexts[key] = {"version": body.version, "payload": body.payload}
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/tick")
async def tick(body: TickBody):
    available_triggers = body.available_triggers
    if not available_triggers:
        return {"actions": []}

    c = get_composer()

    async def process_trigger(trigger_id: str):
        # Skip if suppressed or no context
        trg_entry = contexts.get(("trigger", trigger_id))
        if not trg_entry:
            return None
        trg = trg_entry["payload"]

        sup_key = trg.get("suppression_key", "")
        if sup_key and sup_key in suppressed_keys:
            return None

        merchant_id = trg.get("merchant_id")
        if not merchant_id:
            return None

        merchant_entry = contexts.get(("merchant", merchant_id))
        if not merchant_entry:
            return None
        merchant = merchant_entry["payload"]

        category_slug = merchant.get("category_slug", "")
        category_entry = contexts.get(("category", category_slug))
        if not category_entry:
            return None
        category = category_entry["payload"]

        customer_id = trg.get("customer_id")
        customer = None
        if customer_id:
            cust_entry = contexts.get(("customer", customer_id))
            if cust_entry:
                customer = cust_entry["payload"]

        # Build conversation_id
        conv_id = f"conv_{merchant_id}_{trigger_id}"

        # Don't resend to ended conversations
        if conv_id in ended_conversations:
            return None

        # Compose message in executor to avoid blocking
        loop = asyncio.get_event_loop()
        try:
            action = await loop.run_in_executor(
                None,
                lambda: c.compose(category, merchant, trg, customer)
            )
        except Exception as e:
            print(f"[COMPOSE ERROR] {trigger_id}: {e}")
            return None

        if not action or not action.get("body"):
            return None

        # Mark suppression
        if sup_key:
            suppressed_keys.add(sup_key)

        # Store Vera's first message in conversation history
        conversations.setdefault(conv_id, []).append({
            "from": "vera",
            "body": action["body"],
        })
        conv_trigger_map[conv_id] = trigger_id

        send_as = action.get("send_as", "vera")
        # Build template params if missing
        template_params = action.get("template_params", [])
        if not template_params:
            owner = merchant.get("identity", {}).get("owner_first_name", "")
            template_params = [owner, action.get("body", "")[:100], ""]

        return {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": send_as,
            "trigger_id": trigger_id,
            "template_name": action.get("template_name", f"vera_{trg.get('kind', 'generic')}_v1"),
            "template_params": template_params,
            "body": action["body"],
            "cta": action.get("cta", "open_ended"),
            "suppression_key": sup_key,
            "rationale": action.get("rationale", ""),
        }

    # Process triggers in parallel (max 5 concurrent)
    semaphore = asyncio.Semaphore(5)

    async def process_with_semaphore(tid):
        async with semaphore:
            return await process_trigger(tid)

    results = await asyncio.gather(
        *[process_with_semaphore(tid) for tid in available_triggers],
        return_exceptions=True
    )

    actions = [r for r in results if r and isinstance(r, dict)]
    return {"actions": actions}


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    import conversation_handlers as ch

    result = ch.handle_reply(
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id or "",
        message=body.message,
        turn_number=body.turn_number,
        conversations=conversations,
        contexts=contexts,
        ended_conversations=ended_conversations,
        suppressed_keys=suppressed_keys,
        composer_module=get_composer(),
    )
    return result


@app.post("/v1/teardown")
async def teardown():
    """Clear all in-memory state at end of test."""
    contexts.clear()
    conversations.clear()
    conv_trigger_map.clear()
    suppressed_keys.clear()
    ended_conversations.clear()
    return {"status": "torn_down"}


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=8080, reload=False)
