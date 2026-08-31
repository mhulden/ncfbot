"""Command-line entry point for deterministic NCF Bot helpers."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from .doctor import run_doctor
from .evaluation import run_evaluation
from .retrieval import search
from .router import route
from .sources import SourceError, load_resources, repository_root


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ncfbot",
        description="Inspect and validate the public-information bot repository.",
    )
    parser.add_argument("--root", type=Path, help="repository root (defaults to the current repository)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="run offline repository health checks")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    route_parser = subparsers.add_parser("route", help="show a transparent audience-routing suggestion")
    route_parser.add_argument("question")
    route_parser.add_argument("--previous-role", choices=("students", "faculty", "outside"))
    route_parser.add_argument("--json", action="store_true")

    search_parser = subparsers.add_parser("search", help="search authored resources for public evidence")
    search_parser.add_argument("query")
    search_parser.add_argument("--audience", choices=("students", "faculty", "outside"))
    search_parser.add_argument("--topic")
    search_parser.add_argument("--limit", type=int, default=5)
    search_parser.add_argument("--json", action="store_true")

    sources_parser = subparsers.add_parser("sources", help="inspect validated resource provenance")
    sources_parser.add_argument("--topic")
    sources_parser.add_argument("--audience")
    sources_parser.add_argument("--json", action="store_true")

    evaluate = subparsers.add_parser("evaluate", help="validate cases and run deterministic assertions")
    evaluate.add_argument("--export", type=Path, help="write the complete run record as JSON")
    evaluate.add_argument("--json", action="store_true")

    course = subparsers.add_parser("course", help="pass remaining arguments to tools/query_courses.py")
    course.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def _doctor(args: argparse.Namespace, root: Path) -> int:
    report = run_doctor(root)
    if args.json:
        _print_json(report.to_dict())
    else:
        print("Repository health: " + ("PASS" if report.ok else "FAIL"))
        if not report.issues:
            print("No offline contract issues found.")
        for issue in report.issues:
            print(f"[{issue.severity.upper()}] {issue.check}: {issue.message}")
        print("Network checks were not run; use the source pipeline's explicit network mode when needed.")
    return 0 if report.ok else 1


def _route(args: argparse.Namespace) -> int:
    result = route(args.question, args.previous_role)
    if args.json:
        _print_json(result.to_dict())
    else:
        print(f"route: {result.route}")
        print("reason: " + result.reason)
        print("matched signals: " + (", ".join(result.matched_signals) or "none"))
    return 0


def _search(args: argparse.Namespace, root: Path) -> int:
    try:
        results = search(args.query, root, audience=args.audience, topic=args.topic, limit=args.limit)
    except (SourceError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        _print_json([item.to_dict() for item in results])
        return 0
    if not results:
        print("No matching public evidence was found in the curated local corpus.")
        return 0
    print("Evidence only — not an official decision or a generated answer.\n")
    for result in results:
        print(f"{result.resource_id} — {result.heading}")
        print(f"  score: {result.score:.3f}")
        print(f"  audiences: {', '.join(result.audiences)}")
        print(f"  topics: {', '.join(result.topics)}")
        print(f"  authority: {', '.join(result.authority_types)}")
        print(f"  status: {result.status}")
        print(f"  effective period: {result.effective_period}")
        print(f"  review state: {result.review_state}")
        print(f"  excerpt: {result.excerpt}")
        for url in result.source_urls:
            print(f"  source: {url}")
    return 0


def _sources(args: argparse.Namespace, root: Path) -> int:
    try:
        resources, _ = load_resources(root)
    except SourceError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    selected = [
        resource for resource in resources
        if (not args.topic or args.topic in resource.metadata["topics"])
        and (not args.audience or args.audience in resource.metadata["audiences"])
    ]
    payload = [
        {
            "id": item.resource_id,
            "title": item.title,
            "resource_file": str(item.metadata["resource_file"]),
            "audiences": item.metadata["audiences"],
            "topics": item.metadata["topics"],
            "status": item.metadata["status"],
            "review_after": item.metadata["review_after"],
            "sources": list(item.urls),
        }
        for item in selected
    ]
    if args.json:
        _print_json(payload)
    elif not payload:
        print("No validated resources match those filters.")
    else:
        for item in payload:
            print(f"{item['id']} — {item['title']} [{item['status']}, review after {item['review_after']}]")
            print(f"  {item['resource_file']}")
            for url in item["sources"]:
                print(f"  {url}")
    return 0


def _evaluate(args: argparse.Namespace, root: Path) -> int:
    report = run_evaluation(root)
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        _print_json(report)
    else:
        print(f"Evaluation cases: {report['case_count']}")
        print(f"Deterministic assertions: {report['passed']} passed, {report['failed']} failed")
        print("By audience: " + json.dumps(report["by_audience"], sort_keys=True))
        print("By topic: " + json.dumps(report["by_topic"], sort_keys=True))
        for error in report["validation_errors"]:
            print(f"[ERROR] {error}")
        for result in report["results"]:
            for failure in result["failures"]:
                print(f"[FAIL] {result['id']}: {failure}")
        if args.export:
            print(f"Exported run record to {args.export}")
    return 0 if not report["validation_errors"] and report["failed"] == 0 else 1


def _course(args: argparse.Namespace, root: Path) -> int:
    tool = root / "tools" / "query_courses.py"
    if not tool.is_file():
        print("Course query tool is unavailable; Agent 6 must provide tools/query_courses.py.", file=sys.stderr)
        return 2
    forwarded = args.args[1:] if args.args[:1] == ["--"] else args.args
    completed = subprocess.run([sys.executable, str(tool), *forwarded], cwd=root)
    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root = repository_root(args.root)
    if args.command == "doctor":
        return _doctor(args, root)
    if args.command == "route":
        return _route(args)
    if args.command == "search":
        return _search(args, root)
    if args.command == "sources":
        return _sources(args, root)
    if args.command == "evaluate":
        return _evaluate(args, root)
    if args.command == "course":
        return _course(args, root)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
