"""Transparent, deterministic audience routing.

The router is an aid for the conversational agent, not a replacement for its
judgment.  It deliberately returns ``ambiguous`` when the evidence is weak.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

ROUTES = {"students", "faculty", "outside", "role-independent", "ambiguous"}


@dataclass(frozen=True)
class RouteResult:
    route: str
    matched_signals: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["matched_signals"] = list(self.matched_signals)
        return data


_EXPLICIT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("faculty", (r"\b(?:i am|i['’]m) (?:a |an )?(?:faculty member|faculty|professor|instructor|advisor)\b", r"\bas (?:a |an )?(?:faculty member|faculty|professor|instructor|advisor)\b", r"\bmy advisee\b")),
    ("students", (r"\b(?:i am|i['’]m) (?:a |an )?(?:current |graduate |undergraduate )?student\b", r"\bas (?:a |an )?(?:current |graduate |undergraduate )?student\b", r"\bmy advisor\b")),
    ("outside", (r"\b(?:i am|i['’]m) (?:a |an )?(?:prospective student|applicant|parent|family member|alumnus|alumna|visitor)\b", r"\bas (?:a |an )?(?:prospective student|applicant|parent|family member|alumnus|alumna|visitor)\b", r"\bmy (?:child|son|daughter) (?:is applying|wants to apply|attends)\b")),
)

_SIGNALS: dict[str, tuple[str, ...]] = {
    "students": (
        "my course", "my classes", "my transcript", "my degree", "my aoc",
        "my isp", "my thesis", "my registration", "graduate on time",
        "academic standing", "add a class", "drop a class", "withdraw from",
    ),
    "faculty": (
        "my advisee", "sponsor an isp", "advisee", "submit an evaluation",
        "faculty member", "professor", "instructor", "advising a student",
    ),
    "outside": (
        "apply to", "application", "prospective", "campus tour", "visit campus",
        "tuition", "admissions", "financial aid", "my child", "parent", "alumni",
        "residency for tuition", "housing options",
    ),
}

_ROLE_INDEPENDENT = (
    "where is", "campus map", "academic calendar", "when is the college open",
    "what is new college", "who founded", "address", "directions", "parking map",
)


def _matches(text: str, phrases: Iterable[str]) -> list[str]:
    return [phrase for phrase in phrases if phrase in text]


def route(text: str, previous_role: str | None = None) -> RouteResult:
    """Classify *text* into an audience while exposing every matched signal.

    ``previous_role`` supplies conversational context.  A new explicit identity
    always overrides it, which permits role changes during a conversation.
    """

    normalized = " ".join(text.lower().split())
    if not normalized:
        return RouteResult("ambiguous", (), "No question text was provided.")

    for audience, patterns in _EXPLICIT:
        matched = tuple(pattern for pattern in patterns if re.search(pattern, normalized))
        if matched:
            return RouteResult(audience, matched, "Explicit user identity outranks keyword heuristics.")

    independent = tuple(_matches(normalized, _ROLE_INDEPENDENT))
    scores: dict[str, list[str]] = {
        audience: _matches(normalized, phrases) for audience, phrases in _SIGNALS.items()
    }
    best_score = max((len(items) for items in scores.values()), default=0)
    leaders = [audience for audience, items in scores.items() if len(items) == best_score and best_score]

    if independent and best_score == 0:
        return RouteResult("role-independent", independent, "The answer normally does not change by audience.")

    if len(leaders) == 1 and best_score >= 1:
        audience = leaders[0]
        return RouteResult(audience, tuple(scores[audience]), "Audience-specific wording supports an inferred route.")

    if len(leaders) > 1:
        signals = tuple(f"{audience}:{signal}" for audience in leaders for signal in scores[audience])
        return RouteResult("ambiguous", signals, "Signals point to more than one audience; ask one short clarifying question.")

    if previous_role in {"students", "faculty", "outside"}:
        return RouteResult(previous_role, (f"conversation:{previous_role}",), "No new role signal overrides the conversation context.")

    return RouteResult("ambiguous", (), "The wording does not reliably identify an audience.")
