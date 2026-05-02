"""Debug compose_reply to see what the LLM returns."""
import json
import composer
from pathlib import Path

EXPANDED_DIR = Path("dataset/expanded")
categories = {p.stem: json.loads(p.read_text("utf-8")) for p in (EXPANDED_DIR / "categories").glob("*.json")}
merchants = {p.stem: json.loads(p.read_text("utf-8")) for p in (EXPANDED_DIR / "merchants").glob("*.json")}

m = merchants.get("m_001_drmeera_dentist_delhi", {})
cat = categories.get(m.get("category_slug", ""), {})

from prompts.system_prompt import build_system_prompt
from utils.validators import parse_llm_json

sys_prompt = build_system_prompt(cat, "vera")

history = [
    {"from": "vera", "body": "Dr. Meera, JIDA research digest shows 3-mo fluoride recall cuts caries 38%..."},
    {"from": "merchant", "body": "Ok lets do it. Whats next?"},
]
history_str = "\n".join(
    f"[{t['from'].upper()}]: {t['body'][:120]}" for t in history
)

owner_name = m.get("identity", {}).get("owner_first_name", "")
trigger_kind = "research_digest"
kind_label = trigger_kind.replace("_", " ")

reply_prompt = f"""You are continuing an ongoing conversation AS Vera (magicpin's merchant AI assistant).

CONVERSATION HISTORY (last 2 turns):
{history_str}

MERCHANT'S LATEST MESSAGE: "Ok lets do it. Whats next?"

IMPORTANT: The merchant has committed to action ("Ok lets do it. Whats next?").
DO NOT ask more qualifying questions. DO NOT use generic language like "Got it, let me draft the next step".
Instead, take CONCRETE action specific to the {kind_label}:
- Draft the specific artifact (campaign copy, pricing tiers, offer structure, etc.)
- Or confirm the exact next operational step with specifics (dates, numbers, localities)
- Use the merchant's name ({owner_name}) and reference the specific {kind_label} context.
Be decisive and action-oriented — the merchant wants to see results, not more questions.

MERCHANT CONTEXT:
- Name: {m.get('identity', {}).get('name')}
- Owner: {owner_name}
- Languages: {m.get('identity', {}).get('languages', ['en'])}

TRIGGER (original reason for conversation):
- Kind: {trigger_kind} | Suppression key: research:dentists:2026-W17

TASK: Respond to the merchant's message. Choose ONE action:

Option A — Send a follow-up message:
{{"action": "send", "body": "<message>", "cta": "<cta_type>", "rationale": "<why>"}}

Option B — Wait:
{{"action": "wait", "wait_seconds": <seconds>, "rationale": "<why>"}}

Option C — End:
{{"action": "end", "rationale": "<why>"}}

Return ONLY valid JSON. No markdown. Start with {{ and end with }}."""

raw = composer._call_llm(sys_prompt, reply_prompt)

Path("debug_raw_intent.txt").write_text(raw, encoding="utf-8")
print("RAW LENGTH:", len(raw))

parsed = parse_llm_json(raw)
if parsed:
    print("PARSED OK:", json.dumps(parsed, indent=2, ensure_ascii=False))
else:
    print("PARSE FAILED!")
    print("First 300 chars:", raw[:300])
