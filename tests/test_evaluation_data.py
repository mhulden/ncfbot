import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

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
    manifest_hash = report["resource_manifest_hash"]
    assert manifest_hash is None or re.fullmatch(r"[0-9a-f]{64}", manifest_hash)


def test_invalid_source_metadata_returns_structured_failed_report(tmp_path):
    (tmp_path / "PLAN-distributed.md").write_text("test\n", encoding="utf-8")
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    for filename in ("source-record.schema.json", "evaluation-case.schema.json"):
        (schemas / filename).write_text((ROOT / "schemas" / filename).read_text(), encoding="utf-8")
    questions = tmp_path / "evaluations/questions"
    questions.mkdir(parents=True)
    questions.joinpath("cross-cutting.jsonl").write_text(
        (ROOT / "evaluations/questions/cross-cutting.jsonl").read_text(), encoding="utf-8"
    )
    resources = tmp_path / "resources/students"
    resources.mkdir(parents=True)
    resources.joinpath("invalid.source.json").write_text(
        json.dumps({"id": 7, "unexpected": True}), encoding="utf-8"
    )

    report = run_evaluation(tmp_path)

    assert report["validation_errors"]
    assert report["failed"] == 0
    assert report["results"] == []


def test_round_1_reconciliation_is_complete_and_self_consistent():
    schema = json.loads((ROOT / "schemas/round-1-reconciliation.schema.json").read_text())
    validator = Draft202012Validator(schema)
    records = [
        json.loads(line)
        for line in (ROOT / "evaluations/round-1-reconciliation.jsonl").read_text().splitlines()
        if line.strip()
    ]

    assert len(records) == 35
    assert [record["test_id"] for record in records] == [f"HT-{number:03d}" for number in range(1, 36)]
    assert all(not list(validator.iter_errors(record)) for record in records)
    assert all(
        sum(record["scores"][field] for field in ("accuracy", "grounding", "applicability", "usefulness", "judgment"))
        == record["scores"]["total"]
        for record in records
    )
    assert sum(record["scores"]["total"] for record in records) == 312
    assert {record["test_id"] for record in records if record["critical"] == "yes"} == {
        "HT-009", "HT-013", "HT-029", "HT-035",
    }
    assert all("tester" not in record and "peer_reviewer" not in record for record in records)


def test_round_1_reconciliation_preserves_known_gaps_and_corrected_links():
    records = {
        record["test_id"]: record
        for record in (
            json.loads(line)
            for line in (ROOT / "evaluations/round-1-reconciliation.jsonl").read_text().splitlines()
            if line.strip()
        )
    }

    assert records["HT-024"]["answer_status"] == "mismatched"
    assert records["HT-024"]["disposition"] == "capability-enhancement"
    assert records["HT-026"]["issue_url"].endswith("/issues/35")
    assert len(records["HT-026"]["answer"]) == 2040
    assert records["HT-027"]["scores"]["total"] == 9
    assert records["HT-027"]["issue_url"].endswith("/issues/24")
    assert {records[test_id]["answer_status"] for test_id in ("HT-021", "HT-023", "HT-025")} == {"missing"}
    assert all(records[test_id]["disposition"] == "evidence-gap" for test_id in ("HT-031", "HT-032", "HT-033", "HT-034"))
    assert all(records[test_id]["reviewer_explanation"] is None for test_id in ("HT-031", "HT-032", "HT-033", "HT-034"))
    assert all(records[test_id]["prior_context_status"] == "incomplete" for test_id in ("HT-031", "HT-032"))
