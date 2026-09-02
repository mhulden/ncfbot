"""Shared JSON Schema loading and deterministic error formatting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


def load_validator(schema_path: Path) -> tuple[Draft202012Validator | None, list[str]]:
    """Load and validate a Draft 2020-12 schema."""

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{schema_path}: cannot load schema: {exc}"]
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return None, [f"{schema_path}: invalid schema: {exc.message}"]
    return Draft202012Validator(schema, format_checker=FormatChecker()), []


def schema_errors(validator: Draft202012Validator, instance: Any, label: str) -> list[str]:
    """Return stable, path-aware validation errors for one instance."""

    errors: list[str] = []
    for error in sorted(
        validator.iter_errors(instance), key=lambda item: tuple(str(part) for part in item.absolute_path)
    ):
        location = "$"
        for part in error.absolute_path:
            location += f"[{part}]" if isinstance(part, int) else f".{part}"
        errors.append(f"{label}: schema violation at {location}: {error.message}")
    return errors


def validate_against_schema(instance: Any, schema_path: Path, label: str) -> list[str]:
    validator, errors = load_validator(schema_path)
    if validator is None:
        return errors
    return schema_errors(validator, instance, label)
