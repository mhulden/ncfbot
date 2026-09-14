"""Provider-neutral human-run records for reproducible evaluation."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .schema_validation import load_validator, schema_errors
from .sources import repository_root


CSV_FIELDS = (
    "run_id",
    "test_id",
    "linked_issue",
    "linked_pr",
    "repository_revision",
    "resource_manifest_hash",
    "agent_product",
    "model",
    "model_version",
    "runtime",
    "settings_json",
    "condition",
    "prompt",
    "prior_context_json",
    "resources_json",
    "tool_events_json",
    "trace_reference",
    "started_at",
    "completed_at",
    "time_to_first_actionable_seconds",
    "time_to_final_answer_seconds",
    "final_answer",
    "accuracy_0_2",
    "grounding_0_2",
    "applicability_0_2",
    "usefulness_0_2",
    "judgment_0_2",
    "total_0_10",
    "critical",
    "priority",
    "classification",
    "source_verification",
    "reviewer_note",
    "disposition",
)

JSON_COLUMNS = {
    "settings_json": "settings",
    "prior_context_json": "prior_context",
    "resources_json": "resources",
    "tool_events_json": "tool_events",
}
INTEGER_COLUMNS = {
    "accuracy_0_2": "accuracy",
    "grounding_0_2": "grounding",
    "applicability_0_2": "applicability",
    "usefulness_0_2": "usefulness",
    "judgment_0_2": "judgment",
    "total_0_10": "total",
}
FLOAT_COLUMNS = ("time_to_first_actionable_seconds", "time_to_final_answer_seconds")
NULLABLE_TEXT_COLUMNS = {
    "linked_issue",
    "linked_pr",
    "resource_manifest_hash",
    "agent_product",
    "model",
    "model_version",
    "runtime",
    "trace_reference",
    "completed_at",
    "final_answer",
    "reviewer_note",
}


def _parse_json_cell(value: str, label: str, errors: list[str]) -> Any:
    if not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        errors.append(f"{label}: invalid JSON: {exc.msg}")
        return None


def _parse_number(value: str, label: str, kind: type[int] | type[float], errors: list[str]) -> int | float | None:
    if not value.strip():
        return None
    try:
        return kind(value)
    except ValueError:
        errors.append(f"{label}: expected {kind.__name__}, got {value!r}")
        return None


def csv_row_to_record(row: dict[str, str], label: str = "row") -> tuple[dict[str, Any], list[str]]:
    """Convert one template row into the JSON Schema representation."""

    errors: list[str] = []
    record: dict[str, Any] = {}
    extra_cells = row.get(None)
    if extra_cells:
        errors.append(f"{label}: extra CSV cell(s): {extra_cells!r}")
    for field in CSV_FIELDS:
        value = row.get(field)
        if value is None:
            errors.append(f"{label}: missing CSV cell for {field}")
            value = ""
        if field in JSON_COLUMNS:
            record[JSON_COLUMNS[field]] = _parse_json_cell(value, f"{label}.{field}", errors)
        elif field in INTEGER_COLUMNS:
            continue
        elif field in FLOAT_COLUMNS:
            record[field] = _parse_number(value, f"{label}.{field}", float, errors)
        elif field in NULLABLE_TEXT_COLUMNS:
            record[field] = value.strip() or None
        else:
            record[field] = value.strip()

    record["scores"] = {
        target: _parse_number(row.get(source) or "", f"{label}.{source}", int, errors)
        for source, target in INTEGER_COLUMNS.items()
    }
    return record, errors


def _validate_uri(value: Any, label: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        return
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        errors.append(f"{label}: expected an absolute HTTP(S) URL")


def _parse_aware_datetime(value: Any, label: str, errors: list[str]) -> datetime | None:
    if value is None or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label}: expected an ISO 8601 date-time")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{label}: date-time must include a UTC offset")
        return None
    return parsed


def validate_human_run(record: Any, root: str | Path | None = None, label: str = "record") -> list[str]:
    """Validate schema plus relationships that JSON Schema cannot express clearly."""

    base = repository_root(root)
    validator, errors = load_validator(base / "schemas" / "human-evaluation-run.schema.json")
    if validator is None:
        return errors
    errors.extend(schema_errors(validator, record, label))
    if not isinstance(record, dict):
        return errors

    _validate_uri(record.get("linked_issue"), f"{label}.linked_issue", errors)
    _validate_uri(record.get("linked_pr"), f"{label}.linked_pr", errors)
    started = _parse_aware_datetime(record.get("started_at"), f"{label}.started_at", errors)
    completed = _parse_aware_datetime(record.get("completed_at"), f"{label}.completed_at", errors)
    if started is not None and completed is not None and completed < started:
        errors.append(f"{label}: completed_at cannot precede started_at")

    scores = record.get("scores")
    if isinstance(scores, dict):
        component_names = ("accuracy", "grounding", "applicability", "usefulness", "judgment")
        components = [scores.get(name) for name in component_names]
        total = scores.get("total")
        populated = [value is not None for value in (*components, total)]
        if any(populated) and not all(populated):
            errors.append(f"{label}: scores must be either complete or all null")
        elif all(isinstance(value, int) for value in (*components, total)) and sum(components) != total:
            errors.append(f"{label}: score total {total} does not equal component sum {sum(components)}")

    condition = record.get("condition")
    context = record.get("prior_context")
    if condition == "fresh" and context not in (None, []):
        errors.append(f"{label}: fresh condition must not contain prior context")
    if condition == "multiturn" and not context:
        errors.append(f"{label}: multiturn condition requires recorded prior context")

    events = record.get("tool_events")
    if isinstance(events, list):
        sequences = [event.get("sequence") for event in events if isinstance(event, dict)]
        if sequences != list(range(1, len(events) + 1)):
            errors.append(f"{label}: tool event sequence must be contiguous and start at 1")
        elapsed = [event.get("elapsed_seconds") for event in events if isinstance(event, dict)]
        numeric_elapsed = [value for value in elapsed if isinstance(value, (int, float))]
        if numeric_elapsed != sorted(numeric_elapsed):
            errors.append(f"{label}: tool event elapsed times must be nondecreasing")

    if record.get("disposition") != "not-run" and events is None and not record.get("trace_reference"):
        errors.append(f"{label}: completed runs require tool events or a durable trace reference")

    first = record.get("time_to_first_actionable_seconds")
    final = record.get("time_to_final_answer_seconds")
    if isinstance(first, (int, float)) and isinstance(final, (int, float)) and first > final:
        errors.append(f"{label}: first actionable time cannot exceed final answer time")
    if isinstance(first, (int, float)) and isinstance(events, list):
        actionable = [
            event.get("elapsed_seconds")
            for event in events
            if isinstance(event, dict) and event.get("actionable") is True
            and event.get("event_type") == "user-visible-output"
            and isinstance(event.get("elapsed_seconds"), (int, float))
        ]
        if not actionable:
            errors.append(f"{label}: first actionable time requires an actionable event")
        elif min(actionable) != first:
            errors.append(f"{label}: first actionable time does not match the earliest actionable event")
    if isinstance(final, (int, float)) and isinstance(events, list):
        after_final = [
            event.get("sequence")
            for event in events
            if isinstance(event, dict) and isinstance(event.get("elapsed_seconds"), (int, float))
            and event["elapsed_seconds"] > final
        ]
        if after_final:
            errors.append(f"{label}: tool event(s) occur after the final answer: {after_final}")

    if record.get("disposition") in {"passed", "failed"}:
        if not record.get("completed_at"):
            errors.append(f"{label}: completed disposition requires completed_at")
        if not record.get("final_answer"):
            errors.append(f"{label}: completed disposition requires the full final answer")
        if not isinstance(first, (int, float)) or not isinstance(final, (int, float)):
            errors.append(f"{label}: completed disposition requires both timing measurements")
        if not isinstance(scores, dict) or not all(
            isinstance(scores.get(field), int)
            for field in ("accuracy", "grounding", "applicability", "usefulness", "judgment", "total")
        ):
            errors.append(f"{label}: completed disposition requires all six scores")
    return errors


def read_human_runs(path: Path, root: str | Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Read and validate a CSV template or normalized JSONL run file."""

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    if path.suffix.lower() == ".csv":
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                if tuple(reader.fieldnames or ()) != CSV_FIELDS:
                    return [], [f"{path}: headers do not match the Round 2 template"]
                for row_number, row in enumerate(reader, 2):
                    record, row_errors = csv_row_to_record(row, f"{path}:{row_number}")
                    records.append(record)
                    errors.extend(row_errors)
        except OSError as exc:
            return [], [f"{path}: cannot read CSV: {exc}"]
    elif path.suffix.lower() == ".jsonl":
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return [], [f"{path}: cannot read JSONL: {exc}"]
        for line_number, raw in enumerate(lines, 1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_number}: invalid JSON: {exc.msg}")
                continue
            records.append(record)
    else:
        return [], [f"{path}: expected a .csv or .jsonl input"]

    for index, record in enumerate(records, 1):
        errors.extend(validate_human_run(record, root, f"{path}:record {index}"))
    run_ids = [record.get("run_id") for record in records if isinstance(record, dict)]
    duplicates = sorted({run_id for run_id in run_ids if run_id and run_ids.count(run_id) > 1})
    errors.extend(f"{path}: duplicate run_id {run_id}" for run_id in duplicates)
    return records, errors


def export_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    """Write normalized records only after the caller has validated them."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(payload, encoding="utf-8")
