from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
FIXTURES = Path(__file__).parent / "fixtures" / "courses"
sys.path.insert(0, str(TOOLS))

import build_course_history
import discover_public_terms
import fetch_course_details
import fetch_public_courses
import poll_live_sections
import query_courses


class FakeTermClient:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.bootstrapped = False
        self.offsets = []

    def bootstrap(self):
        self.bootstrapped = True

    def get_json(self, _path, **kwargs):
        self.offsets.append(kwargs["query"]["offset"])
        return next(self.pages)

    def url(self, path):
        return "https://example.edu" + path


class FakeListingClient:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.selected = None

    def select_term(self, term):
        self.selected = term

    def get_json(self, _path, **_kwargs):
        return next(self.pages)

    def url(self, path):
        return "https://example.edu" + path


class CourseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.term_pages = json.loads((FIXTURES / "term-pages.json").read_text())
        cls.listing_pages = json.loads((FIXTURES / "listing-pages.json").read_text())
        cls.rows = fetch_public_courses.read_jsonl(FIXTURES / "normalized-sections.jsonl")

    def test_term_pagination_and_exact_deduplication(self):
        client = FakeTermClient(self.term_pages)
        artifact = discover_public_terms.discover_terms(client, page_size=2)
        self.assertEqual([term["code"] for term in artifact["terms"]], ["209908", "209905", "209902"])
        self.assertEqual(artifact["term_count"], 3)
        self.assertEqual(artifact["coverage"]["earliest_term_code"], "209902")
        self.assertEqual(client.offsets, [1, 2, 3])

    def test_fuzzy_term_search_value_is_not_interpreted_as_year(self):
        term = discover_public_terms.normalize_term({"code": "202008", "description": "Fall 2020"}, "2026-01-01T00:00:00Z")
        self.assertEqual(term["code"], "202008")
        self.assertFalse(term["view_only"])

    def test_session_bootstrap_failure_is_explicit(self):
        session = discover_public_terms.BannerSession("http://localhost:1", timeout=0.01)
        session.opener.open = mock.Mock(side_effect=urllib.error.URLError("offline"))
        with self.assertRaises(discover_public_terms.BannerError):
            session.bootstrap()

    def test_banner_session_rejects_unapproved_https_host(self):
        with self.assertRaises(ValueError):
            discover_public_terms.BannerSession("https://example.com/banner")

    def test_banner_redirect_handler_rejects_cross_origin(self):
        handler = discover_public_terms.SameOriginRedirectHandler(
            ("https", "banapps02.ncf.edu", None)
        )
        request = discover_public_terms.urllib.request.Request(
            "https://banapps02.ncf.edu/start"
        )
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://example.com/login",
            )

    def test_results_pagination_and_section_identity(self):
        rows, metadata = fetch_public_courses.fetch_term(FakeListingClient(self.listing_pages), "209908", "Fall 2099", page_size=2)
        self.assertEqual(len(rows), 3)
        self.assertTrue(metadata["complete"])
        self.assertEqual(metadata["page_count"], 2)
        self.assertEqual(len({(row["term_code"], row["crn"]) for row in rows}), 3)

    def test_partial_term_pagination_cannot_look_complete(self):
        partial = [{"success": True, "totalCount": 3, "data": self.listing_pages[0]["data"]}, {"success": True, "totalCount": 3, "data": []}]
        with self.assertRaises(discover_public_terms.BannerError):
            fetch_public_courses.fetch_term(FakeListingClient(partial), "209908", "Fall 2099", page_size=2)

    def test_conflicting_duplicate_section_is_rejected(self):
        first = self.listing_pages[0]["data"][0]
        changed = dict(first, courseTitle="Different title")
        pages = [{"success": True, "totalCount": 2, "data": [first]}, {"success": True, "totalCount": 2, "data": [changed]}]
        with self.assertRaises(discover_public_terms.BannerError):
            fetch_public_courses.fetch_term(FakeListingClient(pages), "209908", "Fall 2099", page_size=1)

    def test_normalization_preserves_meeting_and_snapshot_label(self):
        row = fetch_public_courses.normalize_section(
            self.listing_pages[0]["data"][0], "209908", "Fall 2099", "2099-08-01T12:00:00Z", "https://example.edu/results"
        )
        self.assertEqual(row["course_display"], "SYN 1000")
        self.assertIn("Mon/Wed", row["meeting_summary"])
        self.assertEqual(row["enrollment"]["freshness"], "snapshot")
        self.assertEqual(row["detail_level"], "listing")

    def test_missing_optional_fields_remain_null_or_empty(self):
        raw = {"term": "209908", "courseReferenceNumber": "1"}
        row = fetch_public_courses.normalize_section(raw, "209908", "Fall 2099", "2099-01-01T00:00:00Z", "https://example.edu/results")
        self.assertIsNone(row["section"])
        self.assertEqual(row["instructors"], [])
        self.assertIsNone(row["description"])
        self.assertIsNone(row["enrollment"])

    def test_atomic_write_does_not_replace_original_on_generation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl"
            path.write_text("original\n")

            def broken():
                yield {"ok": True}
                raise RuntimeError("interrupted")

            with self.assertRaises(RuntimeError):
                discover_public_terms.atomic_write_jsonl(path, broken())
            self.assertEqual(path.read_text(), "original\n")

    def test_resume_requires_matching_count_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "historical-sections.jsonl"
            discover_public_terms.atomic_write_jsonl(archive, self.rows)
            grouped = {}
            for row in self.rows:
                grouped.setdefault(row["term_code"], []).append(row)
            state = {
                "terms": {
                    code: {"status": "success", "record_count": len(rows), "sha256": fetch_public_courses.rows_digest(rows)}
                    for code, rows in grouped.items()
                }
            }
            retained = fetch_public_courses.load_resume_rows(archive, state)
            self.assertEqual(set(retained), {"209902", "209908"})
            state["terms"]["209908"]["record_count"] = 999
            self.assertNotIn("209908", fetch_public_courses.load_resume_rows(archive, state))

    def test_history_groups_exact_code_without_collapsing_sections(self):
        history = build_course_history.build_history(self.rows, "fixture")
        syn = next(course for course in history["courses"] if course["course_display"] == "SYN 1000")
        self.assertEqual(syn["section_count"], 3)
        self.assertEqual(len(syn["section_identities"]), 3)
        self.assertIn("Earlier Synthetic Systems", syn["titles"])

    def test_detail_html_cleaning_and_unavailable_text(self):
        fragments = json.loads((FIXTURES / "detail-fragments.json").read_text())
        self.assertEqual(fetch_course_details.clean_detail(fragments["description"], "description"), "A synthetic description.")
        self.assertEqual(fetch_course_details.clean_detail(fragments["prerequisites"], "prerequisites"), "Permission of instructor.")
        self.assertIsNone(fetch_course_details.clean_detail(fragments["corequisites"], "corequisites"))
        self.assertIn("Credit Hours", fetch_course_details.clean_detail(fragments["catalog_details"], "catalog_details"))

    def test_on_demand_detail_fetch_requests_every_public_tab(self):
        fragments = json.loads((FIXTURES / "detail-fragments.json").read_text())

        class DetailsClient:
            def __init__(self):
                self.selected = None
                self.paths = []

            def select_term(self, term):
                self.selected = term

            def request(self, path, **_kwargs):
                self.paths.append(path)
                endpoint = path.rsplit("/", 1)[-1]
                field = next(name for name, value in fetch_course_details.DETAIL_ENDPOINTS.items() if value == endpoint)
                fragment = fragments.get(field, f"<section>No {field.replace('_', ' ')} information available.</section>")
                return fragment.encode(), "text/html"

            def url(self, path):
                return "https://example.edu" + path

        client = DetailsClient()
        result = fetch_course_details.fetch_details(client, "209908", "90001")
        self.assertEqual(client.selected, "209908")
        self.assertEqual(len(client.paths), 8)
        self.assertEqual(result["description"], "A synthetic description.")
        self.assertEqual(result["detail_status"], "success")

    def test_query_filters(self):
        parser = query_courses.build_parser()
        cases = [
            (["--subject", "SYN"], 3),
            (["--course", "SYN1000"], 3),
            (["--crn", "90001"], 1),
            (["--section", "002"], 1),
            (["--term", "209902"], 1),
            (["--instructor", "Grace"], 1),
            (["--keyword", "fuzzy"], 1),
            (["--attribute", "Studio"], 1),
        ]
        for flags, expected in cases:
            args = parser.parse_args(["--input", str(FIXTURES / "normalized-sections.jsonl"), *flags])
            self.assertEqual(sum(query_courses.record_matches(row, args) for row in self.rows), expected, flags)

    def test_all_query_output_formats(self):
        for output_format in ("scan", "table", "history", "full", "json", "jsonl"):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                status = query_courses.main(["--input", str(FIXTURES / "normalized-sections.jsonl"), "--course", "SYN1000", "--format", output_format])
            self.assertEqual(status, 0)
            self.assertTrue(stream.getvalue().strip())

    def test_snapshot_timestamp_and_incompleteness_are_displayed(self):
        metadata = json.loads((FIXTURES / "historical-sections.meta.json").read_text())
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            query_courses.print_context(4, metadata)
        output = stream.getvalue()
        self.assertIn("2099-08-01T12:00:00Z", output)
        self.assertIn("WARNING: archive is incomplete", output)

    def test_malformed_jsonl_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text("[]\n")
            with self.assertRaises(ValueError):
                fetch_public_courses.read_jsonl(path)

    def test_synthetic_rows_contain_every_schema_required_key(self):
        schema = json.loads((ROOT / "schemas" / "course-section.schema.json").read_text())
        for row in self.rows:
            self.assertEqual(set(schema["required"]) - set(row), set())

    def test_no_match_is_honest_empty_result(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            status = query_courses.main(["--input", str(FIXTURES / "normalized-sections.jsonl"), "--course", "NONE9999", "--format", "scan"])
        self.assertEqual(status, 0)
        self.assertIn("Matched sections: 0", stream.getvalue())

    def test_course_evaluation_contract_and_unique_ids(self):
        required = {
            "id", "audience", "topic", "question", "expected_skill", "expected_resource_ids",
            "must_include", "must_not_include", "clarification_expected", "citation_required",
            "freshness_sensitive", "notes",
        }
        path = ROOT / "evaluations" / "questions" / "courses.jsonl"
        with path.open() as handle:
            cases = [json.loads(line) for line in handle if line.strip()]
        self.assertGreaterEqual(len(cases), 30)
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertTrue(all(required <= set(case) for case in cases))

    def test_live_poll_marks_only_successful_response_current(self):
        raw = dict(self.listing_pages[0]["data"][0])
        client = FakeListingClient([{"success": True, "totalCount": 1, "data": [raw]}])
        result = poll_live_sections.poll(client, "209908", ["90001"])
        self.assertTrue(result["current"])
        self.assertEqual(result["sections"][0]["enrollment"]["freshness"], "live")

    def test_live_failure_never_returns_cached_current_value(self):
        class Broken:
            def __init__(self, *_args, **_kwargs):
                pass

            def select_term(self, _term):
                raise discover_public_terms.BannerError("synthetic outage")

        stderr = io.StringIO()
        with mock.patch.object(poll_live_sections, "BannerSession", Broken), contextlib.redirect_stderr(stderr):
            status = poll_live_sections.main(["--term", "209908", "--crn", "90001"])
        self.assertEqual(status, 1)
        failure = json.loads(stderr.getvalue())
        self.assertFalse(failure["current"])
        self.assertEqual(failure["sections"], [])


if __name__ == "__main__":
    unittest.main()
