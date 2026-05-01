"""
trigger_prompts.py — Per-trigger-kind user prompt builders.
Each function receives the 4 contexts and returns a rich user prompt string.
"""
from __future__ import annotations
import json


def _merchant_summary(merchant: dict, category: dict) -> str:
    identity = merchant.get("identity", {})
    perf = merchant.get("performance", {})
    sub = merchant.get("subscription", {})
    offers = merchant.get("offers", [])
    signals = merchant.get("signals", [])
    hist = merchant.get("conversation_history", [])
    agg = merchant.get("customer_aggregate", {})
    reviews = merchant.get("review_themes", [])

    peer = category.get("peer_stats", {})
    peer_ctr = peer.get("avg_ctr")
    my_ctr = perf.get("ctr")
    ctr_vs_peer = ""
    if peer_ctr and my_ctr:
        diff_pct = round((my_ctr - peer_ctr) / peer_ctr * 100)
        ctr_vs_peer = f" (peer median {peer_ctr:.3f} — {'ABOVE' if my_ctr >= peer_ctr else 'BELOW'} by {abs(diff_pct)}%)"

    active_offers = [o["title"] for o in offers if o.get("status") == "active"]
    last_turn = hist[-1] if hist else None
    last_touch = f"Last Vera message: \"{last_turn['body'][:80]}...\" — engagement: {last_turn.get('engagement', 'unknown')}" if last_turn else "No conversation history"

    review_str = ""
    if reviews:
        review_str = "\nReview themes: " + "; ".join(
            f"{r['theme']}({r['sentiment']}, {r.get('occurrences_30d', '?')}x)" for r in reviews[:3]
        )

    agg_str = ""
    if agg:
        parts = []
        for k, v in agg.items():
            if v is not None:
                parts.append(f"{k}={v}")
        agg_str = "\nCustomer aggregate: " + ", ".join(parts[:6])

    return f"""MERCHANT CONTEXT:
- Name: {identity.get('name')} | Owner: {identity.get('owner_first_name', 'N/A')}
- Location: {identity.get('locality')}, {identity.get('city')}
- Languages: {identity.get('languages', ['en'])}
- Verified GBP: {identity.get('verified', False)} | Subscription: {sub.get('status')} ({sub.get('plan')}, {sub.get('days_remaining', 0)} days left)
- Performance (30d): views={perf.get('views')}, calls={perf.get('calls')}, directions={perf.get('directions')}, CTR={my_ctr}{ctr_vs_peer}
- 7d delta: views {perf.get('delta_7d', {}).get('views_pct', 0):+.0%}, calls {perf.get('delta_7d', {}).get('calls_pct', 0):+.0%}
- Active offers: {active_offers if active_offers else 'None'}
- Signals: {signals}
- {last_touch}{agg_str}{review_str}"""


def _category_summary(category: dict) -> str:
    peer = category.get("peer_stats", {})
    digest = category.get("digest", [])
    seasonal = category.get("seasonal_beats", [])
    trends = category.get("trend_signals", [])

    digest_str = "\n".join(
        f"  [{d.get('kind','').upper()}] {d.get('title')} — Source: {d.get('source','')}. {d.get('summary','')[:120]}"
        for d in digest[:4]
    )
    seasonal_str = " | ".join(f"{s['month_range']}: {s['note']}" for s in seasonal[:3])
    trends_str = ", ".join(f"{t['query']} +{int(t['delta_yoy']*100)}% YoY" for t in trends[:3])

    return f"""CATEGORY CONTEXT ({category.get('display_name', category.get('slug'))}):
- Peer stats: avg_ctr={peer.get('avg_ctr')}, avg_rating={peer.get('avg_rating')}, avg_reviews={peer.get('avg_review_count')}, retention={peer.get('retention_6mo_pct') or peer.get('retention_3mo_pct') or peer.get('retention_30d_pct')}
- This week's digest:
{digest_str}
- Seasonal beats: {seasonal_str}
- Trending searches: {trends_str}"""


