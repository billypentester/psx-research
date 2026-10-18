import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "data/normalized/FFC/financial_facts.json"

with FACTS_PATH.open() as f:
    data = json.load(f)

facts = data["facts"]
errors = 0
checks = 0

# Check that total assets equal total equity and liabilities
# for each scope and reporting period, using matching units.
for scope in ("standalone", "consolidated"):
    periods = sorted({
        f["period_end"] for f in facts
        if f.get("scope") == scope
        and f.get("metric") in ("total_assets", "total_equity_and_liabilities")
    })

    for period in periods:
        matching = [
            f for f in facts
            if f.get("scope") == scope
            and f.get("period_end") == period
            and f.get("metric") in ("total_assets", "total_equity_and_liabilities")
        ]
        assets = [f for f in matching if f["metric"] == "total_assets"]
        equity_liabilities = [
            f for f in matching if f["metric"] == "total_equity_and_liabilities"
        ]

        if not assets or not equity_liabilities:
            print(f"WARNING: Missing balance-sheet total: {scope} {period}")
            continue

        for a in assets:
            for e in equity_liabilities:
                if a.get("unit") != e.get("unit"):
                    print(f"ERROR: Unit mismatch: {scope} {period}")
                    errors += 1
                    continue

                checks += 1
                if a["value"] != e["value"]:
                    print(
                        f"ERROR: Balance sheet does not reconcile: {scope} {period}: "
                        f"assets={a['value']}, equity_and_liabilities={e['value']}"
                    )
                    errors += 1
                else:
                    print(f"PASS: Balance sheet reconciles: {scope} {period}")

print(f"\nReconciliation checks: {checks}; errors: {errors}")
raise SystemExit(1 if errors else 0)
