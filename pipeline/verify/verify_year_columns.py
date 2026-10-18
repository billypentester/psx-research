import csv
import json
import re
from collections import Counter
from pathlib import Path

from verify_financial_rows import LABELS, pdf_page_for, label_match

ROOT = Path(__file__).resolve().parents[2]
FACTS_FILE = ROOT / "data/normalized/FFC/financial_facts.json"
OCR_DIR = ROOT / "data/normalized/FFC/ocr_second_pass"
REPORT_DIR = ROOT / "reports"
CSV_FILE = REPORT_DIR / "ffc_year_column_verification.csv"
TXT_FILE = REPORT_DIR / "ffc_year_column_verification.txt"

NUMBER_RE = re.compile(r"(?<![\w.])\(?-?\d[\d,]*(?:\.\d+)?\)?(?![\w.])")


def parse_number(token):
    token = token.replace(",", "").strip()
    negative = token.startswith("(") and token.endswith(")")
    token = token.strip("()")
    number = float(token) if "." in token else int(token)
    return -abs(number) if negative else number


def numbers_on_line(line):
    return [parse_number(m.group()) for m in NUMBER_RE.finditer(line)]


def find_year_order(lines):
    for line in lines[:20]:
        years = re.findall(r"\b20\d{2}\b", line)
        if len(years) >= 2:
            first_two = [int(year) for year in years[:2]]
            if first_two[0] != first_two[1]:
                return first_two
    return []


def main():
    data = json.loads(FACTS_FILE.read_text())
    results = []
    page_cache = {}

    for fact in data.get("facts", []):
        metric = fact.get("metric", "")
        page = pdf_page_for(fact.get("source_page"))
        period = fact.get("period_end", "")
        target_year = int(period[:4]) if period[:4].isdigit() else None

        result = {
            "metric": metric,
            "scope": fact.get("scope", ""),
            "period_end": period,
            "stored_value": fact.get("value", ""),
            "stored_status": fact.get("verification_status", ""),
            "pdf_page": page or "",
            "year_column": "",
            "ocr_value_in_year_column": "",
            "ocr_row": "",
            "check_status": "",
        }

        if metric not in LABELS:
            result["check_status"] = "NO_LABEL_RULE"
        elif page is None:
            result["check_status"] = "NO_PAGE_MAPPING"
        else:
            if page not in page_cache:
                path = OCR_DIR / f"page-{page}.txt"
                if path.exists():
                    lines = path.read_text(errors="replace").splitlines()
                    page_cache[page] = (lines, find_year_order(lines))
                else:
                    page_cache[page] = (None, [])

            lines, years = page_cache[page]

            if lines is None:
                result["check_status"] = "OCR_FILE_MISSING"
            elif not years:
                result["check_status"] = "YEAR_HEADER_NOT_FOUND"
            elif target_year not in years:
                result["check_status"] = "TARGET_YEAR_NOT_IN_HEADER"
            else:
                column_index = years.index(target_year)
                result["year_column"] = target_year
                matching = [
                    line.strip()
                    for line in lines
                    if line.strip() and label_match(line, metric)
                ]

                if not matching:
                    result["check_status"] = "LABEL_NOT_FOUND"
                else:
                    checked = False
                    saw_short_row = False

                    for line in matching:
                        # Remove the matched label before parsing numeric values.
                        normalized_line = line
                        aliases = sorted(
                            LABELS.get(metric, []),
                            key=len,
                            reverse=True,
                        )
                        for alias in aliases:
                            pos = normalized_line.lower().find(alias.lower())
                            if pos >= 0:
                                normalized_line = normalized_line[pos + len(alias):]
                                break

                        stripped = normalized_line.lstrip()
                        values = numbers_on_line(normalized_line)

                        # Only the merger row uses a dash for 2025 followed
                        # by a numeric 2024 amount in this source.
                        is_merger_row = (
                            metric == "cash_and_cash_equivalents_acquired_through_merger"
                        )
                        leading_dash = bool(
                            re.match(r"^[—–-](?:\s|$)", stripped)
                        )

                        if is_merger_row and leading_dash:
                            if target_year == 2025:
                                result["ocr_row"] = line
                                result["ocr_value_in_year_column"] = "DASH_PLACEHOLDER"
                                result["check_status"] = "YEAR_COLUMN_DASH_PLACEHOLDER"
                                checked = True
                                break
                            elif target_year == 2024 and values:
                                cell = values[0]
                            else:
                                saw_short_row = True
                                continue
                        elif len(values) > column_index:
                            cell = values[column_index]
                        else:
                            saw_short_row = True
                            continue

                        result["ocr_row"] = line
                        result["ocr_value_in_year_column"] = cell

                        if (
                            isinstance(fact.get("value"), (int, float))
                            and cell == fact["value"]
                        ):
                            result["check_status"] = "YEAR_COLUMN_VALUE_MATCH"
                        else:
                            result["check_status"] = "YEAR_COLUMN_VALUE_MISMATCH"

                        checked = True
                        break

                    if not checked:
                        result["check_status"] = (
                            "NOT_ENOUGH_ROW_VALUES" if saw_short_row
                            else "ROW_VALUES_NOT_PARSED"
                        )

        results.append(result)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_FILE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    counts = Counter(row["check_status"] for row in results)
    report = [
        "FFC YEAR-COLUMN VERIFICATION REPORT",
        "=" * 36,
        f"Facts examined: {len(results)}",
        "",
        "Status counts:",
        *[f"{key}: {count}" for key, count in sorted(counts.items())],
        "",
        "DETAILS",
        "=" * 36,
    ]

    for row in results:
        if row["check_status"] != "YEAR_COLUMN_VALUE_MATCH":
            report.append(
                f"[{row['check_status']}] {row['scope']} | {row['metric']} | "
                f"{row['period_end']} | stored={row['stored_value']} | "
                f"OCR column={row['ocr_value_in_year_column']} | "
                f"page={row['pdf_page']}"
            )
            if row["ocr_row"]:
                report.append(f"  OCR row: {row['ocr_row']}")

    TXT_FILE.write_text("\n".join(report) + "\n")
    print("\n".join(report[:25]))
    print(f"\nFull report: {TXT_FILE}")
    print(f"CSV report:  {CSV_FILE}")
    print("No financial facts or verification statuses were changed.")


if __name__ == "__main__":
    main()
