#!/usr/bin/env python3
"""
validate_sources.py — Agent 5: sidecar and corpus validator

Validates all .source.json sidecar files against source-record.schema.json,
checks cross-references between sidecars and resource Markdown files,
and builds a generated combined manifest of the full corpus.

Usage:
    python tools/validate_sources.py --all
    python tools/validate_sources.py --sidecar resources/students/academic-model.source.json
    python tools/validate_sources.py --all --manifest resources/generated/source-manifest.json

Exit codes:
    0 — all validations passed
    1 — one or more validation errors found
"""

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    import jsonschema
    from jsonschema import Draft202012Validator
except ImportError:
    raise SystemExit(
        "Missing dependency: pip install jsonschema\n"
        "Install all dev dependencies with: pip install -e '.[dev]'"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("validate_sources")

SCHEMA_PATH = Path("schemas/source-record.schema.json")
RESOURCES_DIR = Path("resources")
GENERATED_DIR = Path("resources/generated")
MANIFEST_PATH = Path("resources/generated/manifest.json")

# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

def load_schema() -> dict:
    if not SCHEMA_PATH.exists():
        raise SystemExit(f"Schema not found: {SCHEMA_PATH}\nRun from the repo root.")
    with SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def make_validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema)


# ---------------------------------------------------------------------------
# Individual sidecar validation
# ---------------------------------------------------------------------------

def validate_sidecar(sidecar_path: Path, validator: Draft202012Validator) -> list[str]:
    """
    Validate one .source.json file. Returns a list of error strings (empty = pass).
    Checks:
      1. JSON parseable
      2. Schema conformance
      3. Unique stable ID (checked at corpus level)
      4. resource_file exists on disk
      5. Sources section in paired Markdown contains the same canonical URLs
      6. sha256 is populated (warns if null)
      7. review_after is not already overdue
    """
    errors = []

    # 1. Parse
    try:
        with sidecar_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"JSON parse error: {exc}"]

    # 2. Schema
    schema_errors = sorted(validator.iter_errors(data), key=lambda e: str(e.path))
    for err in schema_errors:
        errors.append(f"Schema: {list(err.path)} — {err.message}")

    if errors:
        return errors  # No point continuing if schema is broken

    # 3. resource_file exists
    resource_path = Path(data["resource_file"])
    if not resource_path.exists():
        errors.append(f"resource_file not found on disk: {resource_path}")
    else:
        # 5. Check Sources section in Markdown contains the sidecar URLs
        md_text = resource_path.read_text(encoding="utf-8")
        sidecar_urls = {
            src["canonical_url"]
            for src in data.get("sources", [])
            if src.get("canonical_url")
        }
        missing_in_md = []
        for url in sidecar_urls:
            if url not in md_text:
                missing_in_md.append(url)
        if missing_in_md:
            for url in missing_in_md:
                errors.append(
                    f"Source URL in sidecar but missing from resource Markdown: {url}"
                )

        # Check Markdown has a Sources section
        if not re.search(r"^##?\s+sources?\s*$", md_text, re.IGNORECASE | re.MULTILINE):
            errors.append("Resource Markdown missing a 'Sources' section heading")

        # Check Markdown has Verified through line
        if not re.search(r"verified through\s*:", md_text, re.IGNORECASE):
            errors.append("Resource Markdown missing 'Verified through: YYYY-MM-DD' near the top")

    # 6. sha256 populated
    for i, src in enumerate(data.get("sources", [])):
        if src.get("sha256") is None:
            errors.append(
                f"sources[{i}].sha256 is null — run fetch_sources.py to populate"
            )
        if src.get("public_access_verified") is not True:
            errors.append(
                f"sources[{i}].public_access_verified is not true — must be manually confirmed"
            )

    # 7. review_after overdue
    review_str = data.get("review_after", "")
    if review_str:
        try:
            review_date = date.fromisoformat(review_str)
            if review_date < date.today():
                errors.append(
                    f"review_after {review_str} is overdue (today is {date.today()})"
                )
        except ValueError:
            errors.append(f"review_after is not a valid ISO date: {review_str!r}")

    return errors