def _customer_summary(customer: dict) -> str:
    if not customer:
        return "CUSTOMER: None (merchant-facing message)"
    identity = customer.get("identity", {})
    rel = customer.get("relationship", {})
    prefs = customer.get("preferences", {})
    consent = customer.get("consent", {})
    return f"""CUSTOMER CONTEXT:
- Name: {identity.get('name')} | Language: {identity.get('language_pref')} | Age: {identity.get('age_band')}
- State: {customer.get('state')} | Visits: {rel.get('visits_total')} | Last visit: {rel.get('last_visit')}
- Services received: {rel.get('services_received', [])[:4]}
- Preferences: {prefs.get('preferred_slots')}, channel={prefs.get('channel')}
- Consent scope: {consent.get('scope', [])}"""


def _trigger_summary(trigger: dict) -> str:
    return f"""TRIGGER:
- ID: {trigger.get('id')} | Kind: {trigger.get('kind')} | Source: {trigger.get('source')}
- Scope: {trigger.get('scope')} | Urgency: {trigger.get('urgency')}/5
- Payload: {json.dumps(trigger.get('payload', {}), ensure_ascii=False)[:300]}
- Suppression key: {trigger.get('suppression_key')}
- Expires: {trigger.get('expires_at')}"""


# ─── Per-kind prompt builders ────────────────────────────────────────────────

