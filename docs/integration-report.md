# Agent 7 Integration Report

Status: Ready for final integration review
Report date: 2026-09-02
Branch: `agent-7/integration-evaluation`

## Scope

This report covers the deterministic integration layer owned by Agent 7: packaging, routing, curated-resource retrieval, source inspection, repository health checks, evaluation validation and export, cross-cutting evaluation data, and offline tests.

No NCF institutional fact was added by Agent 7. The implementation uses synthetic test fixtures only. No material was copied from an existing NCF bot or from files outside this repository.

## Repository revisions reviewed

- Current reviewed `main`: `1606dfa`
- Agent 1 merge: `4c2d35f8e17b8f2e8aa95eb1dd05a6d0f5fc0e3f`
- Agent 2 merge: `44dafc4`
- Agent 3 merge: `6d3dcea`, including owner-requested follow-up `e1414f9`
- Agent 4 merge: `bb44e39`, including owner-requested follow-up `86a13ef`
- Agent 5 merge: `fa7dd42`, including reviewed fixes through `3f5f7e7`
- Agent 6 merge: `0755203`
- Agent 7 work: topic-focused commits recorded on this branch and rebased onto the revisions above

Agent 7 is rebased onto the merged and reviewed Agent 1–6 work.

## Implemented commands

```text
python -m ncfbot doctor
python -m ncfbot route "How do I sponsor an ISP?"
python -m ncfbot search "withdrawal deadline" --audience students
python -m ncfbot sources --topic admissions
python -m ncfbot evaluate
python -m ncfbot evaluate --export evaluation-run.json
python -m ncfbot course -- <arguments for tools/query_courses.py>
```

The `course` command is a pass-through to Agent 6's `tools/query_courses.py`. Direct use of Agent 6's documented command remains supported.

Search output is explicitly labeled as evidence rather than an official decision. Results include resource ID, heading path, inspectable score, effective period, review state, excerpt, and canonical public source URLs.

## Offline verification results

Fresh-environment installation and test command:

```text
python -m venv <temporary-directory>/venv
<temporary-directory>/venv/bin/python -m pip install -e '.[test]'
<temporary-directory>/venv/bin/python -m pytest
```

Result from a fresh environment against merged Agents 1–6 on 2026-09-02: **118 passed**. Post-merge course-integrity regressions bring the final suite to **121 passed**.

Additional command checks:

- `python -m ncfbot route "How do I sponsor an ISP?"`: routed to `faculty`, with `sponsor an isp` shown as the transparent matched signal and no fabricated numeric confidence.
- `python -m ncfbot search "withdrawal deadline" --audience students`: returned ranked current student/calendar evidence with status, applicability, review state, and official URLs.
- `python -m ncfbot evaluate`: validated and ran **217 merged cases; 217 passed, 0 failed**.
- `python -m ncfbot doctor`: **passed** with no offline contract issues.
- Review regressions confirm that `doctor` rejects incomplete historical metadata, inconsistent current snapshots, corrupted grouped history, schema-invalid provenance, and schema-invalid course rows.
- Post-merge regressions also confirm exact per-term archive hashes and exact grouped-history derivation, including titles and the complete grouped course set.
- Invalid source metadata now makes `evaluate` return a structured failed report instead of raising `SourceError`.
- `python tools/validate_sources.py --all`: **21/21 sidecars passed**.
- `python tools/check_freshness.py --offline`: zero errors and zero warnings.
- Current snapshot query for `CAI 3827`: returned one Fall 2026 section with snapshot timestamp and freshness labeling.
- Historical archive query for `ANTH 2100`: returned four observations spanning Fall 2017 through Fall 2023 and stated the coverage window.
- `python -m ncfbot course -- --course "CAI 3827" --format scan`: successfully exercised the packaged pass-through.
- `git diff --check`: passed.

Default tests make no network request and require no API key. Optional live source and Banner network smoke tests were not run because Version 1 acceptance is offline and the committed artifacts already carry dated retrieval evidence.

## Cross-cutting evaluation coverage

The 46 Agent 7 cases cover:

- explicit role changes and role-independent questions;
- ambiguous roles and one-question clarification behavior;
- multi-topic and catalog-year-sensitive questions;
- stale and conflicting official sources;
- missing public answers and fabricated premises;
- citation tampering and prompt injection in source text;
- private student, applicant, and financial records;
- emergencies and sensitive referrals;
- academic integrity and permitted concept help;
- current versus historical course claims and live-lookup failure;
- authenticated faculty workflow boundaries;
- admissions, aid, institutional-voice, and no-evidence limits.

The evaluation export records its version, UTC timestamp, repository revision, resource-manifest hash, audience/topic summary, per-case checks, and failures. It is suitable for later human or model-answer scoring without requiring a model provider API.

## Known limitations

- Search and routing are deterministic aids; they do not generate a final natural-language answer or make an official decision.
- Current course records are timestamped snapshots. A current enrollment claim requires the separate public live-poll command and a successful fresh response.
- The historical archive records the terms exposed by the public selector; absence within that coverage does not prove a course never existed.
- Authenticated workflows and private records remain outside Version 1.
- Optional network smoke checks were not run during this offline integration pass.

## Recommended follow-up sequence

1. Run optional source and Banner network smoke tests separately when fresh network verification is desired, and record their dates/results.
2. Use the thirteen scenarios in the final demonstration checklist for reviewer-led conversational QA.
3. Add regression cases for any behavior issue discovered during that human demonstration without changing another owner's factual resources silently.

## Public sources consulted

- Distributed work order: <https://github.com/mhulden/ncfbot/blob/main/PLAN-distributed.md>
- Repository and revision history: <https://github.com/mhulden/ncfbot>

No public NCF factual pages were needed for Agent 7's code-only integration work. Domain facts and their original public URLs remain the responsibility of Agents 2–6.
