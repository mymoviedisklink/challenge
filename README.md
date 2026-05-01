# Vera Bot — magicpin AI Challenge Submission

## Approach

**Architecture**: FastAPI HTTP server implementing all 5 required endpoints (`healthz`, `metadata`, `context`, `tick`, `reply`).

**LLM**: `Qwen3.6-35B-A3B` accessed via OpenAI-compatible API at a local endpoint. Temperature=0 for determinism.

**Core intelligence — Trigger-Kind Dispatch**:
The single most impactful design decision is that each of 20+ trigger kinds gets a specialized prompt template rather than a generic "compose a message" prompt. For example:
- `research_digest` → source-citation framing (JIDA p.14, trial N, patient segment match)
- `recall_due` → slot-offering with language-mix and customer preference honoring
- `ipl_match_today` → contrarian data-driven advice (Saturday IPL = -12% covers; weeknight = +18%)
- `supply_alert` → urgency + batch-numbers + derived affected-customer count
- `active_planning_intent` → draft complete artifact immediately (no more qualifying questions)

**Multi-turn intelligence**:
- **Auto-reply detection**: pattern matching + repeat detection → escalating response (nudge → wait 24h → end)
- **Intent transition**: commitment signals ("let's do it", "haan karo") switch from qualifying to action mode immediately
- **Hostile handling**: graceful exit on opt-out signals
- **Out-of-scope**: politely decline + redirect back to trigger topic

**Context enrichment**:
At composition time, peer benchmarks are derived (merchant CTR vs category peer median), customer aggregate insights are surfaced, and conversation history is injected into the prompt.

**Post-LLM validation**:
Output is validated for taboo words, URL presence, CTA shape, and required fields. Failed validation triggers a single re-prompt with specific corrections.

## Tradeoffs

- **Local model vs frontier**: Using a local Qwen3.6-35B-A3B instead of GPT-4o/Claude gives zero API cost and fast inference, but may produce slightly less polished copy on edge cases. The trigger-kind dispatch compensates by giving the model rich, structured context.
- **In-memory state**: Adequate for the 60-minute test window; would need Redis for production.
- **Parallel tick processing**: Up to 5 concurrent LLM calls per tick to stay within the 30-second budget.

## What Additional Context Would Have Helped

1. **Real merchant catalog prices** for the expanded dataset (generated merchants have empty offers lists — the bot falls back to category offer_catalog defaults)
2. **Historical conversation patterns** per merchant to detect dormancy more accurately
3. **Actual slot availability** for customer-facing recall messages (we use the trigger payload's `available_slots` field, but not all triggers have this)
4. **Language detection confidence scores** — knowing whether a merchant has replied in Hindi vs English in the past would sharpen the code-mix calibration

## Files

| File | Purpose |
|------|---------|
| `bot.py` | FastAPI server (5 endpoints) |
| `composer.py` | LLM composition engine |
| `conversation_handlers.py` | Multi-turn reply logic |
| `prompts/system_prompt.py` | Category-voice-aware system prompt |
| `prompts/trigger_prompts.py` | 20+ per-trigger-kind prompt templates |
| `utils/auto_reply_detector.py` | WhatsApp auto-reply detection |
| `utils/intent_detector.py` | Intent transition classification |
| `utils/validators.py` | Post-LLM output validation |
| `generate_submission.py` | Generates `submission.jsonl` |
| `submission.jsonl` | 30 composed messages (one per test pair) |
