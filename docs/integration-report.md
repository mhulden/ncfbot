# Agent 7 Integration Report

Status: Agent 7 implementation complete; final combined integration is waiting on Agents 2–6
Report date: 2026-08-31
Branch: `agent-7/integration-evaluation`

## Scope

This report covers the deterministic integration layer owned by Agent 7: packaging, routing, curated-resource retrieval, source inspection, repository health checks, evaluation validation and export, cross-cutting evaluation data, and offline tests.

No NCF institutional fact was added by Agent 7. The implementation uses synthetic test fixtures only. No material was copied from an existing NCF bot or from files outside this repository.

## Repository revisions reviewed

- Baseline `main` after bootstrap: `4c2d35f8e17b8f2e8aa95eb1dd05a6d0f5fc0e3f` (merge of Agent 1 pull request #1)
- Agent 1 implementation: `6453c8bdebe75d0c26e0d9c747c5fd6140350139`
- Agents 2–6 merges: not available on the public repository as of 2026-08-31
- Agent 7 work: three topic-focused commits recorded by the pull request

Agent 7 was rebased onto Agent 1's merged bootstrap contract. At final review time, the remote exposed only `main`; Agent 2's student-domain pull request #2 was open, and the domain, source-pipeline, and course-data deliverables had not been merged.

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

Result on 2026-08-31: **20 passed**.

Additional command checks:

- `python -m ncfbot route "How do I sponsor an ISP?"`: routed to `faculty`, with `sponsor an isp` shown as the transparent matched signal and no fabricated numeric confidence.
- `python -m ncfbot search "withdrawal deadline" --audience students`: returned honest no-evidence output because no domain resources have merged.
- `python -m ncfbot sources --topic admissions`: returned no matching validated resources because no domain resources have merged.
- `python -m ncfbot evaluate`: validated and ran **46 cases; 46 passed, 0 failed**.
- `python -m compileall -q ncfbot tests`: passed.
- `python -m ncfbot doctor`: exited `1` and accurately reported the unmerged required components.

Default tests make no network request and require no API key. Optional live-source and Banner smoke tests were not run because the owning tools and inputs are not yet present.

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

- Agents 2–4: the three exact role skills and factual resource corpus;
- Agent 5: source schema, generated source manifest, validation tool, and resource directory contract outputs;
- Agent 6: course schema, public-term catalog, historical section archive, and query tool.

Because these files are absent, combined resource retrieval, source validation, current/historical course queries, final archive-coverage verification, and the full demonstration checklist cannot yet be executed.

Agent 1's README still labels the Agent 7 commands as reserved and says no package is available. Updating that cross-owned quick-start text requires Agent 1 coordination during the final integration pass; this branch does not change it unilaterally.

## Recommended follow-up sequence

1. Rebase Agents 2–6 on Agent 1's merged contract and merge their owned deliverables.
2. Rebase this branch again, then run `python -m ncfbot doctor` and the complete offline test suite.
3. Resolve contract failures through the owning agent rather than weakening checks or rewriting domain facts.
4. Run source and Banner network smoke tests only through the owning tools' explicit opt-in modes; record dates and results here.
5. Coordinate the narrow README installation/command update with Agent 1.
6. Exercise the thirteen final demonstration scenarios and add any evidence-backed regression cases.

## Public sources consulted

- Distributed work order: <https://github.com/mhulden/ncfbot/blob/main/PLAN-distributed.md>
- Repository and revision history: <https://github.com/mhulden/ncfbot>

No public NCF factual pages were needed for Agent 7's code-only integration work. Domain facts and their original public URLs remain the responsibility of Agents 2–6.
