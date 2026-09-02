"""Validation and deterministic checks for behavior-oriented evaluations."""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .retrieval import search
from .router import route
from .schema_validation import load_validator, schema_errors
from .sources import load_resources, manifest_hash, repository_root

REQUIRED_FIELDS = {
    "id": str,
    "audience": str,
    "topic": str,
    "question": str,
    "expected_skill": (str, type(None)),
    "expected_resource_ids": list,
    "must_include": list,
    "must_not_include": list,
    "clarification_expected": bool,
    "citation_required": bool,
    "freshness_sensitive": bool,
    "notes": str,
}
AUDIENCES = {"students", "faculty", "outside", "role-independent", "ambiguous"}
SKILLS = {"skills/students.md", "skills/faculty.md", "skills/outside.md", None}
EVALUATION_VERSION = "1"


@dataclass(frozen=True)
class CaseLocation:
    path: Path
    line: int
    case: dict[str, Any]


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    audience: str
    topic: str
    passed: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]


def iter_evaluation_files(root: str | Path | None = None) -> Iterator[Path]:
    folder = repository_root(root) / "evaluations" / "questions"
    if folder.exists():
        yield from sorted(folder.glob("*.jsonl"))


def read_cases(root: str | Path | None = None) -> tuple[list[CaseLocation], list[str]]:
    base = repository_root(root)
    cases: list[CaseLocation] = []
    errors: list[str] = []
    schema_path = base / "schemas" / "evaluation-case.schema.json"
    schema_validator = None
    if schema_path.is_file():
        schema_validator, schema_load_errors = load_validator(schema_path)
        errors.extend(schema_load_errors)
    for path in iter_evaluation_files(base):
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_number}: invalid JSON: {exc.msg}")
                continue
            label = f"{path}:{line_number}"
            if schema_validator is not None:
                errors.extend(schema_errors(schema_validator, data, label))
            errors.extend(validate_case(data, label))
            if isinstance(data, dict):
                cases.append(CaseLocation(path, line_number, data))
    return cases, errors


def validate_case(case: Any, label: str = "case") -> list[str]:
    if not isinstance(case, dict):
        return [f"{label}: case must be an object"]
    errors: list[str] = []
    allowed = set(REQUIRED_FIELDS)
    for key, expected_type in REQUIRED_FIELDS.items():
        if key not in case:
            errors.append(f"{label}: missing {key}")
        elif not isinstance(case[key], expected_type):
            names = expected_type.__name__ if isinstance(expected_type, type) else " or ".join(item.__name__ for item in expected_type)
            errors.append(f"{label}: {key} must be {names}")
    for key in set(case) - allowed:
        errors.append(f"{label}: unknown field {key}")
    if errors:
        return errors
    identifier = case["id"]
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier):
        errors.append(f"{label}: id must be kebab-case")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", case["topic"]):
        errors.append(f"{label}: topic must be kebab-case")
    if case["audience"] not in AUDIENCES:
        errors.append(f"{label}: invalid audience {case['audience']!r}")
    if case["expected_skill"] not in SKILLS:
        errors.append(f"{label}: invalid expected_skill {case['expected_skill']!r}")
    expected_skill_by_audience = {
        "students": "skills/students.md",
        "faculty": "skills/faculty.md",
        "outside": "skills/outside.md",
        "role-independent": None,
        "ambiguous": None,
    }
    if case["audience"] in expected_skill_by_audience and case["expected_skill"] != expected_skill_by_audience[case["audience"]]:
        errors.append(f"{label}: expected_skill does not match audience {case['audience']!r}")
    for key in ("expected_resource_ids", "must_include", "must_not_include"):
        if not all(isinstance(value, str) and value for value in case[key]):
            errors.append(f"{label}: {key} must contain non-empty strings")
    if len(case["expected_resource_ids"]) != len(set(case["expected_resource_ids"])):
        errors.append(f"{label}: expected_resource_ids contains duplicates")
    if not case["question"]:
        errors.append(f"{label}: question must not be empty")
    return errors


def duplicate_case_ids(cases: list[CaseLocation]) -> list[str]:
    counts = Counter(item.case.get("id") for item in cases)
    return sorted(str(identifier) for identifier, count in counts.items() if identifier and count > 1)


def _revision(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_evaluation(root: str | Path | None = None) -> dict[str, Any]:
    base = repository_root(root)
    cases, validation_errors = read_cases(base)
    duplicates = duplicate_case_ids(cases)
    validation_errors.extend(f"duplicate evaluation id: {identifier}" for identifier in duplicates)
    resources, resource_errors = load_resources(base, strict=False)
    validation_errors.extend(resource_errors)
    known_ids = {resource.resource_id for resource in resources}
    results: list[EvaluationResult] = []
    if not validation_errors:
        for located in cases:
            case = located.case
            checks: list[str] = ["schema"]
            failures: list[str] = []
            # Domain files primarily test answer behavior and may rely on the
            # audience context recorded in the case.  The cross-cutting corpus
            # is the owner of standalone deterministic routing assertions.
            if located.path.name == "cross-cutting.jsonl":
                expected_route = case["audience"]
                actual_route = route(case["question"]).route
                checks.append(f"route={actual_route}")
                if actual_route != expected_route:
                    failures.append(f"expected route {expected_route}, got {actual_route}")
            missing_ids = sorted(set(case["expected_resource_ids"]) - known_ids)
            if missing_ids:
                failures.append("unknown expected resource IDs: " + ", ".join(missing_ids))
            elif case["expected_resource_ids"]:
                # Evaluation audits the complete ranked resource set.  The
                # user-facing search command remains intentionally small.
                evidence = search(case["question"], base, limit=max(1, len(resources)))
                found_ids = {item.resource_id for item in evidence}
                absent = sorted(set(case["expected_resource_ids"]) - found_ids)
                checks.append("retrieval")
                if absent:
                    failures.append("retrieval missed expected IDs: " + ", ".join(absent))
            results.append(
                EvaluationResult(case["id"], case["audience"], case["topic"], not failures, tuple(checks), tuple(failures))
            )
    by_audience = Counter(item.audience for item in results)
    by_topic = Counter(item.topic for item in results)
    return {
        "evaluation_version": EVALUATION_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repository_revision": _revision(base),
        "resource_manifest_hash": manifest_hash(base),
        "case_count": len(cases),
        "passed": sum(item.passed for item in results),
        "failed": sum(not item.passed for item in results),
        "validation_errors": validation_errors,
        "by_audience": dict(sorted(by_audience.items())),
        "by_topic": dict(sorted(by_topic.items())),
        "cases": [
            {
                **item.case,
                "source_file": item.path.relative_to(base).as_posix(),
                "source_line": item.line,
            }
            for item in cases
        ],
        "results": [
            {
                "id": item.case_id,
                "audience": item.audience,
                "topic": item.topic,
                "passed": item.passed,
                "checks": list(item.checks),
                "failures": list(item.failures),
            }
            for item in results
        ],
    }
