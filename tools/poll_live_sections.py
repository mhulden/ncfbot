#!/usr/bin/env python3
"""Poll fresh public enrollment fields for explicitly shortlisted CRNs."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from discover_public_terms import DEFAULT_BASE_URL, BannerError, BannerSession, utc_now
from fetch_public_courses import RESULTS_PATH, enrollment_observation


def poll(client: BannerSession, term: str, crns: list[str]) -> dict[str, Any]:
    requested = list(dict.fromkeys(str(crn).strip() for crn in crns if str(crn).strip()))
    if not requested:
        raise ValueError("at least one nonempty CRN is required")
    client.select_term(term)
    retrieved_at = utc_now()
    results: list[dict[str, Any]] = []
    for crn in requested:
        envelope = client.get_json(
            RESULTS_PATH,
            query={
                "txt_term": term,
                "txt_courseReferenceNumber": crn,
                "pageOffset": 0,
                "pageMaxSize": 10,
                "sortColumn": "subjectDescription",
                "sortDirection": "asc",
            },
            referer=client.url("/classSearch/classSearch"),
        )
        if not isinstance(envelope, dict) or envelope.get("success") is not True or not isinstance(envelope.get("data"), list):
            raise BannerError(f"live result envelope failed for term {term}, CRN {crn}")
        exact = [
            row
            for row in envelope["data"]
            if isinstance(row, dict)
            and str(row.get("term", "")) == term
            and str(row.get("courseReferenceNumber", "")) == crn
        ]
        if len(exact) != 1:
            raise BannerError(f"live lookup returned {len(exact)} exact records for term {term}, CRN {crn}")
        raw = exact[0]
        observation = enrollment_observation(raw, retrieved_at)
        if observation is None:
            results.append({"term_code": term, "crn": crn, "fields_returned": [], "enrollment": None})
            continue
        observation["freshness"] = "live"
        fields = [key for key, value in observation.items() if key not in {"retrieved_at", "freshness"} and value is not None]
        results.append(
            {
                "term_code": term,
                "crn": crn,
                "course_display": " ".join(
                    value for value in [str(raw.get("subject") or "").strip(), str(raw.get("courseNumber") or "").strip()] if value
                ),
                "section": raw.get("sequenceNumber"),
                "title": raw.get("courseTitle"),
                "fields_returned": fields,
                "enrollment": observation,
            }
        )
    return {
        "status": "success",
        "current": True,
        "term_code": term,
        "retrieved_at": retrieved_at,
        "source_url": client.url(RESULTS_PATH),
        "sections": results,
        "warning": "Seat availability does not establish registration eligibility.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--term", required=True)
    parser.add_argument("--crn", action="append", required=True, help="repeat for additional shortlisted CRNs")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = poll(BannerSession(args.base_url, args.timeout), args.term, args.crn)
    except (BannerError, OSError, ValueError) as exc:
        result = {
            "status": "failed",
            "current": False,
            "term_code": args.term,
            "requested_crns": args.crn,
            "retrieved_at": utc_now(),
            "sections": [],
            "error": str(exc),
            "warning": "Current availability could not be verified; no cached value is labeled current.",
        }
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
