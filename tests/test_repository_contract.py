import hashlib
import json
from pathlib import Path

from ncfbot.doctor import REQUIRED_FILES, run_doctor


ROOT = Path(__file__).resolve().parents[1]


def _complete_synthetic_repository(root: Path) -> Path:
    for relative in REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.startswith("tools/"):
            path.write_text("import argparse\nargparse.ArgumentParser().parse_args()\n", encoding="utf-8")
        else:
            path.write_text("{}" if path.suffix == ".json" else "placeholder\n", encoding="utf-8")
    evaluation_specs = {
        "students.jsonl": (30, "students", "skills/students.md"),
        "faculty.jsonl": (30, "faculty", "skills/faculty.md"),
        "outside.jsonl": (30, "outside", "skills/outside.md"),
        "courses.jsonl": (30, "students", "skills/students.md"),
        "cross-cutting.jsonl": (40, "ambiguous", None),
    }
    for filename, (count, audience, skill) in evaluation_specs.items():
        lines = []
        prefix = filename.removesuffix(".jsonl")
        for index in range(count):
            lines.append(json.dumps({
                "id": f"{prefix}-case-{index}", "audience": audience, "topic": "synthetic",
                "question": "How does this work?", "expected_skill": skill, "expected_resource_ids": [],
                "must_include": [], "must_not_include": [], "clarification_expected": audience == "ambiguous",
                "citation_required": False, "freshness_sensitive": False, "notes": "synthetic fixture",
            }))
        (root / "evaluations/questions" / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / "PLAN-distributed.md").write_text("integration contract\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "Use skills/students.md, skills/faculty.md, or skills/outside.md.\n", encoding="utf-8"
    )
    resource = root / "resources/shared/sample.md"
    resource.parent.mkdir(parents=True)
    resource.write_text(
        "# Sample\n\nScope statement.\n\nVerified through: 2026-08-31\n\n## Facts\n\nSynthetic evidence.\n\n## Sources\n\n- https://www.ncf.edu/sample\n",
        encoding="utf-8",
    )
    source_bytes = b"synthetic public response"
    sidecar = {
        "id": "sample",
        "resource_file": "resources/shared/sample.md",
        "title": "Sample",
        "audiences": ["students", "faculty", "outside"],
        "topics": ["sample"],
        "sources": [{
            "canonical_url": "https://www.ncf.edu/sample",
            "publisher": "NCF",
            "authority_type": "office",
            "retrieved_at": "2026-08-31T12:00:00Z",
            "last_modified": None,
            "effective_from": None,
            "effective_through": None,
            "academic_year": None,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "public_access_verified": True,
        }],
        "status": "current",
        "volatility": "stable",
        "review_after": "2099-01-01",
        "notes": "synthetic fixture",
    }
    sidecar_path = resource.with_name("sample.source.json")
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    generated = root / "resources/generated"
    generated.mkdir(parents=True)
    manifest = {
        "schema_version": "1",
        "generated_at": "2026-08-31T12:00:00Z",
        "resources": [{"sidecar_file": "resources/shared/sample.source.json", "record": sidecar}],
    }
    (generated / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    courses = root / "resources/courses"
    courses.mkdir(parents=True)
    (courses / "course-scan.md").write_text(
        "# Synthetic generated course scan\n", encoding="utf-8"
    )
    (courses / "current-course-scan.md").write_text(
        "# Synthetic generated current scan\n", encoding="utf-8"
    )
    (courses / "public-terms.json").write_text(
        json.dumps({"terms": [{"term_code": "202601", "complete": True}]}), encoding="utf-8"
    )
    (courses / "historical-sections.jsonl").write_text(
        json.dumps({
            "term_code": "202601", "term_label": "Synthetic Term", "subject": "TST",
            "course_number": "1000", "course_display": "TST 1000", "section": "001",
            "crn": "12345", "title": "Synthetic Course", "instructors": [], "meetings": [],
            "meeting_summary": None, "credits_or_units": None, "attributes": [], "description": None,
            "prerequisites": None, "corequisites": None, "restrictions": None, "detail_level": "listing",
            "source_url": "https://example.edu/public-course-search", "retrieved_at": "2026-08-31T12:00:00Z",
        }) + "\n",
        encoding="utf-8",
    )
    return root


def test_doctor_passes_a_complete_offline_contract(tmp_path):
    report = run_doctor(_complete_synthetic_repository(tmp_path))
    assert report.ok, [issue.message for issue in report.issues]
    assert report.issues == ()


def test_doctor_catches_incomplete_archive(tmp_path):
    root = _complete_synthetic_repository(tmp_path)
    (root / "resources/courses/public-terms.json").write_text(
        json.dumps({"terms": [{"term_code": "202601", "complete": False}]}), encoding="utf-8"
    )
    report = run_doctor(root)
    assert not report.ok
    assert any("marks term incomplete" in issue.message for issue in report.issues)


def test_doctor_reports_missing_upstream_files_clearly(tmp_path):
    (tmp_path / "PLAN-distributed.md").write_text("synthetic incomplete repository\n", encoding="utf-8")
    report = run_doctor(tmp_path)
    assert not report.ok
    messages = {issue.message for issue in report.issues}
    assert "missing required file: skills/students.md" in messages
    assert "missing resources directory" in messages


def test_default_checks_are_offline(tmp_path):
    report = run_doctor(_complete_synthetic_repository(tmp_path))
    assert all(not issue.network for issue in report.issues)
