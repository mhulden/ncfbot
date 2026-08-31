import hashlib
import json
from datetime import date
from pathlib import Path

from ncfbot.retrieval import search, split_resource
from ncfbot.sources import load_resources


def _write_resource(
    root: Path,
    identifier: str,
    title: str,
    body: str,
    *,
    authority: str,
    status: str,
    review_after: str = "2099-01-01",
) -> None:
    folder = root / "resources" / "students"
    folder.mkdir(parents=True, exist_ok=True)
    markdown = folder / f"{identifier}.md"
    markdown.write_text(body, encoding="utf-8")
    source_body = f"public source for {identifier}".encode()
    sidecar = {
        "id": identifier,
        "resource_file": f"resources/students/{identifier}.md",
        "title": title,
        "audiences": ["students"],
        "topics": ["registration"],
        "sources": [{
            "canonical_url": f"https://www.ncf.edu/{identifier}",
            "publisher": "Test office",
            "authority_type": authority,
            "retrieved_at": "2026-08-31T12:00:00Z",
            "last_modified": None,
            "effective_from": "2026-08-01",
            "effective_through": "2027-07-31",
            "academic_year": "2026-27",
            "sha256": hashlib.sha256(source_body).hexdigest(),
            "public_access_verified": True,
        }],
        "status": status,
        "volatility": "annual",
        "review_after": review_after,
        "notes": "synthetic test fixture",
    }
    markdown.with_name(f"{identifier}.source.json").write_text(json.dumps(sidecar), encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "PLAN-distributed.md").write_text("test", encoding="utf-8")
    _write_resource(
        tmp_path,
        "current-registration",
        "Current Registration Policy",
        "# Current Registration Policy\n\nScope.\n\n## Withdrawal deadline\n\nThe withdrawal deadline is published for the applicable term.\n\n## Sources\n\n- https://www.ncf.edu/current-registration\n",
        authority="calendar",
        status="current",
    )
    _write_resource(
        tmp_path,
        "historical-registration",
        "Old Registration Notes",
        "# Old Registration Notes\n\nScope.\n\n## Withdrawal deadline\n\nA historical withdrawal deadline is retained for reference.\n\n## Sources\n\n- https://www.ncf.edu/historical-registration\n",
        authority="news",
        status="historical",
    )
    return tmp_path


def test_split_preserves_heading_path(tmp_path):
    resources, _ = load_resources(_repo(tmp_path))
    chunks = split_resource(next(item for item in resources if item.resource_id == "current-registration"))
    assert any(chunk.heading_path == ("Current Registration Policy", "Withdrawal deadline") for chunk in chunks)


def test_current_authoritative_evidence_outranks_historical(tmp_path):
    results = search("withdrawal deadline", _repo(tmp_path), audience="students", today=date(2026, 8, 31))
    assert [item.resource_id for item in results[:2]] == ["current-registration", "historical-registration"]
    assert results[0].effective_period == "2026-27"
    assert results[0].audiences == ("students",)
    assert results[0].topics == ("registration",)
    assert results[0].authority_types == ("calendar",)
    assert results[0].status == "current"
    assert results[0].source_urls == ("https://www.ncf.edu/current-registration",)


def test_filters_and_no_evidence_behavior(tmp_path):
    root = _repo(tmp_path)
    assert search("withdrawal deadline", root, audience="faculty") == []
    assert search("quantum penguin", root) == []


def test_overdue_resource_is_labeled(tmp_path):
    root = _repo(tmp_path)
    sidecar = root / "resources/students/current-registration.source.json"
    data = json.loads(sidecar.read_text())
    data["review_after"] = "2020-01-01"
    sidecar.write_text(json.dumps(data))
    result = search("withdrawal deadline", root, today=date(2026, 8, 31))[0]
    assert result.review_state == "overdue"
