from __future__ import annotations

import contextlib
import copy
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

    def level_details(self, name, row=None):
        row = row or self.rows[0]
        fragments = json.loads((FIXTURES / "level-fragments.json").read_text())
        return {
            "term_code": row["term_code"], "crn": row["crn"],
            "retrieved_at": "2099-09-01T00:00:00Z",
            "_raw_fragments": {"catalog_details": fragments[name]}, "failures": {},
        }

    def level_row(self, name, **changes):
        row = copy.deepcopy(self.rows[0])
        row.update(changes)
        row.update(fetch_course_details.course_level_fields(self.level_details(name, row)))
        return row

    def query_rows(self, rows, *flags):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sections.jsonl"
            discover_public_terms.atomic_write_jsonl(path, rows)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = query_courses.main(["--input", str(path), *flags])
            return status, output.getvalue()

    def test_level_parser_uses_only_published_levels_block(self):
        ug = fetch_course_details.course_level_fields(self.level_details("undergraduate"))
        self.assertEqual(ug["course_levels"], [{"code": "UG", "description": "Undergraduate"}])
        gr = fetch_course_details.course_level_fields(self.level_details("graduate"))
        self.assertEqual(gr["course_levels"], [{"code": "GR", "description": "Graduate"}])
        both = fetch_course_details.course_level_fields(self.level_details("multiple"))
        self.assertEqual([level["code"] for level in both["course_levels"]], ["UG", "GR"])
        self.assertIn("getSectionCatalogDetails?term=", gr["course_level_metadata"]["source_url"])
        self.assertEqual(gr["course_level_metadata"]["retrieved_at"], "2099-09-01T00:00:00Z")

    def test_missing_malformed_and_failed_level_detail_stays_unknown(self):
        for name, expected in [("absent", "not_published"), ("empty", "not_published"), ("unrecognized", "unrecognized"), ("unbounded", "unrecognized")]:
            result = fetch_course_details.course_level_fields(self.level_details(name))
            self.assertEqual(result["course_levels"], [], name)
            self.assertEqual(result["course_level_metadata"]["status"], expected, name)
        details = self.level_details("graduate")
        details["failures"] = {"catalog_details": "synthetic outage"}
        result = fetch_course_details.course_level_fields(details)
        self.assertEqual(result["course_levels"], [])
        self.assertEqual(result["course_level_metadata"]["status"], "failed")

    def test_level_parser_accepts_public_cleaned_detail_json(self):
        details = self.level_details("graduate")
        fragment = details.pop("_raw_fragments")["catalog_details"]
        details["catalog_details"] = fetch_course_details.clean_detail(fragment, "catalog_details")
        self.assertEqual(fetch_course_details.course_level_fields(details)["course_levels"], [{"code": "GR", "description": "Graduate"}])

    def test_level_filter_is_exact_and_never_guesses_numbering(self):
        rows = [self.level_row("undergraduate", course_number="9000"), self.level_row("graduate", crn="90002", course_number="1000")]
        for flag in ["GR", "graduate", "Graduate"]:
            status, output = self.query_rows(rows, "--level", flag, "--format", "json")
            self.assertEqual(status, 0)
            self.assertEqual([r["crn"] for r in json.loads(output)["records"]], ["90002"])
        status, output = self.query_rows(rows, "--level", "grad", "--format", "json")
        self.assertEqual(json.loads(output)["match_count"], 0)

    def test_unknown_level_is_excluded_but_reported_not_as_absence(self):
        rows = [self.level_row("absent", course_number="5000", title="Graduate Machine Learning")]
        status, output = self.query_rows(rows, "--level", "Graduate", "--format", "json")
        result = json.loads(output)
        self.assertEqual(status, 2)
        self.assertEqual(result["match_count"], 0)
        self.assertEqual(result["metadata"]["level_query"]["unknown_level_count"], 1)
        self.assertEqual(result["metadata"]["level_query"]["status"], "incomplete_level_evidence")

    def test_history_requires_level_or_exact_code_before_frequency(self):
        for selector in [["--subject", "SYN"], ["--course", "1000"]]:
            status, output = self.query_rows(self.rows, *selector, "--format", "history")
            result = json.loads(output)
            self.assertEqual(status, 2)
            self.assertEqual(result["courses"], [])
            self.assertEqual(result["query_status"], "clarification_required")
        status, output = self.query_rows(self.rows, "--course", "SYN1000", "--format", "history")
        self.assertEqual(status, 0)
        result = json.loads(output)
        self.assertEqual(result["courses"][0]["course_level_status"], "unknown")
        self.assertTrue(result["metadata"]["level_query"]["warnings"])

    def test_history_separates_known_and_unknown_levels_for_same_code(self):
        rows = [self.level_row("undergraduate"), self.level_row("graduate", crn="90002"), self.level_row("absent", crn="90003")]
        result = build_course_history.build_history(rows, "synthetic")
        self.assertEqual(result["course_count"], 3)
        self.assertEqual([c["section_count"] for c in result["courses"]], [1, 1, 1])
        self.assertEqual(sum(len(c["section_identities"]) for c in result["courses"]), 3)
        status, output = self.query_rows(rows, "--course", "SYN1000", "--format", "history")
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output)["query_status"], "clarification_required")

    def test_same_title_different_codes_are_not_merged_after_level_filter(self):
        rows = [self.level_row("graduate"), self.level_row("graduate", crn="90002", subject="OTHER", course_display="OTHER 1000")]
        status, output = self.query_rows(rows, "--level", "GR", "--format", "history")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output)["course_count"], 2)

    def test_offline_detail_overlay_preserves_archive_and_enrollment_time(self):
        row = self.rows[0]
        with tempfile.TemporaryDirectory() as directory:
            path = fetch_course_details.cache_path(Path(directory), row["term_code"], row["crn"])
            discover_public_terms.atomic_write_json(path, self.level_details("graduate"))
            original = copy.deepcopy(row)
            overlaid = query_courses.with_cached_levels(row, Path(directory))
            self.assertEqual(row, original)
            self.assertEqual(overlaid["retrieved_at"], original["retrieved_at"])
            self.assertEqual(overlaid["enrollment"], original["enrollment"])
            self.assertEqual(overlaid["course_levels"][0]["code"], "GR")
            details = self.level_details("graduate")
            details["crn"] = "wrong"
            discover_public_terms.atomic_write_json(path, details)
            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                query_courses.with_cached_levels(row, Path(directory))

    def test_new_level_fields_validate_without_invalidating_legacy_rows(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas/course-section.schema.json").read_text())
        for row in [self.rows[0], self.level_row("graduate"), self.level_row("absent")]:
            jsonschema.validate(row, schema)

    def test_level_aware_human_formats_show_published_level(self):
        for output_format in ["scan", "table", "full"]:
            status, output = self.query_rows([self.level_row("undergraduate")], "--format", output_format)
            self.assertEqual(status, 0)
            self.assertIn("Undergraduate (UG)", output)

    def test_enriched_snapshot_persists_levels_without_refreshing_listing_time(self):
        for fail in [False, True]:
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                row = copy.deepcopy(self.rows[0])
                term = row["term_code"]
                discover_public_terms.atomic_write_json(output / "public-terms.json", {"terms": [{"code": term, "description": "Synthetic term"}]})
                args = fetch_public_courses.build_parser().parse_args(["--term", term, "--enrich-details", "--output", directory, "--detail-cache-dir", str(output / "details")])
                metadata = {"term_label": "Synthetic term", "retrieved_at": row["retrieved_at"]}
                details = self.level_details("graduate", row)
                details["detail_status"] = "success"
                with mock.patch.object(fetch_public_courses, "fetch_term", return_value=([row], metadata)), mock.patch.object(fetch_course_details, "fetch_details", return_value=details, side_effect=discover_public_terms.BannerError("synthetic outage") if fail else None), contextlib.redirect_stdout(io.StringIO()):
                    fetch_public_courses.collect_one(args)
                persisted = fetch_public_courses.read_jsonl(output / "current-sections.jsonl")[0]
                self.assertEqual(persisted["retrieved_at"], self.rows[0]["retrieved_at"])
                self.assertEqual(persisted["enrollment"], self.rows[0]["enrollment"])
                if fail:
                    self.assertEqual(persisted["course_levels"], [])
                    self.assertEqual(persisted["course_level_metadata"]["status"], "failed")
                else:
                    self.assertEqual(persisted["course_levels"][0]["code"], "GR")
                    self.assertEqual(persisted["course_level_metadata"]["retrieved_at"], details["retrieved_at"])

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
