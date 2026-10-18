import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACTS_FILE = ROOT / "data/normalized/FFC/financial_facts.json"
OCR_DIR = ROOT / "data/normalized/FFC/ocr_second_pass"
REPORT_DIR = ROOT / "reports"
TXT_FILE = REPORT_DIR / "ffc_row_verification.txt"
CSV_FILE = REPORT_DIR / "ffc_row_verification.csv"

# Canonical metric -> source statement labels.
# Extend these aliases only when the source wording is confirmed.
LABELS = {
    "net_turnover": ["turnover net", "net turnover"],
    "gross_profit": ["gross profit"],
    "profit_after_tax": [
        "profit after taxation",
        "profit after tax",
        "profit for the year",
    ],
    "profit_attributable_to_parent": [
        "profit attributable to owners of the holding company",
        "profit attributable to owners of the parent",
        "equity holders of Fauji Fertilizer Company Limited",
    ],
    "earnings_per_share": ["earnings per share"],
    "total_assets": ["total assets"],
    "total_equity_and_liabilities": [
        "total equity and liabilities",
        "total equity and liabilities",
    ],
    "cash_generated_from_operations": ["cash generated from operations"],
    "net_cash_from_operating_activities": [
        "net cash generated from operating activities",
        "net cash from operating activities",
    ],
    "net_cash_from_investing_activities": [
        "net cash used in investing activities",
        "net cash used in generated from investing activities",
        "net cash from investing activities",
    ],
    "net_cash_from_financing_activities": [
        "net cash used in financing activities",
        "net cash from financing activities",
    ],
    "net_change_in_cash_and_cash_equivalents": [
        "net decrease increase in cash and cash equivalents",
        "net increase decrease in cash and cash equivalents",
    ],
    "cash_and_cash_equivalents_beginning": [
        "cash and cash equivalents at beginning of the year",
    ],
    "effect_of_exchange_rate_changes": [
        "effect of exchange rate changes",
    ],
    "cash_and_cash_equivalents_ending": [
        "cash and cash equivalents at end of the year",
    ],
    "cash_and_cash_equivalents_acquired_through_merger": [
        "acquisition of cash and cash equivalents pursuant to merger",
    ],
}

def pdf_page_for(source_page):
    match = re.search(
        r"Annexure A,\s*page\s+(\d+)\s+of\s+8",
        source_page or "",
        re.IGNORECASE,
    )
    return int(match.group(1)) + 2 if match else None

def normalize_label(text):
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())

def number_pattern(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    negative = value < 0
    absolute = abs(value)

    if isinstance(value, float) and not value.is_integer():
        raw = f"{absolute:.10f}".rstrip("0").rstrip(".")
        whole, dot, decimals = raw.partition(".")
        formatted = f"{int(whole):,}" + (dot + decimals if dot else "")
    else:
        formatted = f"{int(absolute):,}"

    formatted = re.escape(formatted).replace(",", r"[, ]?")
    if negative:
        body = rf"(?:-\s*{formatted}|\(\s*{formatted}\s*\))"
    else:
        body = formatted

    return re.compile(r"(?<![\d.])" + body + r"(?![\d.])")

def label_match(line, metric):
    aliases = LABELS.get(metric, [])
    normalized_line = normalize_label(line)
    for alias in aliases:
        normalized_alias = normalize_label(alias)
        if normalized_alias and normalized_alias in normalized_line:
            return True
    return False

def main():
    data = json.loads(FACTS_FILE.read_text())
    results = []

    for fact in data.get("facts", []):
        metric = fact.get("metric", "")
        page = pdf_page_for(fact.get("source_page"))
        status = "REVIEW_REQUIRED"
        matched_line = ""
        number_found_on_row = False
        label_found = False

        if metric not in LABELS:
            status = "NO_LABEL_RULE"
        elif page is None:
            status = "NO_PAGE_MAPPING"
        else:
            ocr_file = OCR_DIR / f"page-{page}.txt"
            if not ocr_file.exists():
                status = "OCR_FILE_MISSING"
            else:
                lines = ocr_file.read_text(errors="replace").splitlines()
                pattern = number_pattern(fact.get("value"))

                matching_lines = [
                    line.strip()
                    for line in lines
                    if line.strip() and label_match(line, metric)
                ]

                if matching_lines:
                    label_found = True
                    matched_line = " | ".join(matching_lines[:3])
                    number_found_on_row = any(
                        pattern and pattern.search(line)
                        for line in matching_lines
                    )

                    if number_found_on_row:
                        status = "ROW_LABEL_AND_VALUE_FOUND"
                    else:
                        status = "LABEL_MATCH_VALUE_MISMATCH"
                else:
                    # Number presence alone is not row-level verification.
                    page_text = "\n".join(lines)
                    if pattern and pattern.search(page_text):
                        status = "VALUE_FOUND_LABEL_NOT_FOUND"
                    else:
                        status = "LABEL_AND_VALUE_NOT_FOUND"

        results.append({
            "metric": metric,
            "scope": fact.get("scope", ""),
            "period_end": fact.get("period_end", ""),
            "value": fact.get("value", ""),
            "unit": fact.get("unit", ""),
            "stored_status": fact.get("verification_status", ""),
            "source_page": fact.get("source_page", ""),
            "pdf_page": page or "",
            "row_check": status,
            "label_found": label_found,
            "value_found_on_label_line": number_found_on_row,
            "matched_ocr_line": matched_line,
        })

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_FILE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    counts = Counter(row["row_check"] for row in results)
    lines = [
        "FFC ROW-AWARE VERIFICATION REPORT",
        "=" * 34,
        f"Facts examined: {len(results)}",
        "",
        "Status counts:",
    ]
    lines.extend(f"{key}: {count}" for key, count in sorted(counts.items()))
    lines += ["", "DETAILS", "=" * 34]

    for row in results:
        lines.append(
            f"[{row['row_check']}] {row['scope']} | {row['metric']} | "
            f"{row['period_end']} | stored={row['value']} {row['unit']} | "
            f"existing_status={row['stored_status']} | "
            f"PDF page={row['pdf_page']}"
        )
        if row["matched_ocr_line"]:
            lines.append(f"  OCR row: {row['matched_ocr_line']}")

    TXT_FILE.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:15]))
    print(f"\nFull report: {TXT_FILE}")
    print(f"CSV report:  {CSV_FILE}")
    print("No financial facts or verification statuses were changed.")

if __name__ == "__main__":
    main()
