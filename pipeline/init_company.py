"""Create the generic directory and contract files for a new company."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def initialize(company):
    if not company or company != company.upper() or not company.isalnum():
        raise ValueError("Company must be an uppercase alphanumeric ticker, e.g. ENGRO")
    normalized = ROOT / "data" / "normalized" / company
    normalized.mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "raw" / company).mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "derived" / company).mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / company).mkdir(parents=True, exist_ok=True)
    facts_path = normalized / "financial_facts.json"
    if not facts_path.exists():
        facts_path.write_text(
            json.dumps({"company_id": company, "currency": "PKR", "facts": []}, indent=2)
            + "\n",
            encoding="utf-8",
        )
    market_path = normalized / "market_data.json"
    if not market_path.exists():
        market_path.write_text(
            json.dumps(
                {
                    "company_id": company,
                    "currency": "PKR",
                    "observations": [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(f"Initialized {company}")
    print(f"Add normalized facts: {facts_path.relative_to(ROOT)}")
    print(f"Add market observations: {market_path.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser(description="Initialize a generic company workspace.")
    parser.add_argument("--company", required=True)
    args = parser.parse_args()
    try:
        initialize(args.company)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
