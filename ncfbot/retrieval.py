"""Small, inspectable lexical retrieval over authored Markdown resources."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

from .sources import Resource, load_resources

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)?")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
AUTHORITY_WEIGHT = {
    "catalog": 1.25,
    "policy": 1.2,
    "calendar": 1.18,
    "office": 1.12,
    "program": 1.05,
    "directory": 1.0,
    "news": 0.9,
    "other": 0.95,
}


@dataclass(frozen=True)
class Chunk:
    resource: Resource
    heading_path: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class SearchResult:
    resource_id: str
    title: str
    heading: str
    score: float
    audiences: tuple[str, ...]
    topics: tuple[str, ...]
    authority_types: tuple[str, ...]
    status: str
    effective_period: str
    review_state: str
    source_urls: tuple[str, ...]
    excerpt: str

    def to_dict(self) -> dict[str, object]:
        return {
            "resource_id": self.resource_id,
            "title": self.title,
            "heading": self.heading,
            "score": round(self.score, 4),
            "audiences": list(self.audiences),
            "topics": list(self.topics),
            "authority_types": list(self.authority_types),
            "status": self.status,
            "effective_period": self.effective_period,
            "review_state": self.review_state,
            "source_urls": list(self.source_urls),
            "excerpt": self.excerpt,
        }


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def split_resource(resource: Resource) -> list[Chunk]:
    """Split Markdown at headings while retaining the complete heading ancestry."""

    heading_stack: list[tuple[int, str]] = []
    chunks: list[Chunk] = []
    body: list[str] = []
    current_path: tuple[str, ...] = (resource.title,)

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            chunks.append(Chunk(resource, current_path, text))
        body.clear()

    for line in resource.markdown.splitlines():
        match = HEADING_RE.match(line)
        if not match:
            body.append(line)
            continue
        flush()
        level = len(match.group(1))
        title = match.group(2).strip()
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))
        current_path = tuple(item[1] for item in heading_stack)
    flush()
    return chunks


def _review_state(resource: Resource, today: date) -> str:
    review_after = date.fromisoformat(resource.metadata["review_after"])
    return "overdue" if review_after < today else "current"


def _effective_period(resource: Resource) -> str:
    periods: list[str] = []
    for source in resource.metadata["sources"]:
        if source.get("academic_year"):
            periods.append(str(source["academic_year"]))
        else:
            start = source.get("effective_from")
            end = source.get("effective_through")
            if start or end:
                periods.append(f"{start or 'unspecified'} through {end or 'present'}")
    return "; ".join(dict.fromkeys(periods)) or "not specified"


def _score(query: str, query_tokens: list[str], chunk: Chunk, today: date) -> float:
    if not query_tokens:
        return 0.0
    title_tokens = tokenize(chunk.resource.title)
    heading_tokens = tokenize(" ".join(chunk.heading_path))
    body_tokens = tokenize(chunk.text)
    title_set, heading_set, body_set = set(title_tokens), set(heading_tokens), set(body_tokens)
    score = 0.0
    for token in set(query_tokens):
        score += 3.0 * (token in title_set)
        score += 2.2 * (token in heading_set)
        score += 1.0 * (token in body_set)
        score += min(body_tokens.count(token), 4) * 0.15
    normalized_query = " ".join(query.lower().split())
    if len(query_tokens) > 1:
        if normalized_query in chunk.text.lower():
            score += 5.0
        if normalized_query in " ".join(chunk.heading_path).lower():
            score += 7.0
    coverage = len(set(query_tokens) & (title_set | heading_set | body_set)) / len(set(query_tokens))
    score *= 0.5 + 0.5 * coverage
    authority = max((AUTHORITY_WEIGHT.get(value, 0.95) for value in chunk.resource.authority_types), default=0.95)
    score *= authority
    status = chunk.resource.metadata["status"]
    if status == "historical":
        score *= 0.65
    elif status == "superseded":
        score *= 0.35
    elif status in {"deferred", "rejected"}:
        score *= 0.1
    if _review_state(chunk.resource, today) == "overdue":
        score *= 0.75
    return score / (1.0 + 0.02 * math.log1p(len(body_tokens)))


def search(
    query: str,
    root: str | Path | None = None,
    *,
    audience: str | None = None,
    topic: str | None = None,
    limit: int = 5,
    today: date | None = None,
) -> list[SearchResult]:
    """Return a small deterministic evidence set, never a generated answer."""

    if limit < 1:
        raise ValueError("limit must be at least 1")
    resources, _ = load_resources(root)
    current_date = today or date.today()
    query_tokens = tokenize(query)
    ranked: list[tuple[float, Chunk]] = []
    for resource in resources:
        if audience and audience not in resource.metadata["audiences"]:
            continue
        if topic and topic not in resource.metadata["topics"]:
            continue
        for chunk in split_resource(resource):
            score = _score(query, query_tokens, chunk, current_date)
            if score > 0.5:
                ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1].resource.resource_id, item[1].heading_path))

    results: list[SearchResult] = []
    seen_resources: set[str] = set()
    for score, chunk in ranked:
        # Keep evidence diverse: one best chunk per resource in the default small set.
        if chunk.resource.resource_id in seen_resources:
            continue
        seen_resources.add(chunk.resource.resource_id)
        excerpt = re.sub(r"\s+", " ", chunk.text).strip()
        if len(excerpt) > 280:
            excerpt = excerpt[:277].rstrip() + "..."
        results.append(
            SearchResult(
                resource_id=chunk.resource.resource_id,
                title=chunk.resource.title,
                heading=" > ".join(chunk.heading_path),
                score=score,
                audiences=tuple(chunk.resource.metadata["audiences"]),
                topics=tuple(chunk.resource.metadata["topics"]),
                authority_types=chunk.resource.authority_types,
                status=str(chunk.resource.metadata["status"]),
                effective_period=_effective_period(chunk.resource),
                review_state=_review_state(chunk.resource, current_date),
                source_urls=chunk.resource.urls,
                excerpt=excerpt,
            )
        )
        if len(results) >= limit:
            break
    return results


def resource_topics(resources: Iterable[Resource]) -> set[str]:
    return {str(topic) for resource in resources for topic in resource.metadata["topics"]}
