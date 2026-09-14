import csv
import json
from pathlib import Path

from ncfbot.__main__ import main
from ncfbot.human_evaluation import CSV_FIELDS, export_jsonl, read_human_runs, validate_human_run


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "evaluations/examples/round-2-human-run.jsonl"
TEMPLATE = ROOT / "evaluations/templates/round-2-human-run.csv"


def _example_record():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _csv_row(record):
    return {
        "run_id": record["run_id"],
        "test_id": record["test_id"],
        "linked_issue": record["linked_issue"] or "",
        "linked_pr": record["linked_pr"] or "",
        "repository_revision": record["repository_revision"],
        "resource_manifest_hash": record["resource_manifest_hash"] or "",
        "agent_product": record["agent_product"],
        "model": record["model"],
        "model_version": record["model_version"] or "",
        "runtime": record["runtime"],
        "settings_json": json.dumps(record["settings"]),
        "condition": record["condition"],
        "prompt": record["prompt"],
        "prior_context_json": json.dumps(record["prior_context"]),
        "resources_json": json.dumps(record["resources"]),
        "tool_events_json": json.dumps(record["tool_events"]),
        "trace_reference": record["trace_reference"] or "",
        "started_at": record["started_at"],
        "completed_at": record["completed_at"] or "",
        "time_to_first_actionable_seconds": record["time_to_first_actionable_seconds"],
        "time_to_final_answer_seconds": record["time_to_final_answer_seconds"],
        "final_answer": record["final_answer"] or "",
        "accuracy_0_2": record["scores"]["accuracy"],
        "grounding_0_2": record["scores"]["grounding"],
        "applicability_0_2": record["scores"]["applicability"],
        "usefulness_0_2": record["scores"]["usefulness"],
        "judgment_0_2": record["scores"]["judgment"],
        "total_0_10": record["scores"]["total"],
        "critical": record["critical"],
        "priority": record["priority"],
        "classification": record["classification"],
        "source_verification": record["source_verification"],
        "reviewer_note": record["reviewer_note"] or "",
        "disposition": record["disposition"],
    }


def test_round_2_template_has_the_exact_controlled_header():
    with TEMPLATE.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        assert tuple(next(reader)) == CSV_FIELDS
        assert list(reader) == []


def test_representative_completed_record_is_valid():
    record = _example_record()
    assert validate_human_run(record, ROOT) == []
    assert record["time_to_first_actionable_seconds"] < record["time_to_final_answer_seconds"]
    assert record["tool_events"][0]["actionable"] is True
    assert record["tool_events"][1]["event_type"] == "retrieval"


def test_csv_import_and_jsonl_export_preserve_a_completed_record(tmp_path):
    source = tmp_path / "round-2.csv"
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow(_csv_row(_example_record()))

    records, errors = read_human_runs(source, ROOT)
    assert errors == []
    assert len(records) == 1
    assert records[0]["resources"][0]["resource_id"] == "shared-sensitive-referrals"

    exported = tmp_path / "round-2.jsonl"
    export_jsonl(records, exported)
    reread, reread_errors = read_human_runs(exported, ROOT)
    assert reread_errors == []
    assert reread == records


def test_validation_rejects_partial_scores_bad_order_and_bad_timing():
    record = _example_record()
    record["scores"]["judgment"] = None
    record["tool_events"][0]["sequence"] = 2
    record["time_to_first_actionable_seconds"] = 3.0

    errors = validate_human_run(record, ROOT)

    assert any("scores must be either complete or all null" in error for error in errors)
    assert any("tool event sequence must be contiguous" in error for error in errors)
    assert any("first actionable time cannot exceed final answer time" in error for error in errors)


def test_cli_validates_example_and_exports_jsonl(tmp_path, capsys):
    exported = tmp_path / "normalized.jsonl"
    status = main([
        "--root", str(ROOT), "human-evaluation", "--input", str(EXAMPLE), "--export", str(exported)
    ])

    assert status == 0
    assert exported.is_file()
    assert "Validation: PASS" in capsys.readouterr().out
