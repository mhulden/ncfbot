import copy
import json

import pytest

from ncfbot.enforcement import (
    PILOT_PATH,
    evaluate_pilot_case,
    run_enforcement_pilot,
    validate_pilot,
)
from ncfbot.evaluation import run_evaluation
from ncfbot.sources import repository_root


def _pilot_data():
    path = repository_root() / PILOT_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def _case(case_id):
    return next(case for case in _pilot_data()["cases"] if case["id"] == case_id)


def _result(report, case_id):
    return next(result for result in report["results"] if result["id"] == case_id)


def test_pilot_contract_and_recommendation_are_explicit():
    data = _pilot_data()

    assert validate_pilot(data) == []
    assert data["recommendation"]["decision"] == "revise"

    report = run_enforcement_pilot()
    assert report["case_count"] == 6
    assert report["passed"] == 6
    assert report["failed"] == 0
    assert report["validation_errors"] == []


def test_main_evaluation_report_includes_enforcement_pilot():
    report = run_evaluation()

    assert report["enforcement_pilot"]["case_count"] == 6
    assert report["enforcement_pilot"]["passed"] == 6
    assert report["enforcement_pilot"]["failed"] == 0


def test_missing_and_loaded_resource_controls_record_runtime_evidence():
    report = run_enforcement_pilot()
    missing = _result(report, "ht009-missing-resource-gap")
    loaded = _result(report, "ht009-loaded-compliant")

    assert missing["decision"] == "evidence-gap"
    assert missing["required_resource_ids"] == ["faculty-deadlines-and-systems"]
    assert missing["loaded_resource_ids"] == []
    assert missing["missing_resource_ids"] == ["faculty-deadlines-and-systems"]

    assert loaded["decision"] == "allow"
    assert loaded["loaded_resource_ids"] == ["faculty-deadlines-and-systems"]
    assert loaded["missing_resource_ids"] == []
    assert loaded["late_resource_ids"] == []


def test_load_telemetry_does_not_override_answer_content_assertions():
    result = _result(run_enforcement_pilot(), "ht009-loaded-but-invented-ui")

    assert result["loaded_resource_ids"] == ["faculty-deadlines-and-systems"]
    assert result["decision"] == "reject"
    assert result["passed"]
    assert any("forbidden content" in failure for failure in result["assertion_failures"])


def test_privacy_answer_does_not_gain_irrelevant_exam_logistics():
    result = _result(run_enforcement_pilot(), "ht028-privacy-without-logistics")

    assert result["decision"] == "allow"
    assert result["relevant_conflict_ids"] == []
    assert result["loaded_resource_ids"] == ["shared-sensitive-referrals"]
    assert result["assertion_failures"] == []


def test_relevant_unresolved_conflict_preserves_both_claims_and_applicability():
    result = _result(run_enforcement_pilot(), "alc-upload-conflict-relevant")

    assert result["decision"] == "allow"
    assert result["supplied_resource_ids"] == ["faculty-academic-workflows"]
    assert result["relevant_conflict_ids"] == ["alc-faculty-upload-lead-time"]
    assert result["assertion_failures"] == []


def test_resource_loaded_after_claim_is_recorded_as_late():
    case = copy.deepcopy(_case("ht009-missing-resource-gap"))
    case["resource_events"] = [
        {"sequence": 1, "event_type": "claim"},
        {
            "sequence": 2,
            "event_type": "resource-loaded",
            "resource_id": "faculty-deadlines-and-systems",
        },
    ]
    case["maximum_resource_events"] = 1

    result = evaluate_pilot_case(case)

    assert result.missing_resource_ids == ()
    assert result.late_resource_ids == ("faculty-deadlines-and-systems",)
    assert result.decision == "evidence-gap"


def test_structured_conflict_contract_rejects_unpaired_claims():
    data = _pilot_data()
    conflict = data["cases"][3]["conflicts"][0]
    conflict["claims"].pop()

    errors = validate_pilot(data)

    assert any("sources and claims must have equal length" in error for error in errors)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (lambda data: data["cases"][0].__setitem__("id", []), ".id: must be kebab-case"),
        (
            lambda data: data["cases"][3]["conflicts"][0].__setitem__("status", []),
            ".status: invalid status",
        ),
        (
            lambda data: data["cases"][0].__setitem__("expected_decision", []),
            ".expected_decision: invalid decision",
        ),
        (
            lambda data: data["cases"][1]["resource_events"][0].__setitem__(
                "event_type", []
            ),
            ".event_type: invalid event type",
        ),
        (
            lambda data: data["recommendation"].__setitem__("decision", []),
            "recommendation decision must be adopt, revise, or reject",
        ),
    ],
)
def test_malformed_enum_and_identifier_types_return_structured_errors(
    mutation, expected_error
):
    data = _pilot_data()
    mutation(data)

    errors = validate_pilot(data)

    assert any(expected_error in error for error in errors)


def test_malformed_pilot_file_returns_failed_report_instead_of_raising(tmp_path):
    data = _pilot_data()
    data["cases"][0]["id"] = []
    path = tmp_path / PILOT_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")

    report = run_enforcement_pilot(tmp_path)

    assert report["passed"] == 0
    assert report["results"] == []
    assert any(".id: must be kebab-case" in error for error in report["validation_errors"])
