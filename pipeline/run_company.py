"""Single-command entry point for the complete company research workflow."""

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command):
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main():
    parser = argparse.ArgumentParser(
        description="Initialize, collect, validate, and analyze a company."
    )
    parser.add_argument("--company", required=True)
    parser.add_argument("--fetch-discover", action="store_true")
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Create a readiness report when no source data has been loaded",
    )
    args = parser.parse_args()

    init_status = run([
        sys.executable,
        str(ROOT / "pipeline" / "init_company.py"),
        "--company",
        args.company,
    ])
    if init_status:
        return init_status

    analysis = [
        sys.executable,
        str(ROOT / "pipeline" / "run_analysis.py"),
        "--company",
        args.company,
    ]
    if args.validate or args.fetch_discover or args.url:
        analysis.append("--validate")
    if args.fetch_discover:
        analysis.append("--fetch-discover")
    if args.allow_empty:
        analysis.append("--allow-empty")
    for url in args.url:
        analysis.extend(["--url", url])
    status = run(analysis)
    if status == 0:
        print(
            f"Complete workflow finished for {args.company}. "
            f"Review reports/{args.company}/fundamental_analysis.md."
        )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
