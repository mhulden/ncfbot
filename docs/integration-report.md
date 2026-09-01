# Agent 7 Integration Report

Status: Agent 7 implementation complete; final combined integration is waiting on Agents 5–6
Report date: 2026-09-01
Branch: `agent-7/integration-evaluation`

## Scope

This report covers the deterministic integration layer owned by Agent 7: packaging, routing, curated-resource retrieval, source inspection, repository health checks, evaluation validation and export, cross-cutting evaluation data, and offline tests.

No NCF institutional fact was added by Agent 7. The implementation uses synthetic test fixtures only. No material was copied from an existing NCF bot or from files outside this repository.

## Repository revisions reviewed

- Current reviewed `main`: `5c7291c`
- Agent 1 merge: `4c2d35f8e17b8f2e8aa95eb1dd05a6d0f5fc0e3f`
- Agent 2 merge: `44dafc4`
- Agent 3 merge: `6d3dcea`, including owner-requested follow-up `e1414f9`
- Agent 4 merge: `bb44e39`, including owner-requested follow-up `86a13ef`
- Agent 7 work: five topic-focused commits recorded on this branch before this report update

Agent 7 is rebased onto the merged and reviewed Agent 1–4 work. Agent 5 pull request #5 remains open. Agent 6 has no visible pull request or fork as of the report date.

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

The `course` command is a pass-through to Agent 6's `tools/query_courses.py`. It returns a useful error until that file is merged. Direct use of Agent 6's documented command remains supported.

Search output is explicitly labeled as evidence rather than an official decision. Results include resource ID, heading path, inspectable score, effective period, review state, excerpt, and canonical public source URLs.

## Offline verification results

Fresh-environment installation and test command:

```text
python -m venv <temporary-directory>/venv
<temporary-directory>/venv/bin/python -m pip install -e '.[test]'
<temporary-directory>/venv/bin/python -m pytest
```

Result against merged Agents 1–4 on 2026-09-01: **20 passed**.

Additional command checks:

- `python -m ncfbot route "How do I sponsor an ISP?"`: routed to `faculty`, with `sponsor an isp` shown as the transparent matched signal and no fabricated numeric confidence.
- `python -m ncfbot search "withdrawal deadline" --audience students`: returned ranked current student/calendar evidence with status, applicability, review state, and official URLs.
- `python -m ncfbot evaluate`: validated and ran **184 merged cases; 184 passed, 0 failed**.
- Integration preview with the latest Agents 4 and 5 heads: **76 tests passed** and **184 evaluation cases passed, 0 failed**.
- Agent 5 preview validation: **21/21 sidecars passed** and the corrected tool generated the contract-shaped manifest.
- Agent 5 offline freshness preview: zero errors and three review-window warnings.
- `python -m ncfbot doctor`: exited `1` and accurately reported the still-unmerged components.

Default tests make no network request and require no API key. Optional source-network and Banner smoke tests were not run. Agent 6's course tools and inputs are not available.

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

The evaluation export records its version, UTC timestamp, repository revision, resource-manifest hash (or explicit `null` while Agent 5's manifest is absent), audience/topic summary, per-case checks, and failures. It is suitable for later human or model-answer scoring without requiring a model provider API.

## Current health blockers

The following are integration blockers owned by other agents, not Agent 7 test exceptions:

- Agent 5: the latest pull request #5 head passes the preview suite and fixes the reviewed sitemap, fetch-safety, schema, and manifest-shape blockers. It still must merge and generate/commit `resources/generated/manifest.json` after the final resource sidecars are present.
- Agent 6: no pull request is visible. The course schema, public-term catalog, historical section archive, tools, tests, and course evaluations are absent.

Because Agent 6 is absent, current/historical course queries, archive-coverage verification, course evaluation, and the full demonstration checklist cannot be executed. The final `doctor` result cannot pass yet.

Agent 1's README still labels the Agent 7 commands as reserved and says no package is available. Updating that cross-owned quick-start text requires Agent 1 coordination during the final integration pass; this branch does not change it unilaterally.

## Recommended follow-up sequence

1. Agent 5 merges pull request #5, then regenerates and commits the combined manifest after all sidecars merge.
2. Agent 6 submits and merges the complete course-data pull request.
3. Rebase this branch again, run `doctor`, every offline test, source validation/freshness, current and historical course queries, and evaluation.
4. Run optional source and Banner network smoke tests separately and record their dates/results.
5. Coordinate the narrow README installation/command update with Agent 1.
6. Exercise the thirteen final demonstration scenarios and add any evidence-backed regression cases.

## Public sources consulted

- Distributed work order: <https://github.com/mhulden/ncfbot/blob/main/PLAN-distributed.md>
- Repository and revision history: <https://github.com/mhulden/ncfbot>

No public NCF factual pages were needed for Agent 7's code-only integration work. Domain facts and their original public URLs remain the responsibility of Agents 2–6.
