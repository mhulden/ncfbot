#!/usr/bin/env python3
"""Fetch public detail-tab text for one shortlisted Banner section."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from urllib.parse import urlencode
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from discover_public_terms import DEFAULT_BASE_URL, SCHEMA_VERSION, TOOL_VERSION, BannerError, BannerSession, atomic_write_json, utc_now

DETAIL_ENDPOINTS = {
    "description": "getCourseDescription",
    "prerequisites": "getSectionPrerequisites",
    "corequisites": "getCorequisites",
    "restrictions": "getRestrictions",
    "mutual_exclusions": "getCourseMutuallyExclusions",
    "catalog_details": "getSectionCatalogDetails",
    "linked_sections": "getLinkedSections",
    "cross_listed_sections": "getXlstSections",
}
HEADINGS = {
    "description": ["Course Description"],
    "prerequisites": ["Catalog Prerequisites", "Class Prerequisites"],
    "corequisites": ["Corequisites"],
    "restrictions": ["Restrictions"],
    "mutual_exclusions": ["Mutual Exclusions"],
    "catalog_details": ["Catalog Details"],
    "linked_sections": ["Linked Sections"],
    "cross_listed_sections": ["Cross Listed Sections", "Cross-Listed Sections"],
}
UNAVAILABLE_MARKERS = (
    "no prerequisite information available",
    "no corequisite course information available",
    "no course restriction information is available",
    "no mutual exclusion information available",
    "no linked course information available",
    "no cross list information available",
    "no course description available",
)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")


def clean_detail(fragment: str, field: str) -> str | None:
    parser = TextExtractor()
    parser.feed(fragment)
    text = html.unescape(" ".join(parser.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    for heading in HEADINGS.get(field, []):
        text = re.sub(rf"^{re.escape(heading)}\s*", "", text, flags=re.IGNORECASE)
    text = text.strip(" :-\n")
    if not text or any(marker in text.casefold() for marker in UNAVAILABLE_MARKERS):
        return None
    return text


def parse_course_levels(fragment: str) -> tuple[list[dict[str, str]], str]:
    """Read Banner's Levels block, never titles, divisions or restrictions."""
    text = clean_detail(fragment, "catalog_details") or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if "Levels:" not in lines:
        return [], "not_published"
    start = lines.index("Levels:") + 1
    try:
        end = lines.index("Grading Modes:", start)
    except ValueError:
        return [], "unrecognized"
    levels = []
    for line in lines[start:end]:
        match = re.fullmatch(r"(.+?)\s+([A-Za-z0-9]+)", line)
        if not match or ":" in line:
            return [], "unrecognized"
        level = {"description": match[1], "code": match[2]}
        if level not in levels:
            levels.append(level)
    return levels, "published" if levels else "not_published"


def course_level_fields(details: dict[str, Any]) -> dict[str, Any]:
    """Derive levels from new or legacy detail caches without refreshing listings."""
    fragment = (details.get("_raw_fragments") or {}).get("catalog_details")
    if fragment is None:
        fragment = details.get("catalog_details")
    if "catalog_details" in (details.get("failures") or {}):
        levels, status = [], "failed"
    elif fragment is None:
        levels, status = [], "not_published"
    else:
        levels, status = parse_course_levels(fragment)
    return {
        "course_levels": levels,
        "course_level_metadata": {
            "status": status,
            "source_url": DEFAULT_BASE_URL + "/searchResults/getSectionCatalogDetails?" + urlencode({
                "term": details["term_code"], "courseReferenceNumber": details["crn"],
            }),
            "retrieved_at": details["retrieved_at"],
        },
    }


def fetch_details(client: BannerSession, term: str, crn: str) -> dict[str, Any]:
    client.select_term(term)
    retrieved_at = utc_now()
    raw_fragments: dict[str, str] = {}
    normalized: dict[str, str | None] = {}
    failures: dict[str, str] = {}
    for field, endpoint in DETAIL_ENDPOINTS.items():
        try:
            body, _ = client.request(
                f"/searchResults/{endpoint}",
                query={"term": term, "courseReferenceNumber": crn},
                ajax=True,
                referer=client.url("/classSearch/classSearch"),
            )
            fragment = body.decode("utf-8", errors="replace")
            raw_fragments[field] = fragment
            normalized[field] = clean_detail(fragment, field)
        except BannerError as exc:
            failures[field] = str(exc)
            normalized[field] = None
    status = "success" if not failures else "partial"
    result = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "term_code": term,
        "crn": crn,
        "retrieved_at": retrieved_at,
        "detail_level": "enriched",
        "detail_status": status,
        "source_url": client.url("/searchResults/searchResults"),
        **normalized,
        "failures": failures,
        "_raw_fragments": raw_fragments,
    }
    result.update(course_level_fields(result))
    return result


def cache_path(cache_dir: Path, term: str, crn: str) -> Path:
    safe_term = re.sub(r"[^A-Za-z0-9_.-]", "_", term)
    safe_crn = re.sub(r"[^A-Za-z0-9_.-]", "_", crn)
    return cache_dir / safe_term / f"{safe_crn}.json"


def public_result(cached: dict[str, Any]) -> dict[str, Any]:
    return {**{key: value for key, value in cached.items() if key != "_raw_fragments"}, **course_level_fields(cached)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--term", required=True)
    parser.add_argument("--crn", required=True)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--cache-dir", type=Path, default=Path("resources/courses/.cache/details"))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    location = cache_path(args.cache_dir, args.term, args.crn)
    try:
        if location.exists() and not args.refresh and not args.no_cache:
            with location.open(encoding="utf-8") as handle:
                result = json.load(handle)
            if result.get("term_code") != args.term or result.get("crn") != args.crn:
                raise ValueError("detail cache identity mismatch")
        else:
            result = fetch_details(BannerSession(args.base_url, args.timeout), args.term, args.crn)
            if not args.no_cache:
                atomic_write_json(location, result)
    except (BannerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"detail fetch failed: {exc}", file=sys.stderr)
        return 1
    visible = public_result(result)
    if args.format == "json":
        print(json.dumps(visible, indent=2, ensure_ascii=False))
    else:
        print(f"Details for term {args.term}, CRN {args.crn} ({visible['detail_status']})")
        for field in DETAIL_ENDPOINTS:
            print(f"{field.replace('_', ' ').title()}: {visible.get(field) or 'Not published'}")
        print(f"Course levels: {visible['course_levels']} ({visible['course_level_metadata']['status']})")
    return 0 if result.get("detail_status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
