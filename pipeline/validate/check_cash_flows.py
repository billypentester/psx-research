import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACTS_PATH = ROOT / "data/normalized/FFC/financial_facts.json"

with FACTS_PATH.open() as f:
    facts = json.load(f)["facts"]

def get(metric, scope, year):
    matches = [
        f for f in facts
        if f["metric"] == metric
        and f["scope"] == scope
        and f["period_end"] == f"{year}-12-31"
        and f["unit"] == "PKR_thousand"
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {metric} fact for {scope} {year}; "
            f"found {len(matches)}"
        )
    return matches[0]["value"]

errors = 0
checks = 0

for scope in ("standalone", "consolidated"):
    for year in (2025, 2024):
        try:
            operating = get("net_cash_from_operating_activities", scope, year)
            investing = get("net_cash_from_investing_activities", scope, year)
            financing = get("net_cash_from_financing_activities", scope, year)
            net_change = get(
                "net_change_in_cash_and_cash_equivalents", scope, year
            )
            beginning = get(
                "cash_and_cash_equivalents_beginning", scope, year
            )
            fx = get("effect_of_exchange_rate_changes", scope, year)
            ending = get("cash_and_cash_equivalents_ending", scope, year)

            merger_matches = [
                f for f in facts
                if f["metric"] == "cash_and_cash_equivalents_acquired_through_merger"
                and f["scope"] == scope
                and f["period_end"] == f"{year}-12-31"
                and f["unit"] == "PKR_thousand"
            ]
            if len(merger_matches) > 1:
                raise ValueError(f"Duplicate merger-cash fact for {scope} {year}")
            merger = merger_matches[0]["value"] if merger_matches else 0

            checks += 1
            calculated_change = operating + investing + financing
            if calculated_change != net_change:
                errors += 1
                print(
                    f"ERROR: Activity totals, {scope} {year}: "
                    f"calculated={calculated_change}, reported={net_change}"
                )
            else:
                print(f"PASS: Activity totals reconcile, {scope} {year}")

            checks += 1
            calculated_ending = beginning + net_change + fx + merger
            if calculated_ending != ending:
                errors += 1
                print(
                    f"ERROR: Cash balance, {scope} {year}: "
                    f"calculated={calculated_ending}, reported={ending}"
                )
            else:
                print(f"PASS: Cash balance reconciles, {scope} {year}")

        except (ValueError, KeyError) as exc:
            errors += 1
            print(f"ERROR: {scope} {year}: {exc}")

print(f"\nCash-flow checks: {checks}; errors: {errors}")
raise SystemExit(1 if errors else 0)
