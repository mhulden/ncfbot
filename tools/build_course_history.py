#!/usr/bin/env python3
"""Build conservative exact-course-code history from section JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from discover_public_terms import SCHEMA_VERSION, TOOL_VERSION, atomic_write_json, utc_now
from fetch_public_courses import read_jsonl


def unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def build_history(rows: list[dict[str, Any]], source: str) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"record {index} must be an object")
        subject = str(row.get("subject") or "").strip().upper()
        number = str(row.get("course_number") or "").strip().upper()
        term = str(row.get("term_code") or "").strip()
        crn = str(row.get("crn") or "").strip()
        if not all((subject, number, term, crn)):
            raise ValueError(f"record {index} is missing subject/course_number/term_code/crn")
        grouped.setdefault((subject, number), []).append(row)
    courses: list[dict[str, Any]] = []
    for (subject, number), sections in sorted(grouped.items()):
        sections.sort(key=lambda row: (row["term_code"], row["crn"]))
        courses.append(
            {
                "subject": subject,
                "course_number": number,
                "course_display": next((row.get("course_display") for row in sections if row.get("course_display")), f"{subject} {number}"),
                "titles": unique([row.get("title") for row in sections if row.get("title")]),
                "terms": unique([{"term_code": row["term_code"], "term_label": row.get("term_label")} for row in sections]),
                "instructors": sorted(set(name for row in sections for name in row.get("instructors", []) if name)),
                "attributes": sorted(set(value for row in sections for value in row.get("attributes", []) if value)),
                "section_count": len(sections),
                "section_identities": [{"term_code": row["term_code"], "crn": row["crn"], "section": row.get("section")} for row in sections],
            }
        )
    term_codes = sorted({str(row["term_code"]) for row in rows})
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": utc_now(),
        "source": source,
        "grouping_rule": "exact normalized subject plus exact published course_number; similarity is not equivalency",
        "course_count": len(courses),
        "section_count": len(rows),
        "coverage": {
            "earliest_term_code": term_codes[0] if term_codes else None,
            "latest_term_code": term_codes[-1] if term_codes else None,
        },
        "courses": courses,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("resources/courses/historical-sections.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("resources/courses/course-history.json"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rows = read_jsonl(args.input)
        artifact = build_history(rows, str(args.input))
        atomic_write_json(args.output, artifact)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"history build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Grouped {artifact['section_count']} sections into {artifact['course_count']} exact course codes -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
