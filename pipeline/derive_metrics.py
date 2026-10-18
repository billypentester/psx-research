"""Derive auditable metrics from normalized, verified financial facts."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIED_STATUS = "verified"

METRIC_DEFINITIONS = (
    ("revenue_growth", "net_turnover", "net_turnover", "current / prior - 1"),
    ("gross_margin", "gross_profit", "net_turnover", "gross_profit / net_turnover"),
    ("net_profit_margin", "profit_after_tax", "net_turnover", "profit_after_tax / net_turnover"),
    ("eps_growth", "earnings_per_share", "earnings_per_share", "current / prior - 1"),
    ("asset_growth", "total_assets", "total_assets", "current / prior - 1"),
    (
        "operating_cash_flow_margin",
        "net_cash_from_operating_activities",
        "net_turnover",
        "net_cash_from_operating_activities / net_turnover",
    ),
    (
        "cash_conversion",
        "net_cash_from_operating_activities",
        "profit_after_tax",
        "net_cash_from_operating_activities / profit_after_tax",
    ),
    (
        "asset_turnover",
        "net_turnover",
        "total_assets",
        "net_turnover / average(total_assets)",
    ),
)


def fact_key(fact):
    return (
        fact["metric"],
        fact["scope"],
        fact["period_end"],
        fact["period_type"],
        fact["unit"],
    )


def load_facts(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["company_id"], data["facts"]


def fact_index(facts):
    return {
        (
            fact["metric"],
            fact["scope"],
            fact["period_end"],
            fact["period_type"],
        ): fact
        for fact in facts
    }


def periods_for_scope(facts, scope):
    return sorted(
        {
            (fact["period_end"], fact["period_type"])
            for fact in facts
            if fact["scope"] == scope
        }
    )


def prior_period(periods, period):
    index = periods.index(period)
    return periods[index - 1] if index else None


def input_ref(fact):
    if fact is None:
        return None
    return {
        "metric": fact["metric"],
        "scope": fact["scope"],
        "period_end": fact["period_end"],
        "period_type": fact["period_type"],
        "unit": fact["unit"],
        "fact_key": list(fact_key(fact)),
    }


def calculate(definition, current, prior, index, scope, period):
    name, numerator_metric, denominator_metric, formula = definition
    numerator = index.get(
        (numerator_metric, scope, period[0], period[1])
    )
    denominator = index.get(
        (denominator_metric, scope, period[0], period[1])
    )
    needs_prior = name in {"revenue_growth", "eps_growth", "asset_growth"}
    if needs_prior:
        numerator = index.get(
            (numerator_metric, scope, period[0], period[1])
        )
        prior_numerator = (
            index.get((numerator_metric, scope, prior[0], prior[1]))
            if prior
            else None
        )
        inputs = [input_ref(numerator), input_ref(prior_numerator)]
        if not prior_numerator:
            return missing_result(name, scope, period, formula, inputs, "prior period unavailable")
        if any(not item or item["verification_status"] != VERIFIED_STATUS for item in (numerator, prior_numerator)):
            return missing_result(name, scope, period, formula, inputs, "input is not verified")
        if prior_numerator["value"] == 0:
            return missing_result(name, scope, period, formula, inputs, "prior value is zero")
        value = numerator["value"] / prior_numerator["value"] - 1
        return result(name, value, scope, period, formula, inputs)

    if name == "asset_turnover":
        current_assets = index.get(("total_assets", scope, period[0], period[1]))
        previous_assets = (
            index.get(("total_assets", scope, prior[0], prior[1]))
            if prior
            else None
        )
        inputs = [input_ref(numerator), input_ref(current_assets), input_ref(previous_assets)]
        if not current_assets or not previous_assets:
            return missing_result(name, scope, period, formula, inputs, "two asset periods required")
        if any(item["verification_status"] != VERIFIED_STATUS for item in (numerator, current_assets, previous_assets)):
            return missing_result(name, scope, period, formula, inputs, "input is not verified")
        average_assets = (current_assets["value"] + previous_assets["value"]) / 2
        value = numerator["value"] / average_assets if average_assets else None
    else:
        inputs = [input_ref(numerator), input_ref(denominator)]
        if not numerator or not denominator:
            return missing_result(name, scope, period, formula, inputs, "required input unavailable")
        if any(item["verification_status"] != VERIFIED_STATUS for item in (numerator, denominator)):
            return missing_result(name, scope, period, formula, inputs, "input is not verified")
        if denominator["value"] == 0:
            return missing_result(name, scope, period, formula, inputs, "denominator is zero")
        value = numerator["value"] / denominator["value"]
    return result(name, value, scope, period, formula, inputs)


def result(name, value, scope, period, formula, inputs):
    return {
        "metric": name,
        "scope": scope,
        "period_end": period[0],
        "period_type": period[1],
        "value": value,
        "unit": "ratio",
        "formula": formula,
        "inputs": inputs,
        "classification": "calculated",
        "calculation_status": "calculated",
    }


def missing_result(name, scope, period, formula, inputs, reason):
    item = result(name, None, scope, period, formula, inputs)
    item["classification"] = "missing"
    item["calculation_status"] = "missing"
    item["missing_reason"] = reason
    return item


def derive(data):
    company_id, facts = data
    index = fact_index(facts)
    metrics = []
    for scope in sorted({fact["scope"] for fact in facts}):
        periods = periods_for_scope(facts, scope)
        for period in periods:
            previous = prior_period(periods, period)
            for definition in METRIC_DEFINITIONS:
                metrics.append(
                    calculate(definition, period, previous, index, scope, period)
                )
    return {
        "company_id": company_id,
        "currency": "PKR",
        "source": "data/normalized/{}/financial_facts.json".format(company_id),
        "metrics": metrics,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    args = parser.parse_args()
    facts_path = ROOT / "data" / "normalized" / args.company / "financial_facts.json"
    output_path = ROOT / "data" / "derived" / args.company / "derived_metrics.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(derive(load_facts(facts_path)), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
