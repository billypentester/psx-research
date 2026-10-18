import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def get(facts, metric, scope, period_end):
    matches = [
        f for f in facts
        if f["metric"] == metric
        and f["scope"] == scope
        and f["period_end"] == period_end
        and f["unit"] == "PKR_thousand"
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {metric} fact for {scope} {period_end}; "
            f"found {len(matches)}"
        )
    return matches[0]["value"]

def main(company):
    facts_path = ROOT / "data" / "normalized" / company / "financial_facts.json"
    with facts_path.open() as f:
        facts = json.load(f)["facts"]
    errors = 0
    checks = 0
    scopes = sorted({f["scope"] for f in facts})
    periods = sorted({
        f["period_end"] for f in facts
        if f["metric"] == "net_change_in_cash_and_cash_equivalents"
    })
    for scope in scopes:
        for period_end in periods:
            label = f"{scope} {period_end}"
            try:
                operating = get(facts, "net_cash_from_operating_activities", scope, period_end)
                investing = get(facts, "net_cash_from_investing_activities", scope, period_end)
                financing = get(facts, "net_cash_from_financing_activities", scope, period_end)
                net_change = get(
                    facts, "net_change_in_cash_and_cash_equivalents", scope, period_end
                )
                beginning = get(facts, "cash_and_cash_equivalents_beginning", scope, period_end)
                fx = get(facts, "effect_of_exchange_rate_changes", scope, period_end)
                ending = get(facts, "cash_and_cash_equivalents_ending", scope, period_end)

                merger_matches = [
                    f for f in facts
                    if f["metric"] == "cash_and_cash_equivalents_acquired_through_merger"
                    and f["scope"] == scope
                    and f["period_end"] == period_end
                    and f["unit"] == "PKR_thousand"
                ]
                if len(merger_matches) > 1:
                    raise ValueError(f"Duplicate merger-cash fact for {label}")
                merger = merger_matches[0]["value"] if merger_matches else 0

                checks += 1
                calculated_change = operating + investing + financing
                if calculated_change != net_change:
                    errors += 1
                    print(
                        f"ERROR: Activity totals, {label}: "
                        f"calculated={calculated_change}, reported={net_change}"
                    )
                else:
                    print(f"PASS: Activity totals reconcile, {label}")

                checks += 1
                calculated_ending = beginning + net_change + fx + merger
                if calculated_ending != ending:
                    errors += 1
                    print(
                        f"ERROR: Cash balance, {label}: "
                        f"calculated={calculated_ending}, reported={ending}"
                    )
                else:
                    print(f"PASS: Cash balance reconciles, {label}")

            except (ValueError, KeyError) as exc:
                errors += 1
                print(f"ERROR: {label}: {exc}")

    print(f"\nCash-flow checks: {checks}; errors: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", default="FFC")
    raise SystemExit(main(parser.parse_args().company))
