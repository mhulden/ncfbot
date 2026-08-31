import json
from pathlib import Path

from ncfbot.evaluation import duplicate_case_ids, read_cases, run_evaluation, validate_case


ROOT = Path(__file__).resolve().parents[1]


def test_cross_cutting_corpus_is_large_and_valid():
    cases, errors = read_cases(ROOT)
    cross_cutting = [item for item in cases if item.path.name == "cross-cutting.jsonl"]
    assert len(cross_cutting) >= 40
    assert errors == []
    assert duplicate_case_ids(cases) == []


def test_schema_is_valid_json_and_names_contract_fields():
    schema = json.loads((ROOT / "schemas/evaluation-case.schema.json").read_text())
    assert schema["type"] == "object"
    assert set(schema["required"]) == {
        "id", "audience", "topic", "question", "expected_skill",
        "expected_resource_ids", "must_include", "must_not_include",
        "clarification_expected", "citation_required", "freshness_sensitive", "notes",
    }


def test_validator_rejects_unknown_fields():
    case = {
        "id": "valid-id", "audience": "students", "topic": "test", "question": "Question?",
        "expected_skill": "skills/students.md", "expected_resource_ids": [], "must_include": [],
        "must_not_include": [], "clarification_expected": False, "citation_required": False,
        "freshness_sensitive": False, "notes": "", "surprise": True,
    }
    assert any("unknown field surprise" in error for error in validate_case(case))


def test_deterministic_cross_cutting_assertions_pass():
    report = run_evaluation(ROOT)
    assert report["validation_errors"] == []
    assert report["failed"] == 0
    assert report["case_count"] >= 40
    assert report["repository_revision"] != "unknown"
    assert report["resource_manifest_hash"] is None
