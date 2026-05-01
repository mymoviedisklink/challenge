"""
generate_submission.py — Generate submission.jsonl from the 30 test pairs.

Usage:
    python generate_submission.py

Reads:  dataset/expanded/test_pairs.json
Reads:  dataset/expanded/categories/*.json
Reads:  dataset/expanded/merchants/*.json
Reads:  dataset/expanded/customers/*.json
Reads:  dataset/expanded/triggers/*.json
Writes: submission.jsonl  (30 lines, one per test pair)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

EXPANDED_DIR = Path(__file__).parent / "dataset" / "expanded"


def load_all(expanded_dir: Path):
    categories, merchants, customers, triggers = {}, {}, {}, {}

    for f in (expanded_dir / "categories").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        categories[data["slug"]] = data

    for f in (expanded_dir / "merchants").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        merchants[data["merchant_id"]] = data

    for f in (expanded_dir / "customers").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        customers[data["customer_id"]] = data

    for f in (expanded_dir / "triggers").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        triggers[data["id"]] = data

    return categories, merchants, customers, triggers


def main():
    print("Loading expanded dataset...")
    categories, merchants, customers, triggers = load_all(EXPANDED_DIR)

    test_pairs_file = EXPANDED_DIR / "test_pairs.json"
    if not test_pairs_file.exists():
        print(f"ERROR: {test_pairs_file} not found. Run: python dataset/generate_dataset.py first.")
        return

    pairs = json.loads(test_pairs_file.read_text(encoding="utf-8"))["pairs"]
    print(f"Loaded {len(pairs)} test pairs. Composing messages...")

    import composer as c

    output_lines = []
    for i, pair in enumerate(pairs):
        test_id = pair["test_id"]
        trigger_id = pair["trigger_id"]
        merchant_id = pair["merchant_id"]
        customer_id = pair.get("customer_id")

        trigger = triggers.get(trigger_id)
        merchant = merchants.get(merchant_id)
        customer = customers.get(customer_id) if customer_id else None

        if not trigger or not merchant:
            print(f"  [{test_id}] SKIP — missing trigger or merchant")
            continue

        category_slug = merchant.get("category_slug", "")
        category = categories.get(category_slug)
        if not category:
            print(f"  [{test_id}] SKIP — missing category '{category_slug}'")
            continue

        print(f"  [{test_id}] Composing for {merchant_id} / {trigger_id} (kind={trigger.get('kind')})...", end=" ")
        try:
            action = c.compose(category, merchant, trigger, customer)
            line = {
                "test_id": test_id,
                "body": action.get("body", ""),
                "cta": action.get("cta", "open_ended"),
                "send_as": action.get("send_as", "vera"),
                "suppression_key": action.get("suppression_key", trigger.get("suppression_key", "")),
                "rationale": action.get("rationale", ""),
            }
            output_lines.append(json.dumps(line, ensure_ascii=False))
            print(f"OK ({len(action.get('body', ''))} chars)")
        except Exception as e:
            print(f"ERROR: {e}")
            output_lines.append(json.dumps({
                "test_id": test_id,
                "body": f"[ERROR composing for {test_id}]",
                "cta": "none",
                "send_as": "vera",
                "suppression_key": "",
                "rationale": str(e),
            }, ensure_ascii=False))

    out_file = Path(__file__).parent / "submission.jsonl"
    out_file.write_text("\n".join(output_lines), encoding="utf-8")
    print(f"\nDone! Written {len(output_lines)} lines to {out_file}")


if __name__ == "__main__":
    main()
