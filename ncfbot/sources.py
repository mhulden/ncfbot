"""Resource and provenance loading for the curated public corpus."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

VALID_STATUSES = {"current", "historical", "superseded"}
VALID_VOLATILITY = {"daily", "term", "annual", "stable"}
VALID_AUTHORITIES = {"catalog", "calendar", "policy", "office", "program", "directory", "news", "other"}
VALID_AUDIENCES = {"students", "faculty", "outside"}


class SourceError(ValueError):
    """A resource sidecar does not satisfy the shared contract."""


@dataclass(frozen=True)
class Resource:
    path: Path
    sidecar_path: Path
    markdown: str
    metadata: dict[str, Any]

    @property
    def resource_id(self) -> str:
        return str(self.metadata["id"])

    @property
    def title(self) -> str:
        return str(self.metadata["title"])

    @property
    def urls(self) -> tuple[str, ...]:
        return tuple(str(item["canonical_url"]) for item in self.metadata["sources"])

    @property
    def authority_types(self) -> tuple[str, ...]:
        return tuple(str(item.get("authority_type", "other")) for item in self.metadata["sources"])


def repository_root(start: str | Path | None = None) -> Path:
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "PLAN-distributed.md").exists() or (candidate / "pyproject.toml").exists():
            return candidate
    return current


def _require_type(data: dict[str, Any], key: str, expected: type) -> None:
    if key not in data:
        raise SourceError(f"missing required field: {key}")
    if not isinstance(data[key], expected):
        raise SourceError(f"{key} must be {expected.__name__}")


def validate_sidecar(data: Any, sidecar_path: Path | None = None) -> list[str]:
    """Return contract errors for one parsed provenance sidecar."""

    label = str(sidecar_path or "sidecar")
    if not isinstance(data, dict):
        return [f"{label}: root must be an object"]
    errors: list[str] = []
    required_types = {
        "id": str,
        "resource_file": str,
        "title": str,
        "audiences": list,
        "topics": list,
        "sources": list,
        "status": str,
        "volatility": str,
        "review_after": str,
        "notes": str,
    }
    for key, expected in required_types.items():
        try:
            _require_type(data, key, expected)
        except SourceError as exc:
            errors.append(f"{label}: {exc}")
    if errors:
        return errors
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", data["id"]):
        errors.append(f"{label}: id must be non-empty kebab-case")
    if data["status"] not in VALID_STATUSES:
        errors.append(f"{label}: unknown status {data['status']!r}")
    if data["volatility"] not in VALID_VOLATILITY:
        errors.append(f"{label}: unknown volatility {data['volatility']!r}")
    resource_file = Path(data["resource_file"])
    if resource_file.is_absolute() or ".." in resource_file.parts or "\\" in data["resource_file"] or resource_file.as_posix() != data["resource_file"]:
        errors.append(f"{label}: resource_file must be a safe repository-relative POSIX path")
    try:
        date.fromisoformat(data["review_after"])
    except ValueError:
        errors.append(f"{label}: review_after must be YYYY-MM-DD")
    if not data["audiences"] or not all(value in VALID_AUDIENCES for value in data["audiences"]):
        errors.append(f"{label}: audiences must contain only students, faculty, or outside")
    if len(data["audiences"]) != len(set(data["audiences"])):
        errors.append(f"{label}: audiences must be unique")
    if not data["topics"] or not all(isinstance(value, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) for value in data["topics"]):
        errors.append(f"{label}: topics must contain lowercase kebab-case strings")
    if len(data["topics"]) != len(set(data["topics"])):
        errors.append(f"{label}: topics must be unique")
    if not data["sources"]:
        errors.append(f"{label}: sources must not be empty")
    for index, source in enumerate(data["sources"]):
        prefix = f"{label}: sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in (
            "canonical_url", "publisher", "authority_type", "retrieved_at", "last_modified",
            "effective_from", "effective_through", "academic_year", "sha256", "public_access_verified",
        ):
            if field not in source:
                errors.append(f"{prefix} missing {field}")
        url = source.get("canonical_url", "")
        if not isinstance(url, str) or not url.startswith("https://"):
            errors.append(f"{prefix}.canonical_url must be public HTTPS")
        if source.get("public_access_verified") is not True:
            errors.append(f"{prefix}.public_access_verified must be true")
        if source.get("authority_type") not in VALID_AUTHORITIES:
            errors.append(f"{prefix}.authority_type is not recognized")
        if not isinstance(source.get("publisher"), str) or not source.get("publisher"):
            errors.append(f"{prefix}.publisher must be a non-empty string")
        if source.get("academic_year") is not None and not isinstance(source.get("academic_year"), str):
            errors.append(f"{prefix}.academic_year must be a string or null")
        retrieved_at = source.get("retrieved_at")
        if not isinstance(retrieved_at, str) or not retrieved_at.endswith("Z"):
            errors.append(f"{prefix}.retrieved_at must be an ISO-8601 timestamp")
        else:
            try:
                datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{prefix}.retrieved_at must be an ISO-8601 timestamp")
        for field in ("effective_from", "effective_through"):
            value = source.get(field)
            if value is not None:
                try:
                    date.fromisoformat(value)
                except (TypeError, ValueError):
                    errors.append(f"{prefix}.{field} must be YYYY-MM-DD or null")
        start, end = source.get("effective_from"), source.get("effective_through")
        if isinstance(start, str) and isinstance(end, str):
            try:
                if date.fromisoformat(start) > date.fromisoformat(end):
                    errors.append(f"{prefix}: effective_from is after effective_through")
            except ValueError:
                pass
        last_modified = source.get("last_modified")
        if last_modified is not None:
            if not isinstance(last_modified, str) or not last_modified.endswith("Z"):
                errors.append(f"{prefix}.last_modified must be a UTC timestamp or null")
            else:
                try:
                    datetime.fromisoformat(last_modified.replace("Z", "+00:00"))
                except ValueError:
                    errors.append(f"{prefix}.last_modified must be a UTC timestamp or null")
        digest = source.get("sha256", "")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            errors.append(f"{prefix}.sha256 must be 64 lowercase hexadecimal characters")
    return errors


def iter_sidecars(root: str | Path | None = None) -> Iterator[Path]:
    base = repository_root(root)
    resources = base / "resources"
    if not resources.exists():
        return
    yield from sorted(resources.rglob("*.source.json"))


def load_resource(sidecar_path: str | Path, root: str | Path | None = None) -> Resource:
    path = Path(sidecar_path)
    base = repository_root(root or path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceError(f"{path}: cannot read sidecar: {exc}") from exc
    errors = validate_sidecar(data, path)
    if errors:
        raise SourceError("\n".join(errors))
    resource_path = base / data["resource_file"]
    try:
        markdown = resource_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceError(f"{path}: resource_file cannot be read: {resource_path}") from exc
    if resource_path.resolve() != path.with_name(path.name.removesuffix(".source.json") + ".md").resolve():
        raise SourceError(f"{path}: resource_file must name the neighboring Markdown file")
    return Resource(resource_path, path, markdown, data)


def load_resources(root: str | Path | None = None, *, strict: bool = True) -> tuple[list[Resource], list[str]]:
    resources: list[Resource] = []
    errors: list[str] = []
    for sidecar in iter_sidecars(root):
        try:
            resources.append(load_resource(sidecar, root))
        except SourceError as exc:
            errors.extend(str(exc).splitlines())
    if strict and errors:
        raise SourceError("\n".join(errors))
    return resources, errors


def manifest_hash(root: str | Path | None = None) -> str | None:
    """Hash Agent 5's exact generated manifest bytes, or report its absence."""

    path = repository_root(root) / "resources" / "generated" / "manifest.json"
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()
