import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "source_registry.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []

    with REGISTRY.open(encoding="utf-8") as file:
        records = json.load(file)

    if not isinstance(records, list):
        raise ValueError("Source registry must contain a JSON array.")

    return records


def register_source(args: argparse.Namespace) -> dict:
    file_path = Path(args.file).expanduser().resolve()

    if not file_path.is_file():
        raise FileNotFoundError(f"Source file does not exist: {file_path}")

    if args.url and urlparse(args.url).scheme not in {"http", "https"}:
        raise ValueError("URL must start with http:// or https://")

    if args.published_at:
        datetime.strptime(args.published_at, "%Y-%m-%d")

    file_hash = sha256_file(file_path)
    records = load_registry()

    # Identical content is not registered twice for the same company.
    for record in records:
        if (
            record["company_id"] == args.company
            and record["sha256"] == file_hash
        ):
            print(f"Already registered: {record['source_id']}")
            return record

    identity = "|".join(
        [args.company, args.url or "", file_hash]
    )
    source_id = "src_" + hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()[:16]

    record = {
        "source_id": source_id,
        "company_id": args.company,
        "source_type": args.type,
        "title": args.title,
        "url": args.url or None,
        "published_at": args.published_at or None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "local_path": str(file_path.relative_to(ROOT))
        if file_path.is_relative_to(ROOT)
        else str(file_path),
        "sha256": file_hash,
        "page_number": None,
        "notes": args.notes or None,
    }

    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    records.append(record)

    temporary = REGISTRY.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(records, file, indent=2, ensure_ascii=False)
        file.write("\n")

    temporary.replace(REGISTRY)
    print(f"Registered source: {source_id}")
    print(f"Registry: {REGISTRY}")
    print(f"SHA-256: {file_hash}")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register a local source document."
    )
    parser.add_argument("--company", required=True, help="Company ID, e.g. FFC")
    parser.add_argument("--title", required=True, help="Document title")
    parser.add_argument(
        "--type",
        required=True,
        choices=[
            "annual_report",
            "quarterly_report",
            "announcement",
            "market_data",
            "other",
        ],
    )
    parser.add_argument("--file", required=True, help="Path to downloaded file")
    parser.add_argument("--url", help="Original official source URL")
    parser.add_argument("--published-at", help="Publication date: YYYY-MM-DD")
    parser.add_argument("--notes", help="Source limitations or notes")
    args = parser.parse_args()

    try:
        register_source(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()