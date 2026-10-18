"""Validate generic normalized market observations."""

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(company):
    path = ROOT / "data" / "normalized" / company / "market_data.json"
    if not path.is_file():
        print(f"ERROR: missing market data: {path}")
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    registry_path = ROOT / "data" / "source_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    source_ids = {item["source_id"] for item in registry}
    errors = []
    if data.get("company_id") != company:
        errors.append("company_id does not match requested company")
    observations = data.get("observations")
    if not isinstance(observations, list):
        errors.append("observations must be an array")
    for index, item in enumerate(observations or [], start=1):
        try:
            datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            errors.append(f"observation {index}: invalid observed_at")
        if (
            isinstance(item.get("price"), bool)
            or not isinstance(item.get("price"), (int, float))
            or not math.isfinite(item["price"])
            or item["price"] < 0
        ):
            errors.append(f"observation {index}: price must be a non-negative number")
        if not item.get("source_id"):
            errors.append(f"observation {index}: source_id is required")
        elif item["source_id"] not in source_ids:
            errors.append(f"observation {index}: source_id is not registered")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"Market observations: {len(observations or [])}; errors: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    raise SystemExit(main(parser.parse_args().company))
