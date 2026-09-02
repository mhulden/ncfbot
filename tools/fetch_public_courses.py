#!/usr/bin/env python3
"""Fetch and normalize public Banner section listings."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from discover_public_terms import (
    DEFAULT_BASE_URL,
    SCHEMA_VERSION,
    TOOL_VERSION,
    BannerError,
    BannerSession,
    atomic_write_json,
    atomic_write_jsonl,
    discover_terms,
    utc_now,
)

RESULTS_PATH = "/searchResults/searchResults"
DAY_FIELDS = (
    ("monday", "Mon"),
    ("tuesday", "Tue"),
    ("wednesday", "Wed"),
    ("thursday", "Thu"),
    ("friday", "Fri"),
    ("saturday", "Sat"),
    ("sunday", "Sun"),
)


def clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def strings(values: Any, key: str | None = None) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        candidate = value.get(key) if key and isinstance(value, dict) else value
        text = clean_string(candidate)
        if text and text not in result:
            result.append(text)
    return result


def format_clock(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 4:
        return None
    hour, minute = int(digits[:2]), int(digits[2:])
    if hour > 23 or minute > 59:
        return None
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


def normalize_meeting(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    meeting = raw.get("meetingTime") if isinstance(raw.get("meetingTime"), dict) else raw
    faculty = raw.get("faculty") if isinstance(raw.get("faculty"), list) else []
    days = [label for field, label in DAY_FIELDS if meeting.get(field) is True]
    return {
        "days": days,
        "begin_time": clean_string(meeting.get("beginTime")),
        "end_time": clean_string(meeting.get("endTime")),
        "start_date": clean_string(meeting.get("startDate")),
        "end_date": clean_string(meeting.get("endDate")),
        "building": clean_string(meeting.get("building")),
        "building_description": clean_string(meeting.get("buildingDescription")),
        "room": clean_string(meeting.get("room")),
        "campus": clean_string(meeting.get("campus")),
        "campus_description": clean_string(meeting.get("campusDescription")),
        "meeting_type": clean_string(meeting.get("meetingType")),
        "meeting_type_description": clean_string(meeting.get("meetingTypeDescription")),
        "schedule_type": clean_string(meeting.get("meetingScheduleType")),
        "instructors": strings(faculty, "displayName"),
    }


def summarize_meetings(meetings: list[dict[str, Any]]) -> str | None:
    parts: list[str] = []
    for meeting in meetings:
        segment: list[str] = []
        if meeting["days"]:
            segment.append("/".join(meeting["days"]))
        begin, end = format_clock(meeting["begin_time"]), format_clock(meeting["end_time"])
        if begin and end:
            segment.append(f"{begin}-{end}")
        location = " ".join(value for value in [meeting["building"], meeting["room"]] if value)
        if location:
            segment.append(location)
        date_range = "-".join(value for value in [meeting["start_date"], meeting["end_date"]] if value)
        if date_range:
            segment.append(date_range)
        if segment:
            parts.append(" ".join(segment))
    return "; ".join(parts) or None


def credits(raw: dict[str, Any]) -> int | float | str | None:
    direct = raw.get("creditHours")
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return direct
    low, high = raw.get("creditHourLow"), raw.get("creditHourHigh")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)) and low != high:
        return f"{low:g}-{high:g}"
    if isinstance(low, (int, float)):
        return low
    return clean_string(direct)


def enrollment_observation(raw: dict[str, Any], retrieved_at: str) -> dict[str, Any] | None:
    mapping = {
        "maximum": "maximumEnrollment",
        "enrolled": "enrollment",
        "seats_available": "seatsAvailable",
        "wait_capacity": "waitCapacity",
        "wait_count": "waitCount",
        "wait_available": "waitAvailable",
        "open_section": "openSection",
    }
    values = {target: raw.get(source) for target, source in mapping.items()}
    if all(value is None for value in values.values()):
        return None
    open_value = values.get("open_section")
    status = "open" if open_value is True else "closed" if open_value is False else "unknown"
    return {
        "status": status,
        **values,
        "retrieved_at": retrieved_at,
        "freshness": "snapshot",
    }


def normalize_section(raw: Any, term_code: str, term_label: str, retrieved_at: str, source_url: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("section result must be an object")
    crn = clean_string(raw.get("courseReferenceNumber"))
    source_term = clean_string(raw.get("term"))
    if not crn or not source_term or source_term != term_code:
        raise ValueError("section result is missing the exact requested term/CRN identity")
    subject = clean_string(raw.get("subject")) or ""
    number = clean_string(raw.get("courseNumber")) or ""
    display_source = clean_string(raw.get("courseDisplay")) or number
    if subject and display_source.casefold().startswith(subject.casefold()):
        display = display_source
    else:
        display = " ".join(value for value in [subject, display_source] if value)
    meeting_rows = [row for row in (normalize_meeting(item) for item in raw.get("meetingsFaculty") or []) if row]
    instructors = strings(raw.get("faculty"), "displayName")
    attributes = strings(raw.get("sectionAttributes"), "description")
    return {
        "term_code": term_code,
        "term_label": clean_string(raw.get("termDesc")) or re.sub(r"\s*\(View Only\)\s*$", "", term_label),
        "subject": subject,
        "course_number": number,
        "course_display": display,
        "section": clean_string(raw.get("sequenceNumber")),
        "crn": crn,
        "title": clean_string(raw.get("courseTitle")) or "",
        "instructors": instructors,
        "meetings": meeting_rows,
        "meeting_summary": summarize_meetings(meeting_rows),
        "credits_or_units": credits(raw),
        "attributes": attributes,
        "description": None,
        "prerequisites": None,
        "corequisites": None,
        "restrictions": None,
        "mutual_exclusions": None,
        "catalog_details": None,
        "linked_sections": None,
        "cross_listed_sections": None,
        "detail_level": "listing",
        "detail_status": "not_requested",
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "enrollment": enrollment_observation(raw, retrieved_at),
    }


def fetch_term(
    client: BannerSession,
    term_code: str,
    term_label: str,
    *,
    page_size: int = 50,
    delay: float = 0.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if page_size < 1 or page_size > 500:
        raise ValueError("page_size must be between 1 and 500")
    client.select_term(term_code)
    retrieved_at = utc_now()
    source_url = client.url(RESULTS_PATH)
    offset = 0
    expected_total: int | None = None
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    pages = 0
    while True:
        envelope = client.get_json(
            RESULTS_PATH,
            query={
                "txt_term": term_code,
                "pageOffset": offset,
                "pageMaxSize": page_size,
                "sortColumn": "subjectDescription",
                "sortDirection": "asc",
            },
            referer=client.url("/classSearch/classSearch"),
        )
        if not isinstance(envelope, dict) or envelope.get("success") is not True:
            raise BannerError(f"Banner result envelope was unsuccessful for term {term_code}")
        data = envelope.get("data")
        total = envelope.get("totalCount")
        if not isinstance(data, list) or not isinstance(total, int) or total < 0:
            raise BannerError(f"Banner result envelope was malformed for term {term_code}")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise BannerError(f"Banner totalCount changed during pagination for term {term_code}")
        pages += 1
        before = len(by_identity)
        for raw in data:
            record = normalize_section(raw, term_code, term_label, retrieved_at, source_url)
            identity = (record["term_code"], record["crn"])
            existing = by_identity.get(identity)
            if existing is not None and existing != record:
                raise BannerError(f"conflicting duplicate section identity {term_code}/{record['crn']}")
            by_identity[identity] = record
        if len(by_identity) >= total:
            break
        if not data or len(by_identity) == before:
            raise BannerError(f"pagination stalled before totalCount for term {term_code}")
        offset += len(data)
        if delay:
            time.sleep(delay)
    complete = len(by_identity) == (expected_total or 0)
    rows = sorted(by_identity.values(), key=lambda row: (row["subject"], row["course_number"], row["section"] or "", row["crn"]))
    metadata = {
        "term_code": term_code,
        "term_label": term_label,
        "status": "success" if complete else "incomplete",
        "complete": complete,
        "expected_count": expected_total,
        "record_count": len(rows),
        "page_count": pages,
        "retrieved_at": retrieved_at,
        "source_url": source_url,
    }
    return rows, metadata


def rows_digest(rows: Iterable[dict[str, Any]]) -> str:
    body = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    return hashlib.sha256(body.encode()).hexdigest()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: record must be an object")
            rows.append(value)
    return rows


def write_scan(path: Path, rows: list[dict[str, Any]], title: str, generated_at: str) -> None:
    lines = [f"# {title}", "", f"Generated: {generated_at}", f"Sections: {len(rows)}", "", "| Course | Title | Term | Sections |", "|---|---|---|---:|"]
    groups: dict[tuple[str, str, str], int] = {}
    for row in rows:
        key = (row["course_display"], row["title"], row["term_label"])
        groups[key] = groups.get(key, 0) + 1
    for (course, course_title, term), count in sorted(groups.items()):
        lines.append(f"| {course} | {course_title.replace('|', '\\|')} | {term} | {count} |")
    from discover_public_terms import atomic_write_bytes

    atomic_write_bytes(path, ("\n".join(lines) + "\n").encode())


def load_resume_rows(archive: Path, state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if not archive.exists():
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in read_jsonl(archive):
        grouped.setdefault(str(row.get("term_code", "")), []).append(row)
    valid: dict[str, list[dict[str, Any]]] = {}
    for term_code, rows in grouped.items():
        prior = (state.get("terms") or {}).get(term_code) or {}
        if prior.get("status") == "success" and prior.get("record_count") == len(rows) and prior.get("sha256") == rows_digest(rows):
            valid[term_code] = rows
    return valid


def collect_all(args: argparse.Namespace) -> int:
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    terms_path: Path = args.terms_file or output / "public-terms.json"
    terms_artifact = discover_terms(BannerSession(args.base_url, args.timeout), args.term_page_size, args.delay)
    atomic_write_json(terms_path, terms_artifact)
    terms = terms_artifact["terms"]
    exact_codes = {term["code"] for term in terms}
    if args.current_term and args.current_term not in exact_codes:
        raise ValueError("--current-term must be an exact code returned by the public selector")
    state_path = output / "course-fetch-state.json"
    prior_state = read_json(state_path) if args.resume and state_path.exists() else {"terms": {}}
    archive_path = output / "historical-sections.jsonl"
    retained = load_resume_rows(archive_path, prior_state) if args.resume else {}
    all_rows: list[dict[str, Any]] = []
    term_results: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    for term in terms:
        code, label = term["code"], term["description"]
        must_refresh = not args.resume or not args.current_term or code >= args.current_term or code not in retained
        if not must_refresh:
            rows = retained[code]
            result = dict(prior_state["terms"][code], resumed=True)
            print(f"Retained {code}: {len(rows)} records (count/hash verified)")
        else:
            try:
                rows, result = fetch_term(BannerSession(args.base_url, args.timeout), code, label, page_size=args.page_size, delay=args.delay)
                result["sha256"] = rows_digest(rows)
                result["resumed"] = False
                print(f"Fetched {code}: {len(rows)}/{result['expected_count']} records")
            except (BannerError, OSError, ValueError) as exc:
                rows = retained.get(code, [])
                result = {
                    "term_code": code,
                    "term_label": label,
                    "status": "failed",
                    "complete": False,
                    "record_count": len(rows),
                    "expected_count": None,
                    "retrieved_at": utc_now(),
                    "error": str(exc),
                    "retained_prior_rows": bool(rows),
                }
                failures.append(result)
                print(f"Failed {code}: {exc}", file=sys.stderr)
        all_rows.extend(rows)
        term_results[code] = result
        checkpoint = {
            "schema_version": SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "updated_at": utc_now(),
            "terms": term_results,
        }
        atomic_write_json(state_path, checkpoint)
    identities = [(row["term_code"], row["crn"]) for row in all_rows]
    if len(identities) != len(set(identities)):
        print("archive construction failed: duplicate (term_code, crn)", file=sys.stderr)
        return 1
    all_rows.sort(key=lambda row: (row["term_code"], row["subject"], row["course_number"], row["section"] or "", row["crn"]))
    generated_at = utc_now()
    atomic_write_jsonl(archive_path, all_rows)
    complete_codes = [code for code, result in term_results.items() if result.get("complete")]
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": generated_at,
        "artifact": str(archive_path),
        "detail_level": "listing",
        "record_count": len(all_rows),
        "discovered_term_count": len(terms),
        "complete_term_count": len(complete_codes),
        "incomplete_term_count": len(terms) - len(complete_codes),
        "coverage": terms_artifact["coverage"],
        "complete": len(complete_codes) == len(terms),
        "terms": term_results,
        "source_url": BannerSession(args.base_url).url(RESULTS_PATH),
    }
    atomic_write_json(output / "historical-sections.meta.json", metadata)
    atomic_write_json(output / "course-fetch-failures.json", {"generated_at": generated_at, "failures": failures})
    write_scan(output / "course-scan.md", all_rows, "Public Course Archive Scan", generated_at)
    print(f"Archive: {len(all_rows)} sections; complete terms {len(complete_codes)}/{len(terms)}")
    return 0 if metadata["complete"] else 2


def collect_one(args: argparse.Namespace) -> int:
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=True)
    terms_path: Path = args.terms_file or output / "public-terms.json"
    if terms_path.exists():
        artifact = read_json(terms_path)
    else:
        artifact = discover_terms(BannerSession(args.base_url, args.timeout), args.term_page_size, args.delay)
        atomic_write_json(terms_path, artifact)
    matches = [term for term in artifact.get("terms", []) if term.get("code") == args.term]
    if len(matches) != 1:
        print(f"term {args.term!r} is not an exact code in the public selector", file=sys.stderr)
        return 1
    rows, metadata = fetch_term(BannerSession(args.base_url, args.timeout), args.term, matches[0]["description"], page_size=args.page_size, delay=args.delay)
    detail_failures: list[dict[str, str]] = []
    if args.enrich_details:
        from fetch_course_details import cache_path, fetch_details

        for index, row in enumerate(rows, 1):
            location = cache_path(args.detail_cache_dir, args.term, row["crn"])
            try:
                if location.exists() and not args.refresh_details:
                    details = read_json(location)
                else:
                    details = fetch_details(BannerSession(args.base_url, args.timeout), args.term, row["crn"])
                    atomic_write_json(location, details)
                if details.get("term_code") != args.term or details.get("crn") != row["crn"]:
                    raise ValueError("detail cache identity mismatch")
                for field in (
                    "description",
                    "prerequisites",
                    "corequisites",
                    "restrictions",
                    "mutual_exclusions",
                    "catalog_details",
                    "linked_sections",
                    "cross_listed_sections",
                ):
                    row[field] = details.get(field)
                row["detail_level"] = "enriched"
                row["detail_status"] = details.get("detail_status", "partial")
            except (BannerError, OSError, ValueError, json.JSONDecodeError) as exc:
                row["detail_status"] = "failed"
                detail_failures.append({"term_code": args.term, "crn": row["crn"], "error": str(exc)})
            if args.detail_delay and index < len(rows):
                time.sleep(args.detail_delay)
    metadata.update(
        {
            "schema_version": SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "detail_level": "enriched" if args.enrich_details else "listing",
            "detail_failure_count": len(detail_failures),
            "detail_failures": detail_failures,
            "sha256": rows_digest(rows),
        }
    )
    atomic_write_jsonl(output / "current-sections.jsonl", rows)
    atomic_write_json(output / "current-sections.meta.json", metadata)
    write_scan(output / "current-course-scan.md", rows, f"Current Snapshot Scan — {metadata['term_label']}", metadata["retrieved_at"])
    print(f"Current snapshot {args.term}: {len(rows)} sections -> {output / 'current-sections.jsonl'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all-public-terms", action="store_true")
    mode.add_argument("--term")
    parser.add_argument("--output", type=Path, default=Path("resources/courses"))
    parser.add_argument("--terms-file", type=Path)
    parser.add_argument("--resume", action="store_true", help="reuse complete past terms only when stored count/hash match")
    parser.add_argument("--current-term", help="with --resume, always refresh this exact code and lexically later codes")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--term-page-size", type=int, default=10)
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--enrich-details", action="store_true", help="fully enrich an explicit term; never used for all historical terms")
    parser.add_argument("--detail-cache-dir", type=Path, default=Path("resources/courses/.cache/details"))
    parser.add_argument("--refresh-details", action="store_true")
    parser.add_argument("--detail-delay", type=float, default=0.1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return collect_all(args) if args.all_public_terms else collect_one(args)
    except (BannerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"course fetch failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
