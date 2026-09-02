"""Offline repository health checks for the distributed integration contract."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .evaluation import duplicate_case_ids, read_cases
from .schema_validation import load_validator, schema_errors
from .sources import load_resources, repository_root

REQUIRED_FILES = (
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    "skills/students.md",
    "skills/faculty.md",
    "skills/outside.md",
    "schemas/source-record.schema.json",
    "schemas/course-section.schema.json",
    "schemas/evaluation-case.schema.json",
    "evaluations/questions/students.jsonl",
    "evaluations/questions/faculty.jsonl",
    "evaluations/questions/outside.jsonl",
    "evaluations/questions/courses.jsonl",
    "evaluations/questions/cross-cutting.jsonl",
    "docs/source-pipeline.md",
    "docs/course-data.md",
    "tools/survey_sources.py",
    "tools/fetch_sources.py",
    "tools/convert_sources.py",
    "tools/validate_sources.py",
    "tools/check_freshness.py",
    "tools/discover_public_terms.py",
    "tools/fetch_public_courses.py",
    "tools/fetch_course_details.py",
    "tools/build_course_history.py",
    "tools/query_courses.py",
    "tools/poll_live_sections.py",
)
OWNED_RESOURCE_DIRS = {"shared", "students", "faculty", "outside", "courses", "inventory", "generated"}
DERIVED_MARKDOWN_REPORTS = {
    "courses/course-scan.md",
    "courses/current-course-scan.md",
}
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
PUBLIC_URL_RE = re.compile(r"https?://[^\s)>\]]+")


@dataclass(frozen=True)
class Issue:
    severity: str
    check: str
    message: str
    network: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"severity": self.severity, "check": self.check, "message": self.message, "network": self.network}


@dataclass(frozen=True)
class DoctorReport:
    root: Path
    issues: tuple[Issue, ...]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        counts = Counter(issue.severity for issue in self.issues)
        return {
            "root": str(self.root),
            "ok": self.ok,
            "counts": dict(sorted(counts.items())),
            "issues": [issue.to_dict() for issue in self.issues],
            "network_checks": "not run; use the source pipeline's explicit network mode",
        }


def _json(path: Path, issues: list[Issue], check: str) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(Issue("error", check, f"{path}: cannot parse JSON: {exc}"))
        return None


def _check_required(base: Path, issues: list[Issue]) -> None:
    for relative in REQUIRED_FILES:
        if not (base / relative).is_file():
            issues.append(Issue("error", "required-files", f"missing required file: {relative}"))


def _check_resources(base: Path, issues: list[Issue]) -> None:
    resources_dir = base / "resources"
    resources, errors = load_resources(base, strict=False)
    issues.extend(Issue("error", "source-sidecars", message) for message in errors)
    ids = Counter(resource.resource_id for resource in resources)
    for identifier, count in sorted(ids.items()):
        if count > 1:
            issues.append(Issue("error", "source-sidecars", f"duplicate resource id: {identifier}"))
    if not resources_dir.exists():
        issues.append(Issue("error", "resources", "missing resources directory"))
        return
    for child in resources_dir.iterdir():
        if child.is_dir() and child.name not in OWNED_RESOURCE_DIRS:
            issues.append(Issue("error", "resources", f"unowned resource location: resources/{child.name}"))
    for markdown in sorted(resources_dir.rglob("*.md")):
        if markdown.name.lower() == "readme.md":
            continue
        relative_path = markdown.relative_to(resources_dir)
        relative_parts = relative_path.parts
        if relative_parts and relative_parts[0] in {"inventory", "generated"}:
            continue
        if relative_path.as_posix() in DERIVED_MARKDOWN_REPORTS:
            # Agent 6 generates these views from provenance-bearing course
            # records. They are reports, not independently authored resources.
            continue
        if relative_path.as_posix() == "shared/source-policy.md":
            # Project source-use governance, not an institutional fact.
            continue
        sidecar = markdown.with_name(markdown.stem + ".source.json")
        if not sidecar.is_file():
            issues.append(Issue("error", "source-sidecars", f"missing sidecar for {markdown.relative_to(base)}"))
        markdown_text = markdown.read_text(encoding="utf-8")
        title_match = re.search(r"(?m)^#\s+(.+?)\s*$", markdown_text)
        if not title_match:
            issues.append(Issue("error", "resource-markdown", f"missing top-level title: {markdown.relative_to(base)}"))
        if not re.search(r"(?im)^\*{0,2}Verified through:\s*\d{4}-\d{2}-\d{2}\*{0,2}\s*$", markdown_text):
            issues.append(Issue("error", "resource-markdown", f"missing Verified through date: {markdown.relative_to(base)}"))
        headings = re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", markdown_text)
        if not headings or headings[-1].strip().lower() != "sources":
            issues.append(Issue("error", "source-footers", f"missing Sources heading: {markdown.relative_to(base)}"))
    for resource in resources:
        # The contract requires a human-readable sidecar title that is
        # consistent with the resource, not a byte-for-byte copy of its H1.
        # Domain resources may intentionally use a shorter page heading.
        source_heading = re.search(r"(?im)^#{1,6}\s+Sources\s*$", resource.markdown)
        if source_heading:
            footer = resource.markdown[source_heading.end():]
            footer_urls = {url.rstrip(".,;") for url in PUBLIC_URL_RE.findall(footer)}
            sidecar_urls = set(resource.urls)
            if footer_urls != sidecar_urls:
                missing = sorted(sidecar_urls - footer_urls)
                extra = sorted(footer_urls - sidecar_urls)
                details: list[str] = []
                if missing:
                    details.append("missing from footer: " + ", ".join(missing))
                if extra:
                    details.append("not in sidecar: " + ", ".join(extra))
                issues.append(Issue("error", "source-footers", f"{resource.resource_id}: " + "; ".join(details)))
        try:
            review_after = date.fromisoformat(resource.metadata["review_after"])
            if review_after < date.today():
                issues.append(Issue("warning", "freshness", f"overdue review: {resource.resource_id} ({review_after})"))
        except ValueError:
            pass  # Already reported by sidecar validation.
    _check_manifest(base, resources, issues)


def _check_manifest(base: Path, resources: list[Any], issues: list[Issue]) -> None:
    manifest_path = base / "resources" / "generated" / "manifest.json"
    if not manifest_path.is_file():
        issues.append(Issue("error", "generated-manifest", "missing resources/generated/manifest.json"))
        return
    manifest = _json(manifest_path, issues, "generated-manifest")
    if not isinstance(manifest, dict):
        if manifest is not None:
            issues.append(Issue("error", "generated-manifest", "manifest root must be an object"))
        return
    if manifest.get("schema_version") != "1":
        issues.append(Issue("error", "generated-manifest", "manifest schema_version must be '1'"))
    generated_at = manifest.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at.endswith("Z"):
        issues.append(Issue("error", "generated-manifest", "manifest generated_at must be a UTC timestamp"))
    entries = manifest.get("resources")
    if not isinstance(entries, list):
        issues.append(Issue("error", "generated-manifest", "manifest resources must be an array"))
        return
    expected = {
        resource.resource_id: (
            resource.sidecar_path.relative_to(base).as_posix(),
            resource.metadata,
        )
        for resource in resources
    }
    seen: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("record"), dict) or not isinstance(entry.get("sidecar_file"), str):
            issues.append(Issue("error", "generated-manifest", f"manifest resources[{index}] has invalid shape"))
            continue
        identifier = entry["record"].get("id")
        if not isinstance(identifier, str):
            issues.append(Issue("error", "generated-manifest", f"manifest resources[{index}] record has no id"))
            continue
        seen.append(identifier)
        if identifier not in expected:
            issues.append(Issue("error", "generated-manifest", f"manifest contains unknown resource id: {identifier}"))
            continue
        expected_path, expected_record = expected[identifier]
        if entry["sidecar_file"] != expected_path:
            issues.append(Issue("error", "generated-manifest", f"manifest sidecar path mismatch for {identifier}"))
        if entry["record"] != expected_record:
            issues.append(Issue("error", "generated-manifest", f"manifest record mismatch for {identifier}"))
    if seen != sorted(seen):
        issues.append(Issue("error", "generated-manifest", "manifest resources are not sorted by id"))
    if len(seen) != len(set(seen)):
        issues.append(Issue("error", "generated-manifest", "manifest contains duplicate resource ids"))
    missing = sorted(set(expected) - set(seen))
    if missing:
        issues.append(Issue("error", "generated-manifest", "manifest omits resource ids: " + ", ".join(missing)))


def _check_internal_links(base: Path, issues: list[Issue]) -> None:
    for markdown in sorted(base.rglob("*.md")):
        if ".git" in markdown.parts:
            continue
        text = markdown.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK_RE.findall(text):
            clean = target.strip().split("#", 1)[0]
            if not clean or clean.startswith(("http://", "https://", "mailto:", "#")):
                continue
            candidate = (markdown.parent / clean).resolve()
            try:
                candidate.relative_to(base.resolve())
            except ValueError:
                issues.append(Issue("error", "internal-links", f"path escapes repository in {markdown.relative_to(base)}: {target}"))
                continue
            if not candidate.exists():
                issues.append(Issue("error", "internal-links", f"broken path in {markdown.relative_to(base)}: {target}"))


def _check_agent_paths(base: Path, issues: list[Issue]) -> None:
    agents = base / "AGENTS.md"
    if not agents.exists():
        return
    text = agents.read_text(encoding="utf-8")
    for required in ("skills/students.md", "skills/faculty.md", "skills/outside.md"):
        if required not in text:
            issues.append(Issue("error", "agent-routing", f"AGENTS.md does not reference {required}"))


def _check_tool_help(base: Path, issues: list[Issue]) -> None:
    for relative in REQUIRED_FILES:
        if not relative.startswith("tools/"):
            continue
        path = base / relative
        if not path.is_file():
            continue
        try:
            completed = subprocess.run(
                [sys.executable, str(path), "--help"],
                cwd=base,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            issues.append(Issue("error", "tool-help", f"{relative} --help failed: {exc}"))
            continue
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip().splitlines()
            suffix = f": {detail[-1]}" if detail else ""
            issues.append(Issue("error", "tool-help", f"{relative} --help exited {completed.returncode}{suffix}"))


def _term_codes(data: Any) -> tuple[set[str], set[str]]:
    """Extract term codes and incomplete terms from common public-term layouts."""

    records = data.get("terms", data) if isinstance(data, dict) else data
    if not isinstance(records, list):
        return set(), set()
    codes: set[str] = set()
    incomplete: set[str] = set()
    for item in records:
        if isinstance(item, str):
            codes.add(item)
            continue
        if not isinstance(item, dict):
            continue
        code = item.get("term_code", item.get("code", item.get("term")))
        if code is None:
            continue
        code = str(code)
        codes.add(code)
        if item.get("complete") is False or item.get("status") in {"failed", "incomplete", "partial"}:
            incomplete.add(code)
    return codes, incomplete


def _read_course_jsonl(
    path: Path,
    validator: Any,
    issues: list[Issue],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.is_file():
        issues.append(Issue("error", "course-records", f"missing {path}"))
        return records
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        label = f"{path}:{line_number}"
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(Issue("error", "course-records", f"{label}: invalid JSON: {exc.msg}"))
            continue
        if not isinstance(record, dict):
            issues.append(Issue("error", "course-records", f"{label}: record must be an object"))
            continue
        if validator is not None:
            issues.extend(Issue("error", "course-schema", message) for message in schema_errors(validator, record, label))
        records.append(record)
    return records


def _rows_digest(records: list[dict[str, Any]]) -> str:
    body = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in records)
    return hashlib.sha256(body.encode()).hexdigest()


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _grouped_course_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        subject = str(record.get("subject") or "").strip().upper()
        course_number = str(record.get("course_number") or "").strip().upper()
        term_code = str(record.get("term_code") or "").strip()
        crn = str(record.get("crn") or "").strip()
        if not all((subject, course_number, term_code, crn)):
            continue
        grouped.setdefault((subject, course_number), []).append(record)

    courses: list[dict[str, Any]] = []
    for (subject, course_number), sections in sorted(grouped.items()):
        sections.sort(key=lambda record: (str(record.get("term_code")), str(record.get("crn"))))
        courses.append(
            {
                "subject": subject,
                "course_number": course_number,
                "course_display": next(
                    (record.get("course_display") for record in sections if record.get("course_display")),
                    f"{subject} {course_number}",
                ),
                "titles": _unique([record.get("title") for record in sections if record.get("title")]),
                "terms": _unique(
                    [
                        {"term_code": record.get("term_code"), "term_label": record.get("term_label")}
                        for record in sections
                    ]
                ),
                "instructors": sorted(
                    {
                        name
                        for record in sections
                        for name in record.get("instructors", [])
                        if isinstance(name, str) and name
                    }
                ),
                "attributes": sorted(
                    {
                        value
                        for record in sections
                        for value in record.get("attributes", [])
                        if isinstance(value, str) and value
                    }
                ),
                "section_count": len(sections),
                "section_identities": [
                    {
                        "term_code": record.get("term_code"),
                        "crn": record.get("crn"),
                        "section": record.get("section"),
                    }
                    for record in sections
                ],
            }
        )
    return courses


def _coverage(data: Any) -> tuple[str | None, str | None]:
    value = data.get("coverage") if isinstance(data, dict) else None
    if not isinstance(value, dict):
        return None, None
    earliest = value.get("earliest_term_code")
    latest = value.get("latest_term_code")
    return (str(earliest) if earliest is not None else None, str(latest) if latest is not None else None)


def _check_courses(base: Path, issues: list[Issue]) -> None:
    courses = base / "resources" / "courses"
    terms_path = courses / "public-terms.json"
    history_path = courses / "historical-sections.jsonl"
    history_meta_path = courses / "historical-sections.meta.json"
    current_path = courses / "current-sections.jsonl"
    current_meta_path = courses / "current-sections.meta.json"
    grouped_path = courses / "course-history.json"
    if not terms_path.exists():
        issues.append(Issue("error", "course-coverage", "missing resources/courses/public-terms.json"))
        return
    data = _json(terms_path, issues, "course-coverage")
    if data is None:
        return
    if not isinstance(data, dict) or not isinstance(data.get("terms"), list):
        issues.append(Issue("error", "course-coverage", "public-terms.json must be an object with a terms array"))
    public_terms, incomplete = _term_codes(data)
    if data.get("term_count") is not None and data.get("term_count") != len(public_terms):
        issues.append(Issue("error", "course-coverage", "public term_count does not match terms array"))
    expected_coverage = (min(public_terms), max(public_terms)) if public_terms else (None, None)
    if data.get("coverage") is not None and _coverage(data) != expected_coverage:
        issues.append(Issue("error", "course-coverage", "public term coverage does not match terms array"))
    for code in sorted(incomplete):
        issues.append(Issue("error", "course-coverage", f"public archive marks term incomplete: {code}"))
    course_validator, schema_load_errors = load_validator(base / "schemas" / "course-section.schema.json")
    issues.extend(Issue("error", "course-schema", message) for message in schema_load_errors)
    history = _read_course_jsonl(history_path, course_validator, issues)
    current = _read_course_jsonl(current_path, course_validator, issues)
    archive_terms = {str(record.get("term_code")) for record in history if record.get("term_code")}
    seen_sections: set[tuple[str, str]] = set()
    for record in history:
        term, crn = record.get("term_code"), record.get("crn")
        if isinstance(term, str) and isinstance(crn, str):
            key = (term, crn)
            if key in seen_sections:
                issues.append(Issue("error", "course-records", f"duplicate section key {term}/{crn}"))
            seen_sections.add(key)
    current_keys = [(record.get("term_code"), record.get("crn")) for record in current]
    if len(current_keys) != len(set(current_keys)):
        issues.append(Issue("error", "course-current", "current snapshot contains duplicate section identities"))
    missing = sorted(public_terms - archive_terms)
    extra = sorted(archive_terms - public_terms)
    if missing:
        issues.append(Issue("error", "course-coverage", "public terms absent from historical archive: " + ", ".join(missing)))
    if extra:
        issues.append(Issue("warning", "course-coverage", "archive terms absent from public-term catalog: " + ", ".join(extra)))

    term_counts = Counter(str(record.get("term_code")) for record in history if record.get("term_code"))
    history_meta = _json(history_meta_path, issues, "course-coverage") if history_meta_path.is_file() else None
    if history_meta is None:
        if not history_meta_path.is_file():
            issues.append(Issue("error", "course-coverage", "missing resources/courses/historical-sections.meta.json"))
    elif not isinstance(history_meta, dict):
        issues.append(Issue("error", "course-coverage", "historical-sections.meta.json must be an object"))
    else:
        meta_terms = history_meta.get("terms")
        if history_meta.get("artifact") != "resources/courses/historical-sections.jsonl":
            issues.append(Issue("error", "course-coverage", "historical metadata names the wrong archive artifact"))
        if history_meta.get("complete") is not True or history_meta.get("incomplete_term_count") != 0:
            issues.append(Issue("error", "course-coverage", "historical archive metadata marks the archive incomplete"))
        if history_meta.get("record_count") != len(history):
            issues.append(Issue("error", "course-coverage", "historical archive record_count does not match JSONL"))
        if history_meta.get("discovered_term_count") != len(public_terms):
            issues.append(Issue("error", "course-coverage", "historical discovered_term_count does not match public terms"))
        if history_meta.get("complete_term_count") != len(public_terms):
            issues.append(Issue("error", "course-coverage", "historical complete_term_count does not match public terms"))
        if _coverage(history_meta) != expected_coverage:
            issues.append(Issue("error", "course-coverage", "historical metadata coverage does not match public terms"))
        if not isinstance(meta_terms, dict) or set(meta_terms) != public_terms:
            issues.append(Issue("error", "course-coverage", "historical metadata term set does not match public terms"))
        else:
            for code, term_meta in meta_terms.items():
                if not isinstance(term_meta, dict) or term_meta.get("complete") is not True or term_meta.get("status") != "success":
                    issues.append(Issue("error", "course-coverage", f"historical metadata marks term incomplete: {code}"))
                    continue
                if term_meta.get("record_count") != term_counts.get(code, 0):
                    issues.append(Issue("error", "course-coverage", f"historical metadata count mismatch for term: {code}"))
                expected_count = term_meta.get("expected_count")
                if isinstance(expected_count, int) and expected_count != term_counts.get(code, 0):
                    issues.append(Issue("error", "course-coverage", f"historical expected_count mismatch for term: {code}"))
                term_records = [record for record in history if record.get("term_code") == code]
                if term_meta.get("sha256") != _rows_digest(term_records):
                    issues.append(Issue("error", "course-coverage", f"historical sha256 mismatch for term: {code}"))

    current_meta = _json(current_meta_path, issues, "course-current") if current_meta_path.is_file() else None
    if current_meta is None:
        if not current_meta_path.is_file():
            issues.append(Issue("error", "course-current", "missing resources/courses/current-sections.meta.json"))
    elif not isinstance(current_meta, dict):
        issues.append(Issue("error", "course-current", "current-sections.meta.json must be an object"))
    else:
        current_terms = {record.get("term_code") for record in current}
        if current_meta.get("complete") is not True or current_meta.get("status") != "success":
            issues.append(Issue("error", "course-current", "current snapshot metadata marks the snapshot incomplete"))
        if current_meta.get("record_count") != len(current):
            issues.append(Issue("error", "course-current", "current snapshot record_count does not match JSONL"))
        if current_meta.get("expected_count") != len(current):
            issues.append(Issue("error", "course-current", "current snapshot expected_count does not match JSONL"))
        if current_terms != {current_meta.get("term_code")}:
            issues.append(Issue("error", "course-current", "current snapshot term does not match its metadata"))
        if current_meta.get("sha256") != _rows_digest(current):
            issues.append(Issue("error", "course-current", "current snapshot sha256 does not match JSONL"))

    grouped = _json(grouped_path, issues, "course-history") if grouped_path.is_file() else None
    if grouped is None:
        if not grouped_path.is_file():
            issues.append(Issue("error", "course-history", "missing resources/courses/course-history.json"))
    elif not isinstance(grouped, dict) or not isinstance(grouped.get("courses"), list):
        issues.append(Issue("error", "course-history", "course-history.json must be an object with a courses array"))
    else:
        grouped_courses = grouped["courses"]
        if grouped.get("source") != "resources/courses/historical-sections.jsonl":
            issues.append(Issue("error", "course-history", "course history names the wrong source artifact"))
        if grouped.get("section_count") != len(history) or grouped.get("course_count") != len(grouped_courses):
            issues.append(Issue("error", "course-history", "course history summary counts do not match its inputs"))
        if _coverage(grouped) != expected_coverage:
            issues.append(Issue("error", "course-history", "course history coverage does not match the archive"))
        if grouped_courses != _grouped_course_records(history):
            issues.append(Issue("error", "course-history", "course history derived records do not match the archive"))


def run_doctor(root: str | Path | None = None) -> DoctorReport:
    base = repository_root(root)
    issues: list[Issue] = []
    _check_required(base, issues)
    schemas = base / "schemas"
    if schemas.exists():
        for schema in sorted(schemas.glob("*.json")):
            _, errors = load_validator(schema)
            issues.extend(Issue("error", "schemas", message) for message in errors)
    cases, evaluation_errors = read_cases(base)
    issues.extend(Issue("error", "evaluations", message) for message in evaluation_errors)
    for identifier in duplicate_case_ids(cases):
        issues.append(Issue("error", "evaluations", f"duplicate evaluation id: {identifier}"))
    minimums = {"students.jsonl": 30, "faculty.jsonl": 30, "outside.jsonl": 30, "courses.jsonl": 30, "cross-cutting.jsonl": 40}
    case_counts = Counter(item.path.name for item in cases)
    for filename, minimum in minimums.items():
        if (base / "evaluations" / "questions" / filename).is_file() and case_counts[filename] < minimum:
            issues.append(Issue("error", "evaluations", f"{filename} has {case_counts[filename]} cases; requires at least {minimum}"))
    _check_resources(base, issues)
    _check_internal_links(base, issues)
    _check_agent_paths(base, issues)
    _check_tool_help(base, issues)
    _check_courses(base, issues)
    ordered = tuple(sorted(issues, key=lambda item: (item.severity != "error", item.check, item.message)))
    return DoctorReport(base, ordered)