def prompt_research_digest(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    top_item_id = payload.get("top_item_id", "")
    digest_items = category.get("digest", [])
    top_item = next((d for d in digest_items if d.get("id") == top_item_id), digest_items[0] if digest_items else {})

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

RELEVANT DIGEST ITEM:
Title: {top_item.get('title')}
Source: {top_item.get('source')}
Trial N: {top_item.get('trial_n', 'N/A')} | Patient segment: {top_item.get('patient_segment', 'general')}
Summary: {top_item.get('summary', '')}
Actionable: {top_item.get('actionable', '')}

TASK: Compose a merchant-facing message using the research digest as the hook.
- Use the specific trial numbers and source citation (e.g., "JIDA Oct 2026 p.14")
- Anchor to THIS merchant's patient cohort (check customer_aggregate signals)
- Offer to pull the abstract + draft patient-education content
- End with open_ended CTA (not binary — this is a curiosity/knowledge trigger)
- send_as: vera"""


def prompt_recall_due(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    slots = payload.get("available_slots", [])
    slot_str = " ya ".join(s.get("label", "") for s in slots[:2]) if slots else "available slots"

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

{_customer_summary(customer)}

TASK: Compose a customer-facing recall reminder.
- Service due: {payload.get('service_due')} | Last visit: {payload.get('last_service_date')} | Due: {payload.get('due_date')}
- Available slots: {slot_str}
- send_as: merchant_on_behalf (message comes FROM the merchant's number, TO the customer)
- Honor customer language preference exactly ({customer.get('identity', {}).get('language_pref') if customer else 'en'})
- Honor preferred time slot ({customer.get('preferences', {}).get('preferred_slots') if customer else 'any'})
- Include the active offer price from merchant offers
- CTA: multi_choice_slot (Reply 1 for first slot, 2 for second, or suggest a time)"""


def prompt_perf_dip(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "views")
    delta = payload.get("delta_pct", -0.2)
    baseline = payload.get("vs_baseline", "N/A")
    is_seasonal = payload.get("is_expected_seasonal", False)

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a merchant-facing performance dip alert.
- Metric: {metric} dropped {abs(delta):.0%} over 7d (baseline: {baseline})
- Seasonal dip: {'YES — this is a normal seasonal pattern, reframe as opportunity' if is_seasonal else 'NO — unexpected drop, investigate'}
- Compare to peer stats to give context
- Offer a specific, actionable remedy (post, offer, etc.)
- CTA: binary_yes_no ("Want me to draft X?")
- send_as: vera"""


def prompt_perf_spike(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "views")
    delta = payload.get("delta_pct", 0.2)
    driver = payload.get("likely_driver", "")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a merchant-facing performance spike acknowledgment.
- Metric: {metric} spiked +{abs(delta):.0%} over 7d
- Likely driver: {driver}
- Celebrate the win with specific numbers
- Convert momentum into next action (new post, offer activation, etc.)
- CTA: binary_yes_no
- send_as: vera"""


def prompt_renewal_due(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    days = payload.get("days_remaining", merchant.get("subscription", {}).get("days_remaining", 14))
    plan = payload.get("plan", merchant.get("subscription", {}).get("plan", "Pro"))
    amount = payload.get("renewal_amount")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a renewal reminder.
- Days remaining: {days} | Plan: {plan}{' | Renewal amount: ₹' + str(amount) if amount else ''}
- Frame in terms of VALUE at stake — what happens to their profile, leads, visibility if they don't renew
- Use their actual performance numbers to anchor the value
- Urgency without panic (peer merchant tone)
- CTA: binary_yes_no ("Reply YES to renew")
- send_as: vera"""


def prompt_winback(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    days_expired = payload.get("days_since_expiry", 30)
    perf_dip = payload.get("perf_dip_pct", -0.2)
    lapsed_customers = payload.get("lapsed_customers_added_since_expiry", 0)

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a winback message for a lapsed merchant (subscription expired {days_expired} days ago).
- Their performance has dropped {abs(perf_dip):.0%} since expiry
- {lapsed_customers} additional customers have lapsed since expiry
- No-shame tone — acknowledge the gap, focus on what's possible now
- Offer a specific immediate action to restart
- CTA: binary_yes_no
- send_as: vera"""


def prompt_festival(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    festival = payload.get("festival", "upcoming festival")
    days_until = payload.get("days_until", 30)
    date = payload.get("date", "")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a festival-opportunity message.
- Festival: {festival} | Date: {date} | Days until: {days_until}
- Tie the festival to a category-specific offer (check offer_catalog + active offers)
- Be specific about what action to take now (post, campaign, etc.)
- Avoid generic "Happy Diwali" — focus on business opportunity
- CTA: binary_yes_no or open_ended depending on urgency
- send_as: vera"""


def prompt_competitor_opened(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    comp_name = payload.get("competitor_name", "a new competitor")
    dist_km = payload.get("distance_km", "nearby")
    their_offer = payload.get("their_offer", "unknown offer")
    opened = payload.get("opened_date", "recently")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a competitive intelligence message.
- Competitor: {comp_name} opened {dist_km}km away on {opened}
- Their offer: {their_offer}
- Frame as intelligence, not alarm — voyeur curiosity hook
- Highlight what THIS merchant has that the competitor lacks (rating, reviews, established status)
- Suggest a pre-emptive action (offer activation, GBP post, etc.)
- CTA: binary_yes_no or open_ended
- send_as: vera"""


def prompt_review_theme(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    theme = payload.get("theme", "service quality")
    count = payload.get("occurrences_30d", 3)
    trend = payload.get("trend", "rising")
    quote = payload.get("common_quote", "")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a review-pattern alert.
- Emerging theme: "{theme}" | Count: {count} reviews in 30d | Trend: {trend}
- Common quote: "{quote}"
- Deliver the insight as a peer observation, not a criticism
- Offer to draft a response template or operational fix
- CTA: binary_yes_no
- send_as: vera"""


def prompt_milestone(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    metric = payload.get("metric", "reviews")
    value_now = payload.get("value_now", 0)
    milestone = payload.get("milestone_value", 0)
    imminent = payload.get("is_imminent", False)

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a milestone celebration/anticipation message.
- Metric: {metric} | Current: {value_now} | Milestone: {milestone} | Imminent: {imminent}
- Celebrate the achievement with social proof framing
- Turn into a momentum play — what's the next action to capitalize?
- CTA: open_ended or binary_yes_no
- send_as: vera"""


def prompt_dormant(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    days_dormant = payload.get("days_since_last_merchant_message", 14)
    last_topic = payload.get("last_topic", "")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Re-engage a dormant merchant (no reply in {days_dormant} days).
- Last topic: {last_topic}
- Do NOT repeat the same topic or message
- Use a fresh angle — pick the highest-relevance digest item or a curiosity-ask
- Low-friction opener — question or insight, not a task
- CTA: open_ended
- send_as: vera"""


def prompt_curious_ask(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    ask_template = payload.get("ask_template", "what_service_in_demand_this_week")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose a curiosity-ask message to drive engagement.
- Ask template: {ask_template}
- This is a "asking the merchant" lever — low commitment, high engagement
- Offer a concrete deliverable for their answer (Google post, WhatsApp reply draft, etc.)
- The ask should feel like genuine curiosity, not a survey
- CTA: open_ended
- send_as: vera"""


def prompt_supply_alert(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    alert_id = payload.get("alert_id", "")
    molecule = payload.get("molecule", "medication")
    batches = payload.get("affected_batches", [])
    manufacturer = payload.get("manufacturer", "Manufacturer")

    digest = category.get("digest", [])
    alert_item = next((d for d in digest if d.get("id") == alert_id), {})

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

ALERT DETAILS:
{json.dumps(alert_item, ensure_ascii=False)[:400] if alert_item else f'Molecule: {molecule}, Batches: {batches}, Manufacturer: {manufacturer}'}

TASK: Compose an urgent supply alert message.
- This is urgency=5 — the merchant MUST know now
- Include batch numbers if available
- Derive how many of their chronic customers may be affected (from customer_aggregate)
- Offer complete workflow: WhatsApp to affected customers + replacement pickup
- CTA: binary_yes_no
- send_as: vera"""


def prompt_chronic_refill(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    molecules = payload.get("molecule_list", [])
    runs_out = payload.get("stock_runs_out_iso", "")
    delivery_saved = payload.get("delivery_address_saved", False)

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

{_customer_summary(customer)}

TASK: Compose a chronic refill reminder to the customer (on behalf of pharmacy).
- Molecules: {molecules}
- Stock runs out: {runs_out}
- Delivery address saved: {delivery_saved}
- send_as: merchant_on_behalf
- Language: {customer.get('identity', {}).get('language_pref', 'hi') if customer else 'hi'}
- Include total bill + savings (senior discount if applicable)
- Offer delivery confirmation with single CONFIRM CTA
- CTA: binary_confirm_cancel"""


def prompt_regulation_change(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    deadline = payload.get("deadline_iso", "")
    item_id = payload.get("top_item_id", "")

    digest = category.get("digest", [])
    reg_item = next((d for d in digest if d.get("id") == item_id), digest[0] if digest else {})

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

REGULATION ITEM:
{json.dumps(reg_item, ensure_ascii=False)[:400] if reg_item else 'See trigger payload'}
Deadline: {deadline}

TASK: Compose a compliance alert.
- Communicate the change clearly without causing panic
- Give the specific deadline and what changes
- Offer an audit action or checklist
- CTA: binary_yes_no ("Want me to walk you through the audit?")
- send_as: vera"""


def prompt_cde_opportunity(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    credits = payload.get("credits", 0)
    fee = payload.get("fee", "")
    item_id = payload.get("digest_item_id", "")

    digest = category.get("digest", [])
    cde_item = next((d for d in digest if d.get("id") == item_id), digest[0] if digest else {})

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

CDE ITEM:
{json.dumps(cde_item, ensure_ascii=False)[:400] if cde_item else 'See trigger payload'}
Credits: {credits} | Fee: {fee}

TASK: Compose a professional development / CDE opportunity message.
- Frame as a peer tip ("IDA Delhi webinar tonight, thought you'd want to know")
- Include date, credits, fee, speaker if available
- Low-urgency but timely
- CTA: binary_yes_no
- send_as: vera"""


def prompt_customer_lapsed(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    days_since = payload.get("days_since_last_visit", 60)
    prev_focus = payload.get("previous_focus", "")
    prev_months = payload.get("previous_membership_months", 0)

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

{_customer_summary(customer)}

TASK: Compose a lapsed customer winback message.
- Days since last visit: {days_since}
- Previous focus: {prev_focus}
- Previous membership: {prev_months} months
- send_as: merchant_on_behalf
- NO guilt or pressure — warm, no-judgment tone
- Reference a new offering that matches their previous goal
- Low-commitment CTA: free trial, no auto-charge
- CTA: binary_yes_no"""


def prompt_trial_followup(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    trial_date = payload.get("trial_date", "")
    next_sessions = payload.get("next_session_options", [])
    slot = next_sessions[0].get("label", "upcoming session") if next_sessions else "next available slot"

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

{_customer_summary(customer)}

TASK: Compose a trial followup message.
- Trial date: {trial_date}
- Next session option: {slot}
- send_as: merchant_on_behalf
- Warm, encouraging — "how was the trial?" + next step
- No hard sell — ease them in with a specific next date
- CTA: binary_yes_no"""


def prompt_active_planning(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    intent_topic = payload.get("intent_topic", "new program")
    last_msg = payload.get("merchant_last_message", "")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: The merchant has expressed a planning intent — they want to build something.
- Intent topic: {intent_topic}
- Their last message: "{last_msg}"
- DO NOT ask more qualifying questions — they've committed
- Draft a COMPLETE concrete artifact (pricing tiers, program structure, offer copy, etc.)
- Be specific: use locality names, realistic pricing, operational details
- Offer the next logistical step (post it? send to customers? etc.)
- CTA: binary_yes_no or binary_confirm_cancel
- send_as: vera"""


def prompt_gbp_unverified(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    uplift = payload.get("estimated_uplift_pct", 0.3)
    path = payload.get("verification_path", "postcard or phone call")

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Nudge an unverified merchant to verify their Google Business Profile.
- Estimated uplift from verification: +{uplift:.0%} visibility
- Verification path: {path}
- Frame as a quick win — minimal effort, significant payoff
- CTA: binary_yes_no
- send_as: vera"""


def prompt_ipl_match(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})
    match = payload.get("match", "IPL match")
    venue = payload.get("venue", "")
    match_time = payload.get("match_time_iso", "")
    is_weeknight = payload.get("is_weeknight", True)

    # Key insight from category digest: Saturday IPL = -12% covers; weeknight = +18%
    insight = (
        "IMPORTANT: Saturday IPL matches shift orders to home-watch parties (restaurant covers -12% vs avg). "
        "Recommend delivery-only promotion, NOT a dine-in match-night promo."
        if not is_weeknight else
        "Weeknight IPL matches drive +18% restaurant covers — push match-night combo."
    )

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

TASK: Compose an IPL match-day message.
- Match: {match} at {venue}, {match_time}
- Is weeknight: {is_weeknight}
- CRITICAL INSIGHT: {insight}
- Reference their active offers if relevant
- Be contrarian and data-informed (this is a high-signal message)
- CTA: binary_yes_no
- send_as: vera"""


def prompt_appointment_tomorrow(category, merchant, trigger, customer):
    payload = trigger.get("payload", {})

    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

{_customer_summary(customer)}

TASK: Compose an appointment reminder (1 day before).
- send_as: merchant_on_behalf
- Keep it brief and friendly — just the essentials (date, time, address hint)
- Offer easy reschedule path
- CTA: binary_confirm_cancel"""


# ─── Dispatcher ──────────────────────────────────────────────────────────────

KIND_TO_BUILDER = {
    "research_digest": prompt_research_digest,
    "recall_due": prompt_recall_due,
    "perf_dip": prompt_perf_dip,
    "seasonal_perf_dip": prompt_perf_dip,
    "perf_spike": prompt_perf_spike,
    "renewal_due": prompt_renewal_due,
    "winback_eligible": prompt_winback,
    "festival_upcoming": prompt_festival,
    "competitor_opened": prompt_competitor_opened,
    "review_theme_emerged": prompt_review_theme,
    "milestone_reached": prompt_milestone,
    "dormant_with_vera": prompt_dormant,
    "curious_ask_due": prompt_curious_ask,
    "supply_alert": prompt_supply_alert,
    "chronic_refill_due": prompt_chronic_refill,
    "regulation_change": prompt_regulation_change,
    "cde_opportunity": prompt_cde_opportunity,
    "customer_lapsed_soft": prompt_customer_lapsed,
    "customer_lapsed_hard": prompt_customer_lapsed,
    "trial_followup": prompt_trial_followup,
    "active_planning_intent": prompt_active_planning,
    "gbp_unverified": prompt_gbp_unverified,
    "ipl_match_today": prompt_ipl_match,
    "appointment_tomorrow": prompt_appointment_tomorrow,
    "wedding_package_followup": prompt_trial_followup,
    "category_seasonal": prompt_festival,
}


def build_user_prompt(category: dict, merchant: dict, trigger: dict, customer: dict | None) -> str:
    """Dispatch to the right per-kind prompt builder."""
    kind = trigger.get("kind", "")
    builder = KIND_TO_BUILDER.get(kind)
    if builder:
        return builder(category, merchant, trigger, customer)
    # Fallback generic prompt
    return f"""{_category_summary(category)}

{_merchant_summary(merchant, category)}

{_trigger_summary(trigger)}

{_customer_summary(customer)}

TASK: Compose an engaging WhatsApp message based on the trigger above.
Determine send_as from the trigger scope (merchant→vera, customer→merchant_on_behalf).
Use the most relevant compulsion lever from the category voice.
CTA: binary_yes_no or open_ended as appropriate."""
