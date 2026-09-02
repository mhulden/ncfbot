#!/usr/bin/env python3
"""Search normalized NCF course sections offline."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from build_course_history import build_history
from fetch_public_courses import read_jsonl

DEFAULT_INPUT = Path("resources/courses/current-sections.jsonl")


def folded(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def compact_code(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", folded(value))


def contains(value: Any, needle: str | None) -> bool:
    return needle is None or folded(needle) in folded(value)


def record_matches(row: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.term and folded(row.get("term_code")) != folded(args.term):
        return False
    if args.subject and folded(row.get("subject")) != folded(args.subject):
        return False
    if args.course:
        candidates = {
            compact_code(row.get("course_display")),
            compact_code(f"{row.get('subject', '')}{row.get('course_number', '')}"),
            compact_code(row.get("course_number")),
        }
        if compact_code(args.course) not in candidates:
            return False
    if args.section and folded(row.get("section")) != folded(args.section):
        return False
    if args.crn and folded(row.get("crn")) != folded(args.crn):
        return False
    if args.instructor and not any(contains(name, args.instructor) for name in row.get("instructors", [])):
        return False
    if args.attribute and not any(contains(value, args.attribute) for value in row.get("attributes", [])):
        return False
    if args.keyword:
        values = [row.get("title"), row.get("description"), row.get("course_display"), row.get("meeting_summary")]
        if not any(contains(value, args.keyword) for value in values):
            return False
    return True


def metadata_path(input_path: Path) -> Path:
    if input_path.name == "historical-sections.jsonl":
        return input_path.with_name("historical-sections.meta.json")
    if input_path.name == "current-sections.jsonl":
        return input_path.with_name("current-sections.meta.json")
    return input_path.with_suffix(".meta.json")


def load_metadata(input_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    path = metadata_path(input_path)
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if isinstance(value, dict):
            return value
    terms = sorted({str(row.get("term_code")) for row in rows if row.get("term_code")})
    times = sorted({str(row.get("retrieved_at")) for row in rows if row.get("retrieved_at")})
    return {
        "generated_at": times[-1] if times else None,
        "coverage": {"earliest_term_code": terms[0] if terms else None, "latest_term_code": terms[-1] if terms else None},
        "complete": None,
        "incomplete_term_count": None,
    }


def print_context(matches: int, metadata: dict[str, Any]) -> None:
    coverage = metadata.get("coverage") or {}
    earliest, latest = coverage.get("earliest_term_code"), coverage.get("latest_term_code")
    print(f"Matched sections: {matches}")
    if earliest or latest:
        print(f"Archive coverage: {earliest or '?'} through {latest or '?'}")
    timestamp = metadata.get("generated_at") or metadata.get("retrieved_at")
    if timestamp:
        print(f"Snapshot/archive generated: {timestamp}")
    if metadata.get("complete") is False or metadata.get("incomplete_term_count"):
        print(f"WARNING: archive is incomplete ({metadata.get('incomplete_term_count', 'unknown')} incomplete terms)")


def print_scan(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    print_context(len(rows), metadata)
    print("COURSE\tTITLE\tTERM\tSECTIONS")
    grouped: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = (str(row.get("course_display") or ""), str(row.get("title") or ""), str(row.get("term_label") or row.get("term_code") or ""))
        grouped[key] = grouped.get(key, 0) + 1
    for (course, title, term), count in sorted(grouped.items()):
        print(f"{course}\t{title}\t{term}\t{count}")


def print_table(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    print_context(len(rows), metadata)
    print("TERM\tCOURSE\tSEC\tCRN\tTITLE\tINSTRUCTORS\tMEETING")
    for row in rows:
        print(
            "\t".join(
                [
                    str(row.get("term_code") or ""),
                    str(row.get("course_display") or ""),
                    str(row.get("section") or ""),
                    str(row.get("crn") or ""),
                    str(row.get("title") or ""),
                    "; ".join(row.get("instructors") or []),
                    str(row.get("meeting_summary") or ""),
                ]
            )
        )


def print_full(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    print_context(len(rows), metadata)
    for row in rows:
        print("-")
        print(f"{row.get('course_display')} section {row.get('section') or '?'} — {row.get('title')}")
        print(f"Term: {row.get('term_label')} ({row.get('term_code')}); CRN: {row.get('crn')}")
        print(f"Instructor(s): {'; '.join(row.get('instructors') or []) or 'Not published'}")
        print(f"Meeting: {row.get('meeting_summary') or 'Not published'}")
        print(f"Credits/units: {row.get('credits_or_units') if row.get('credits_or_units') is not None else 'Not published'}")
        print(f"Attributes: {'; '.join(row.get('attributes') or []) or 'None published'}")
        print(f"Description: {row.get('description') or 'Not fetched/published'}")
        print(f"Prerequisites: {row.get('prerequisites') or 'Not fetched/published'}")
        print(f"Detail level: {row.get('detail_level')}; retrieved: {row.get('retrieved_at')}")
        if row.get("enrollment"):
            observed = row["enrollment"]
            print(f"Enrollment observation ({observed.get('freshness')}, {observed.get('retrieved_at')}): {observed.get('status')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--term")
    parser.add_argument("--subject")
    parser.add_argument("--course")
    parser.add_argument("--section")
    parser.add_argument("--crn")
    parser.add_argument("--instructor")
    parser.add_argument("--keyword")
    parser.add_argument("--attribute")
    parser.add_argument("--format", choices=("scan", "table", "history", "full", "json", "jsonl"), default="scan")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rows = read_jsonl(args.input)
        metadata = load_metadata(args.input, rows)
        matches = [row for row in rows if record_matches(row, args)]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"course query failed: {exc}", file=sys.stderr)
        return 1
    if args.format == "scan":
        print_scan(matches, metadata)
    elif args.format == "table":
        print_table(matches, metadata)
    elif args.format == "full":
        print_full(matches, metadata)
    elif args.format == "history":
        print(json.dumps(build_history(matches, str(args.input)), indent=2, ensure_ascii=False))
    elif args.format == "json":
        print(json.dumps({"match_count": len(matches), "metadata": metadata, "records": matches}, indent=2, ensure_ascii=False))
    else:
        for row in matches:
            print(json.dumps(row, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
