import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(company):
    facts_path = ROOT / "data" / "normalized" / company / "financial_facts.json"
    with facts_path.open() as f:
        facts = json.load(f)["facts"]
    errors = 0
    checks = 0

# Check that total assets equal total equity and liabilities
# for each scope and reporting period, using matching units.
    scopes = sorted({f.get("scope") for f in facts})
    for scope in scopes:
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
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", default="FFC")
    raise SystemExit(main(parser.parse_args().company))
