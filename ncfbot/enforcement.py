"""Bounded required-resource and structured-conflict enforcement pilot."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .sources import repository_root


PILOT_PATH = Path("evaluations/required-resource-pilot.json")
DECISIONS = {"allow", "evidence-gap", "reject"}
EVENT_TYPES = {"resource-supplied", "resource-loaded", "claim"}


@dataclass(frozen=True)
class PilotResult:
    case_id: str
    expected_decision: str
    decision: str
    passed: bool
    required_resource_ids: tuple[str, ...]
    supplied_resource_ids: tuple[str, ...]
    loaded_resource_ids: tuple[str, ...]
    missing_resource_ids: tuple[str, ...]
    late_resource_ids: tuple[str, ...]
    relevant_conflict_ids: tuple[str, ...]
    assertion_failures: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "expected_decision": self.expected_decision,
            "decision": self.decision,
            "passed": self.passed,
            "required_resource_ids": list(self.required_resource_ids),
            "supplied_resource_ids": list(self.supplied_resource_ids),
            "loaded_resource_ids": list(self.loaded_resource_ids),
            "missing_resource_ids": list(self.missing_resource_ids),
            "late_resource_ids": list(self.late_resource_ids),
            "relevant_conflict_ids": list(self.relevant_conflict_ids),
            "assertion_failures": list(self.assertion_failures),
        }


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _validate_required_resources(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{label}: required_resources must be an array"]
    errors: list[str] = []
    for index, item in enumerate(value):
        prefix = f"{label}.required_resources[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        if set(item) != {"resource_id", "reason"}:
            errors.append(f"{prefix}: fields must be resource_id and reason")
            continue
        resource_id, reason = item["resource_id"], item["reason"]
        if not isinstance(resource_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", resource_id):
            errors.append(f"{prefix}.resource_id: must be kebab-case")
        if not isinstance(reason, str) or not reason:
            errors.append(f"{prefix}.reason: must be a non-empty string")
    return errors


def _validate_conflicts(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{label}: conflicts must be an array"]
    errors: list[str] = []
    required = {"conflict_id", "status", "sources", "claims", "applicability", "responsible_office"}
    for index, item in enumerate(value):
        prefix = f"{label}.conflicts[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        if set(item) != required:
            errors.append(f"{prefix}: fields do not match the structured-conflict contract")
            continue
        if not isinstance(item["conflict_id"], str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", item["conflict_id"]
        ):
            errors.append(f"{prefix}.conflict_id: must be kebab-case")
        status = item["status"]
        if not isinstance(status, str) or status not in {"unresolved", "resolved", "deferred"}:
            errors.append(f"{prefix}.status: invalid status")
        if not _nonempty_strings(item["sources"]) or len(item["sources"]) < 2:
            errors.append(f"{prefix}.sources: must contain at least two URLs")
        elif any(not source.startswith("https://") for source in item["sources"]):
            errors.append(f"{prefix}.sources: URLs must use HTTPS")
        if not _nonempty_strings(item["claims"]) or len(item["claims"]) < 2:
            errors.append(f"{prefix}.claims: must contain at least two claims")
        if len(item.get("sources", [])) != len(item.get("claims", [])):
            errors.append(f"{prefix}: sources and claims must have equal length")
        for field in ("applicability", "responsible_office"):
            if not isinstance(item[field], str) or not item[field]:
                errors.append(f"{prefix}.{field}: must be a non-empty string")
    return errors


def validate_pilot(data: Any, label: str = "pilot") -> list[str]:
    """Validate the bounded fixture without depending on Agent 5 implementation code."""

    if not isinstance(data, dict):
        return [f"{label}: root must be an object"]
    if set(data) != {"pilot_version", "recommendation", "cases"}:
        return [f"{label}: fields must be pilot_version, recommendation, and cases"]
    errors: list[str] = []
    if data["pilot_version"] != "1":
        errors.append(f"{label}: pilot_version must be '1'")
    recommendation = data["recommendation"]
    if not isinstance(recommendation, dict) or set(recommendation) != {"decision", "reason"}:
        errors.append(f"{label}: recommendation must contain decision and reason")
    else:
        decision = recommendation["decision"]
        if not isinstance(decision, str) or decision not in {"adopt", "revise", "reject"}:
            errors.append(f"{label}: recommendation decision must be adopt, revise, or reject")
        if not isinstance(recommendation["reason"], str) or not recommendation["reason"]:
            errors.append(f"{label}: recommendation reason must be non-empty")
    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        errors.append(f"{label}: cases must be a non-empty array")
        return errors
    identifiers: set[str] = set()
    required_case_fields = {
        "id", "question", "response", "required_resources", "conflicts", "resource_events",
        "relevant_conflict_ids", "must_include", "must_not_include", "evidence_gap_markers",
        "maximum_resource_events", "expected_decision",
    }
    for index, case in enumerate(cases):
        prefix = f"{label}.cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        if set(case) != required_case_fields:
            errors.append(f"{prefix}: fields do not match the pilot case contract")
            continue
        identifier = case["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier):
            errors.append(f"{prefix}.id: must be kebab-case")
        elif identifier in identifiers:
            errors.append(f"{prefix}.id: duplicate id {identifier}")
        else:
            identifiers.add(identifier)
        for field in ("question", "response"):
            if not isinstance(case[field], str) or not case[field]:
                errors.append(f"{prefix}.{field}: must be non-empty")
        errors.extend(_validate_required_resources(case["required_resources"], prefix))
        errors.extend(_validate_conflicts(case["conflicts"], prefix))
        for field in ("relevant_conflict_ids", "must_include", "must_not_include", "evidence_gap_markers"):
            if not _nonempty_strings(case[field]):
                errors.append(f"{prefix}.{field}: must be an array of strings")
        if not isinstance(case["maximum_resource_events"], int) or case["maximum_resource_events"] < 0:
            errors.append(f"{prefix}.maximum_resource_events: must be a non-negative integer")
        expected_decision = case["expected_decision"]
        if not isinstance(expected_decision, str) or expected_decision not in DECISIONS:
            errors.append(f"{prefix}.expected_decision: invalid decision")
        events = case["resource_events"]
        if not isinstance(events, list):
            errors.append(f"{prefix}.resource_events: must be an array")
            continue
        sequences: list[int] = []
        for event_index, event in enumerate(events):
            event_label = f"{prefix}.resource_events[{event_index}]"
            if not isinstance(event, dict) or set(event) - {"sequence", "event_type", "resource_id"}:
                errors.append(f"{event_label}: invalid event shape")
                continue
            if not isinstance(event.get("sequence"), int) or event["sequence"] < 1:
                errors.append(f"{event_label}.sequence: must be a positive integer")
            else:
                sequences.append(event["sequence"])
            event_type = event.get("event_type")
            if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
                errors.append(f"{event_label}.event_type: invalid event type")
            if event_type != "claim":
                resource_id = event.get("resource_id")
                if not isinstance(resource_id, str) or not resource_id:
                    errors.append(f"{event_label}.resource_id: required for resource events")
            elif "resource_id" in event:
                errors.append(f"{event_label}: claim events cannot name a resource")
        if sequences and sequences != list(range(1, len(sequences) + 1)):
            errors.append(f"{prefix}.resource_events: sequence must be contiguous")
    return errors


def evaluate_pilot_case(case: dict[str, Any]) -> PilotResult:
    """Apply ordering, telemetry, conflict, content, and concision checks to one case."""

    response = case["response"]
    lowered = response.casefold()
    events = sorted(case["resource_events"], key=lambda event: event["sequence"])
    claim_sequences = [event["sequence"] for event in events if event["event_type"] == "claim"]
    first_claim = min(claim_sequences, default=float("inf"))
    supplied = tuple(
        event["resource_id"] for event in events if event["event_type"] == "resource-supplied"
    )
    loaded = tuple(
        event["resource_id"] for event in events if event["event_type"] == "resource-loaded"
    )
    available_before_claim = {
        event["resource_id"]
        for event in events
        if event["event_type"] in {"resource-supplied", "resource-loaded"}
        and event["sequence"] < first_claim
    }
    available_anytime = set(supplied) | set(loaded)
    required = tuple(item["resource_id"] for item in case["required_resources"])
    missing = tuple(sorted(set(required) - available_anytime))
    late = tuple(sorted((set(required) & available_anytime) - available_before_claim))
    failures: list[str] = []

    if len(supplied) + len(loaded) > case["maximum_resource_events"]:
        failures.append("unnecessary retrieval: resource event limit exceeded")
    for phrase in case["must_include"]:
        if phrase.casefold() not in lowered:
            failures.append(f"missing required content: {phrase}")
    for phrase in case["must_not_include"]:
        if phrase.casefold() in lowered:
            failures.append(f"forbidden content present: {phrase}")

    conflicts = {item["conflict_id"]: item for item in case["conflicts"]}
    relevant = tuple(case["relevant_conflict_ids"])
    unknown_conflicts = sorted(set(relevant) - set(conflicts))
    if unknown_conflicts:
        failures.append("unknown relevant conflict IDs: " + ", ".join(unknown_conflicts))
    for conflict_id, conflict in conflicts.items():
        if conflict_id in relevant:
            if conflict["status"] == "unresolved":
                for claim in conflict["claims"]:
                    if claim.casefold() not in lowered:
                        failures.append(f"{conflict_id}: missing distinct claim: {claim}")
                for field in ("applicability", "responsible_office"):
                    value = conflict[field]
                    if value.casefold() not in lowered:
                        failures.append(f"{conflict_id}: missing {field}: {value}")
        else:
            for claim in conflict["claims"]:
                if claim.casefold() in lowered:
                    failures.append(f"irrelevant conflict leaked into answer: {conflict_id}")

    if missing or late:
        has_gap = all(marker.casefold() in lowered for marker in case["evidence_gap_markers"])
        if has_gap and not failures:
            decision = "evidence-gap"
        else:
            if not has_gap:
                failures.append("missing-resource answer lacks the required evidence-gap explanation")
            decision = "reject"
    else:
        decision = "allow" if not failures else "reject"

    expected = case["expected_decision"]
    return PilotResult(
        case_id=case["id"],
        expected_decision=expected,
        decision=decision,
        passed=decision == expected,
        required_resource_ids=required,
        supplied_resource_ids=supplied,
        loaded_resource_ids=loaded,
        missing_resource_ids=missing,
        late_resource_ids=late,
        relevant_conflict_ids=relevant,
        assertion_failures=tuple(failures),
    )


def run_enforcement_pilot(root: str | Path | None = None) -> dict[str, Any]:
    """Run the provider-neutral issue #40 fixture and return inspectable evidence."""

    base = repository_root(root)
    path = base / PILOT_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "pilot_version": "1",
            "recommendation": None,
            "case_count": 0,
            "passed": 0,
            "failed": 0,
            "validation_errors": [f"{path}: cannot read pilot fixture: {exc}"],
            "results": [],
        }
    errors = validate_pilot(data, str(path))
    if errors:
        return {
            "pilot_version": str(data.get("pilot_version", "1")) if isinstance(data, dict) else "1",
            "recommendation": data.get("recommendation") if isinstance(data, dict) else None,
            "case_count": len(data.get("cases", [])) if isinstance(data, dict) and isinstance(data.get("cases"), list) else 0,
            "passed": 0,
            "failed": 0,
            "validation_errors": errors,
            "results": [],
        }
    results = [evaluate_pilot_case(case) for case in data["cases"]]
    return {
        "pilot_version": data["pilot_version"],
        "recommendation": data["recommendation"],
        "case_count": len(results),
        "passed": sum(result.passed for result in results),
        "failed": sum(not result.passed for result in results),
        "validation_errors": [],
        "results": [result.to_dict() for result in results],
    }
