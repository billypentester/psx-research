"""Run the deterministic fundamental-analysis pipeline for any company."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .derive_metrics import derive, load_facts
except ImportError:
    from derive_metrics import derive, load_facts


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "source_registry.json"


def load_json(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def latest_period(facts):
    periods = sorted(
        {(fact["period_end"], fact["period_type"]) for fact in facts}
    )
    return periods[-1] if periods else (None, None)


def verified_facts(facts, period_end=None):
    return [
        fact for fact in facts
        if fact["verification_status"] == "verified"
        and (period_end is None or fact["period_end"] == period_end)
    ]


def source_summary(company, facts, registry):
    source_ids = {fact["source_id"] for fact in facts}
    sources = [
        source for source in registry
        if source.get("company_id") == company
        and source.get("source_id") in source_ids
    ]
    return [
        {
            "source_id": source["source_id"],
            "provider": source.get("provider") or "registered",
            "source_type": source["source_type"],
            "title": source["title"],
            "url": source.get("url"),
            "retrieved_at": source["retrieved_at"],
            "local_path": source["local_path"],
        }
        for source in sources
    ]


def report_data(company, facts_data, derived_data, registry):
    facts = facts_data[1]
    period_end, period_type = latest_period(facts)
    latest_verified = verified_facts(facts, period_end)
    latest_metrics = [
        metric for metric in derived_data["metrics"]
        if metric["period_end"] == period_end
        and metric["calculation_status"] == "calculated"
    ]
    missing_metrics = [
        metric for metric in derived_data["metrics"]
        if metric["period_end"] == period_end
        and metric["calculation_status"] == "missing"
    ]
    market_data_path = ROOT / "data" / "normalized" / company / "market_data.json"
    market_data = load_json(market_data_path, None)
    has_market_data = bool(
        market_data and market_data.get("observations")
    )
    gaps = [
        "No normalized market_data.json was found; current price, market cap, valuation multiples, and dividend yield are unavailable."
    ] if not has_market_data else []
    if market_data is not None and not has_market_data:
        gaps[0] = (
            "market_data.json exists but contains no observations; current price, "
            "market cap, valuation multiples, and dividend yield are unavailable."
        )
    if not any(fact["metric"] == "total_debt" for fact in facts):
        gaps.append("Debt and leverage metrics are not present in the normalized facts.")
    if not any(fact["metric"] == "dividend_per_share" for fact in facts):
        gaps.append("Dividend history is not present in the normalized facts.")
    if not any(fact["metric"] == "segment_revenue" for fact in facts):
        gaps.append("Segment-level operating data is not present in the normalized facts.")
    confidence = "high" if latest_verified and not missing_metrics else "medium"
    if not latest_verified or len(gaps) >= 3:
        confidence = "low"
    return {
        "company_id": company,
        "status": "ready" if facts else "data_unavailable",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_period": {
            "period_end": period_end,
            "period_type": period_type,
            "verified_fact_count": len(latest_verified),
        },
        "financial_quality": {
            "total_fact_count": len(facts),
            "verified_fact_count": len(verified_facts(facts)),
            "unverified_fact_count": len(facts) - len(verified_facts(facts)),
            "source_count": len(source_summary(company, facts, registry)),
        },
        "derived_metrics": latest_metrics,
        "missing_calculations": missing_metrics,
        "market_data": market_data,
        "valuation": {
            "status": "unavailable" if not has_market_data else "inputs_available",
            "required_inputs": [
                "current_price",
                "shares_outstanding",
                "earnings_per_share",
                "dividend_per_share",
            ],
        },
        "gaps": gaps,
        "next_steps": (
            [
                f"Collect public source files for {company}.",
                f"Normalize them into data/normalized/{company}/financial_facts.json.",
                f"Normalize price observations into data/normalized/{company}/market_data.json.",
                "Review imported facts and change verification_status to verified only after source checking.",
            ]
            if not facts
            else []
        ),
        "confidence": confidence,
        "sources": source_summary(company, facts, registry),
    }


def metric_text(metric):
    if metric["value"] is None:
        return f"- **{metric['metric']}**: unavailable ({metric.get('missing_reason', 'missing input')})"
    return f"- **{metric['metric']}**: {metric['value']:.4f} (`{metric['formula']}`)"


def render_markdown(data):
    latest = data["latest_period"]
    lines = [
        f"# {data['company_id']} Fundamental Analysis",
        "",
        f"Generated: `{data['generated_at']}`  ",
        f"Latest normalized period: `{latest['period_end']}` ({latest['period_type']})  ",
        f"Research confidence: **{data['confidence']}**",
        f"Data status: **{data['status']}**",
        "",
        "> This report is evidence-led and is not investment advice. Missing inputs are shown explicitly.",
        "",
        "## Financial quality",
        "",
        f"- Normalized facts: **{data['financial_quality']['total_fact_count']}**",
        f"- Verified facts: **{data['financial_quality']['verified_fact_count']}**",
        f"- Sources used: **{data['financial_quality']['source_count']}**",
        "",
        "## Latest derived metrics",
        "",
    ]
    lines.extend(metric_text(metric) for metric in data["derived_metrics"])
    if data["missing_calculations"]:
        lines.extend(["", "## Missing calculations", ""])
        lines.extend(metric_text(metric) for metric in data["missing_calculations"])
    lines.extend(["", "## Valuation readiness", ""])
    lines.append(f"- Status: **{data['valuation']['status']}**")
    lines.append("- Required inputs: " + ", ".join(data["valuation"]["required_inputs"]))
    lines.extend(["", "## Data gaps", ""])
    lines.extend(f"- {gap}" for gap in data["gaps"])
    if data["next_steps"]:
        lines.extend(["", "## Next steps", ""])
        lines.extend(f"{index}. {step}" for index, step in enumerate(data["next_steps"], 1))
    lines.extend(["", "## Sources", ""])
    for source in data["sources"]:
        lines.append(
            f"- `{source['source_id']}` — {source['provider']} — "
            f"[{source['title']}]({source['url'] or source['local_path']})"
        )
    return "\n".join(lines) + "\n"


def write_artifacts(company, facts_data, registry):
    derived = derive(facts_data)
    output_dir = ROOT / "reports" / company
    output_dir.mkdir(parents=True, exist_ok=True)
    derived_path = ROOT / "data" / "derived" / company / "derived_metrics.json"
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    derived_path.write_text(json.dumps(derived, indent=2) + "\n", encoding="utf-8")
    data = report_data(company, facts_data, derived, registry)
    (output_dir / "fundamental_analysis.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "fundamental_analysis.md").write_text(
        render_markdown(data), encoding="utf-8"
    )
    context = {
        "company_id": company,
        "purpose": "Evidence package for Hermes fundamental analysis",
        "instructions": [
            "Use only verified facts for material claims.",
            "Cite source_id and source_page for reported facts.",
            "Treat derived metrics as calculations and preserve their formulas.",
            "Do not invent missing market, dividend, debt, segment, or peer data.",
            "Explain all material data gaps and uncertainty.",
            "Do not issue a recommendation when valuation inputs are unavailable.",
        ],
        "latest_period": data["latest_period"],
        "financial_quality": data["financial_quality"],
        "derived_metrics": data["derived_metrics"],
        "market_data": data["market_data"],
        "valuation": data["valuation"],
        "gaps": data["gaps"],
        "sources": data["sources"],
        "artifacts": {
            "financial_facts": f"data/normalized/{company}/financial_facts.json",
            "derived_metrics": f"data/derived/{company}/derived_metrics.json",
            "analysis_json": f"reports/{company}/fundamental_analysis.json",
            "analysis_markdown": f"reports/{company}/fundamental_analysis.md",
        },
    }
    (output_dir / "hermes_context.json").write_text(
        json.dumps(context, indent=2) + "\n", encoding="utf-8"
    )
    return data


def run_validator(script, company):
    command = [sys.executable, str(ROOT / script), "--company", company]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main():
    parser = argparse.ArgumentParser(
        description="Run validation, derivation, and report generation."
    )
    parser.add_argument("--company", required=True)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run financial fact and accounting validators before reporting",
    )
    parser.add_argument(
        "--fetch-discover",
        action="store_true",
        help="Fetch permitted ticker-matching public links before validation",
    )
    parser.add_argument(
        "--url",
        action="append",
        help="Fetch an explicit public URL before validation; repeatable",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Write a data-readiness report even when no facts are loaded",
    )
    args = parser.parse_args()
    if args.fetch_discover or args.url:
        command = [
            sys.executable,
            str(ROOT / "pipeline" / "fetch_sources.py"),
            "--company",
            args.company,
        ]
        if args.fetch_discover:
            command.append("--discover")
        for url in args.url or []:
            command.extend(["--url", url])
        fetch_status = subprocess.run(command, cwd=ROOT, check=False).returncode
        if fetch_status != 0:
            return fetch_status
    facts_path = ROOT / "data" / "normalized" / args.company / "financial_facts.json"
    if not facts_path.is_file():
        parser.error(
            f"Missing normalized facts: {facts_path}. "
            f"Run `python pipeline/init_company.py --company {args.company}` "
            "and then ingest and verify source data."
        )
    if args.validate:
        scripts = [
            "pipeline/validate/validate_financial_facts.py",
            "pipeline/validate/check_reconciliations.py",
            "pipeline/validate/check_cash_flows.py",
        ]
        market_path = ROOT / "data" / "normalized" / args.company / "market_data.json"
        if market_path.exists():
            scripts.append("pipeline/validate/validate_market_data.py")
        statuses = [run_validator(script, args.company) for script in scripts]
        if any(status != 0 for status in statuses):
            return 1
    facts_data = load_facts(facts_path)
    if not facts_data[1] and not args.allow_empty:
        parser.error(
            f"No financial facts loaded for {args.company}. "
            f"Normalize source data into {facts_path.relative_to(ROOT)} first, "
            "or use --allow-empty to create a readiness report."
        )
    registry = load_json(REGISTRY, [])
    data = write_artifacts(args.company, facts_data, registry)
    print(f"Wrote reports/{args.company}/fundamental_analysis.md")
    print(f"Confidence: {data['confidence']}; gaps: {len(data['gaps'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
