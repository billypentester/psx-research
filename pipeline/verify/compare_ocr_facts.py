import json
import re
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
FACTS_FILE = ROOT / "data/normalized/FFC/financial_facts.json"
OCR_DIR = ROOT / "data/normalized/FFC/ocr_second_pass"
REPORT_DIR = ROOT / "reports"
REPORT_FILE = REPORT_DIR / "ffc_ocr_comparison.txt"
CSV_FILE = REPORT_DIR / "ffc_ocr_comparison.csv"

data = json.loads(FACTS_FILE.read_text())
results = []

def pdf_page_for(source_page):
    match = re.search(r"Annexure A,\s*page\s+(\d+)\s+of\s+8", source_page or "")
    if not match:
        return None
    # Annexure A begins on PDF page 3 in this filing.
    return int(match.group(1)) + 2

def number_pattern(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    negative = value < 0
    absolute_value = abs(value)

    if isinstance(value, float) and not value.is_integer():
        raw = f"{absolute_value:.10f}".rstrip("0").rstrip(".")
        integer, dot, decimal = raw.partition(".")
        formatted = f"{int(integer):,}" + (dot + decimal if dot else "")
    else:
        formatted = f"{int(absolute_value):,}"

    escaped = re.escape(formatted)
    escaped = escaped.replace(",", r"[, ]?")

    if negative:
        numeric = rf"(?:-\s*{escaped}|\(\s*{escaped}\s*\))"
    else:
        numeric = escaped

    return re.compile(r"(?<![\d.])" + numeric + r"(?![\d.])")

for fact in data.get("facts", []):
    page = pdf_page_for(fact.get("source_page"))
    status = "NO_PAGE_MAPPING"
    excerpt = ""
    ocr_file = ""

    if page is not None:
        path = OCR_DIR / f"page-{page}.txt"
        ocr_file = str(path.relative_to(ROOT))

        if not path.exists():
            status = "OCR_FILE_MISSING"
        else:
            text = path.read_text(errors="replace")
            pattern = number_pattern(fact.get("value"))

            if pattern is None:
                status = "UNSUPPORTED_VALUE_TYPE"
            else:
                matches = list(pattern.finditer(text))
                if matches:
                    status = "VALUE_FOUND"
                    m = matches[0]
                    excerpt = text[max(0, m.start()-65):min(len(text), m.end()+65)]
                    excerpt = " ".join(excerpt.split())
                else:
                    status = "VALUE_NOT_FOUND"
                    # Include likely nearby context for easier diagnosis.
                    excerpt = " ".join(text.split())[:220]

    results.append({
        "metric": fact.get("metric", ""),
        "scope": fact.get("scope", ""),
        "period_end": fact.get("period_end", ""),
        "value": fact.get("value", ""),
        "unit": fact.get("unit", ""),
        "stored_status": fact.get("verification_status", ""),
        "source_page": fact.get("source_page", ""),
        "pdf_page": page if page is not None else "",
        "ocr_file": ocr_file,
        "comparison": status,
        "ocr_excerpt": excerpt,
    })

REPORT_DIR.mkdir(parents=True, exist_ok=True)

from csv import DictWriter
with CSV_FILE.open("w", newline="") as f:
    writer = DictWriter(f, fieldnames=list(results[0].keys()) if results else [])
    if results:
        writer.writeheader()
        writer.writerows(results)

counts = Counter(r["comparison"] for r in results)

lines = [
    "FFC SECOND-PASS OCR COMPARISON",
    "=" * 34,
    f"Facts examined: {len(results)}",
    "",
]
for key, count in sorted(counts.items()):
    lines.append(f"{key}: {count}")

lines += [
    "",
    "DETAILS",
    "=" * 34,
]
for r in results:
    lines.append(
        f"[{r['comparison']}] {r['scope']} | {r['metric']} | "
        f"{r['period_end']} | stored={r['value']} {r['unit']} | "
        f"status={r['stored_status']} | PDF page={r['pdf_page']}"
    )
    lines.append(f"  OCR: {r['ocr_excerpt'] or '(no excerpt)'}")

REPORT_FILE.write_text("\n".join(lines) + "\n")

print("\n".join(lines[:10]))
print(f"\nFull report: {REPORT_FILE}")
print(f"CSV report:  {CSV_FILE}")
print("\nNo dataset values or verification statuses were changed.")
