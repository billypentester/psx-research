"""Normalize structured public-source responses into generic research data.

The importer accepts explicit field mappings. It never infers a financial
meaning from an arbitrary column name without a configured mapping.
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

try:
    from .register_source import load_registry
except ImportError:
    from register_source import load_registry


ROOT = Path(__file__).resolve().parents[1]
MARKET_FIELDS = {
    "observed_at",
    "price",
    "currency",
    "volume",
    "shares_outstanding",
    "market_cap",
    "dividend_per_share",
}
FINANCIAL_FIELDS = {
    "metric",
    "value",
    "unit",
    "period_end",
    "period_type",
    "scope",
}


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._table = []
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in {"td", "th"}:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def parse_number(value):
    if value is None or str(value).strip() == "":
        return None
    cleaned = str(value).strip().replace(",", "").replace("%", "")
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    number = float(cleaned)
    return -number if negative else number


def read_records(path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        raise ValueError("JSON must be an array or contain a data array")
    if suffix in {".html", ".htm"}:
        parser = TableParser()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        records = []
        for table in parser.tables:
            if len(table) < 2:
                continue
            headers = [header.strip().lower() for header in table[0]]
            records.extend(dict(zip(headers, row)) for row in table[1:])
        return records
    raise ValueError(f"Unsupported structured input: {path.suffix}")


def source_record(source_id):
    for source in load_registry():
        if source["source_id"] == source_id:
            return source
    raise ValueError(f"Source is not registered: {source_id}")


def normalize_market_data(company, records, mapping, source_id):
    source_record(source_id)
    if "observed_at" not in mapping or "price" not in mapping:
        raise ValueError("Market mapping must include observed_at and price")
    output = []
    for index, record in enumerate(records, start=1):
        item = {
            "company_id": company,
            "source_id": source_id,
            "source_record": source_id,
            "observed_at": record.get(mapping["observed_at"]),
            "currency": record.get(mapping.get("currency", "")),
        }
        for field in ("price", "volume", "shares_outstanding", "market_cap", "dividend_per_share"):
            column = mapping.get(field)
            item[field] = parse_number(record.get(column)) if column else None
        if not item["observed_at"]:
            raise ValueError(f"Row {index}: observed_at is required")
        datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00"))
        if item["price"] is None:
            raise ValueError(f"Row {index}: price mapping produced no value")
        output.append(item)
    return {
        "company_id": company,
        "currency": next((item["currency"] for item in output if item["currency"]), None),
        "observations": output,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_financial_data(company, records, mapping, source_id):
    source_record(source_id)
    required_mapping = {
        "metric", "value", "unit", "period_end", "period_type", "scope",
    }
    missing_mapping = required_mapping - mapping.keys()
    if missing_mapping:
        raise ValueError(f"Missing financial mapping fields: {sorted(missing_mapping)}")
    facts = []
    for index, record in enumerate(records, start=1):
        item = {
            "company_id": company,
            "metric": record.get(mapping["metric"]),
            "value": parse_number(record.get(mapping["value"])),
            "unit": record.get(mapping["unit"]),
            "period_end": record.get(mapping["period_end"]),
            "period_type": record.get(mapping["period_type"]),
            "scope": record.get(mapping["scope"]),
            "source_id": source_id,
            "source_page": f"structured response row {index}",
            "verification_status": "needs_final_review",
            "fact_classification": "reported",
        }
        if not item["metric"] or item["value"] is None:
            raise ValueError(f"Row {index}: metric and numeric value are required")
        if item["scope"] not in {"standalone", "consolidated"}:
            raise ValueError(f"Row {index}: invalid scope")
        facts.append(item)
    return {"company_id": company, "currency": "PKR", "facts": facts}


def main():
    parser = argparse.ArgumentParser(description="Normalize a structured source response.")
    parser.add_argument("--company", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--mapping", required=True, help="JSON mapping of canonical fields to input columns")
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--kind", choices=["market", "financial"], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = Path(args.input)
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    records = read_records(path)
    if not records:
        parser.error("No structured records found")
    if args.kind == "market":
        result = normalize_market_data(args.company, records, mapping, args.source_id)
    else:
        result = normalize_financial_data(args.company, records, mapping, args.source_id)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
