import hashlib
import json
import math
import sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
FACTS_FILE = ROOT / "data/normalized/FFC/financial_facts.json"
REGISTRY_FILE = ROOT / "data/source_registry.json"

ALLOWED_SCOPES = {"standalone", "consolidated"}
ALLOWED_STATUSES = {
    "verified", "ocr_unverified", "needs_final_review",
    "estimated", "missing",
}
ALLOWED_UNITS = {"PKR_thousand", "PKR", "PKR_per_share"}

errors = []
warnings = []
passes = []


def error(message):
    errors.append(message)


def warning(message):
    warnings.append(message)


def passed(message):
    passes.append(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        error(f"Cannot read {path.relative_to(ROOT)}: {exc}")
        return None


def main():
    data = load_json(FACTS_FILE)
    registry_data = load_json(REGISTRY_FILE)

    if data is None or registry_data is None:
        return report()

    facts = data.get("facts")
    if not isinstance(facts, list):
        error("'facts' must be a JSON array.")
        return report()

    # Support the current registry format: a top-level JSON array.
    if isinstance(registry_data, list):
        sources = registry_data
    elif isinstance(registry_data, dict):
        sources = registry_data.get("sources", [])
    else:
        error("Source registry must be a JSON array or object.")
        return report()

    sources_by_id = {}
    for source in sources:
        source_id = source.get("source_id")
        if not source_id:
            error("Registry entry has no source_id.")
            continue
        if source_id in sources_by_id:
            error(f"Duplicate source_id in registry: {source_id}")
        sources_by_id[source_id] = source

    required = {
        "metric", "scope", "period_end", "period_type", "value",
        "unit", "source_id", "source_page", "verification_status",
    }

    seen = Counter()

    for index, fact in enumerate(facts):
        label = f"Fact #{index + 1} ({fact.get('metric', 'unknown')})"

        missing_fields = required - fact.keys()
        if missing_fields:
            error(f"{label}: missing fields {sorted(missing_fields)}")
            continue

        if fact["scope"] not in ALLOWED_SCOPES:
            error(f"{label}: invalid scope {fact['scope']!r}")

        if fact["verification_status"] not in ALLOWED_STATUSES:
            error(f"{label}: invalid verification status")
        elif fact["verification_status"] != "verified":
            warning(
                f"{label}: status is "
                f"{fact['verification_status']!r}, not verified"
            )

        if fact["unit"] not in ALLOWED_UNITS:
            error(f"{label}: unsupported unit {fact['unit']!r}")

        value = fact["value"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            error(f"{label}: value must be a finite number")

        period = fact["period_end"]
        if not isinstance(period, str):
            error(f"{label}: period_end must be a date string")
        else:
            try:
                from datetime import date
                date.fromisoformat(period)
            except ValueError:
                error(f"{label}: invalid period_end {period!r}")

        key = (
            fact["metric"], fact["scope"], fact["period_end"],
            fact["period_type"], fact["unit"],
        )
        seen[key] += 1

        source_id = fact["source_id"]
        source = sources_by_id.get(source_id)

        if source is None:
            error(f"{label}: source {source_id!r} not found")
            continue

        local_path = source.get("local_path")
        expected_hash = source.get("sha256")

        if not local_path:
            error(f"{label}: registry source has no local_path")
            continue

        # Prevent absolute paths and traversal outside the project root.
        candidate = Path(local_path)
        if candidate.is_absolute():
            error(f"{label}: source path must be project-relative")
            continue

        resolved = (ROOT / candidate).resolve()
        if not resolved.is_relative_to(ROOT):
            error(f"{label}: source path escapes project root")
            continue

        if not resolved.is_file():
            error(f"{label}: source file not found: {local_path}")
            continue

        if not expected_hash:
            warning(f"{label}: registry source has no SHA-256")
            continue

        actual_hash = sha256_file(resolved)
        if actual_hash != expected_hash:
            error(f"{label}: SHA-256 mismatch for {local_path}")
        else:
            passed(f"{label}: source file hash matches registry")

    for key, count in seen.items():
        if count > 1:
            error(f"Duplicate fact key ({count} occurrences): {key}")

    return report()


def report():
    print("\nFinancial Facts Validation")
    print("=" * 30)

    for message in passes:
        print(f"PASS: {message}")
    for message in warnings:
        print(f"WARNING: {message}")
    for message in errors:
        print(f"ERROR: {message}")

    print(
        f"\nSummary: {len(passes)} passed, "
        f"{len(warnings)} warning(s), {len(errors)} error(s)"
    )

    if errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