# ---------------------------------------------------------------------------
# Corpus-level checks
# ---------------------------------------------------------------------------

def check_duplicate_ids(sidecars: list[tuple[Path, dict]]) -> list[str]:
    seen: dict[str, Path] = {}
    errors = []
    for path, data in sidecars:
        id_ = data.get("id", "")
        if id_ in seen:
            errors.append(
                f"Duplicate sidecar ID '{id_}': {seen[id_]} and {path}"
            )
        else:
            seen[id_] = path
    return errors


# ---------------------------------------------------------------------------
# Manifest generation
# ---------------------------------------------------------------------------

def build_manifest(sidecars: list[tuple[Path, dict]]) -> dict:
    """
    Build a combined machine-readable manifest of all corpus sources.
    Shape matches integration-contracts.md: top-level metadata + resources array.
    Written to resources/generated/manifest.json by the caller ONLY when all
    validations pass — never written over a valid manifest with partial/invalid data.
    No agent hand-maintains this file — always regenerate via validate_sources.py.
    """
    resources = []
    for path, data in sidecars:
        resources.append({
            "id": data.get("id"),
            "resource_file": data.get("resource_file"),
            "title": data.get("title"),
            "audiences": data.get("audiences", []),
            "topics": data.get("topics", []),
            "status": data.get("status"),
            "volatility": data.get("volatility"),
            "review_after": data.get("review_after"),
            "source_urls": [
                s.get("canonical_url")
                for s in data.get("sources", [])
                if s.get("canonical_url")
            ],
            "sidecar_path": str(path),
        })

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": "validate_sources.py",
        "total_resources": len(resources),
        "resources": resources,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate .source.json sidecars and optionally build a corpus manifest."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Validate all .source.json files under resources/",
    )
    group.add_argument(
        "--sidecar",
        type=Path,
        help="Validate a single .source.json file",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Write a combined source manifest to this path (default: resources/generated/manifest.json)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    schema = load_schema()
    validator = make_validator(schema)

    # Collect sidecars
    if args.sidecar:
        sidecar_paths = [args.sidecar]
    else:
        sidecar_paths = sorted(RESOURCES_DIR.rglob("*.source.json"))

    log.info("Validating %d sidecar(s)...", len(sidecar_paths))

    loaded: list[tuple[Path, dict]] = []
    all_errors: dict[str, list[str]] = {}

    for path in sidecar_paths:
        errs = validate_sidecar(path, validator)
        if errs:
            all_errors[str(path)] = errs
            log.error("FAIL %s (%d error(s))", path, len(errs))
        else:
            log.info("PASS %s", path)
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            loaded.append((path, data))
        except Exception:
            pass

    # Corpus-level duplicate ID check
    if args.all:
        dup_errors = check_duplicate_ids(loaded)
        if dup_errors:
            all_errors.setdefault("_corpus", []).extend(dup_errors)
            for e in dup_errors:
                log.error("CORPUS: %s", e)

    # Report
    total = len(sidecar_paths)
    failed = len(all_errors)
    passed = total - failed

    print(f"\nValidation results: {passed}/{total} passed, {failed} failed")

    if all_errors:
        print("\nErrors:")
        for file, errs in all_errors.items():
            print(f"\n  {file}")
            for e in errs:
                print(f"    - {e}")
        if args.manifest:
            log.warning(
                "Manifest NOT written — validation failed. Fix errors first to avoid "
                "replacing a valid manifest with partial/invalid data."
            )
        sys.exit(1)

    # Manifest — only written when all validations passed
    if args.manifest and loaded:
        manifest = build_manifest(loaded)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        with args.manifest.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
        log.info("Manifest written → %s (%d resources)", args.manifest, len(loaded))

    print("All sidecars valid.")
    sys.exit(0)


if __name__ == "__main__":
    main()
