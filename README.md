<img src="./mrmanatee2.png" alt="Mr. Manatee" width="200">

# NCF Bot

A clean-room, public-information assistant for New College of Florida, designed for current students, faculty (including faculty advisors), and outsiders such as prospective students, families, alumni, visitors, and community members.

**This is not an official NCF assistant or employee.** It explains public evidence and routes people to responsible offices; it cannot decide individual cases or replace professional advice.

## Current status

This branch contains **Agent 1's bootstrap governance**, not a finished bot. The three skills, factual resources, schemas, Python package, source tools, course archive, and automated tests are other teams' deliverables. They are intentionally not created as placeholders. Commands below marked **reserved** will work only after their owners implement and merge them.

[PLAN-distributed.md](PLAN-distributed.md) is the manager-owned implementation work order. It supersedes the individual proposals: Version 1 uses a reviewed, high-value public corpus, not an indiscriminate whole-site mirror. Agent 1 merges first; Agents 2–6 build their domains and tools; Agent 7 performs final integration.

## Version 1

- An agent reads [AGENTS.md](AGENTS.md), routes the question, loads a role skill if needed, and retrieves relevant public evidence.
- The agent gives a direct explanation, applicability, next action, warnings when necessary, and concise official links at the end.
- Deterministic helpers support routing, lexical search, provenance inspection, health checks, course queries, and evaluation. They do not generate the final natural-language answer or require a model API key.
- Public course tooling separates historical listings, current snapshots, and fresh section-level enrollment checks. The archive covers the terms actually exposed by the public source, not a promised fixed year range.
- No private records, Canvas, authenticated systems, user accounts, transcript storage, write actions for users, public deployment, or production web UI are included. No provider-specific adapter, embeddings, or vector database is required.

## Clean-room rule

All institutional evidence must be independently retrieved from its original approved public location. Do not copy prompts, prose, resources, downloads, code, fixtures, or exports from an existing bot or parent/current-bot directory. Files outside this repository and individual proposals are not factual authorities. Public reachability is not proof of currency, authority, or permission to redistribute a full document.

Never use private accounts, records, credentials, saved authenticated cookies, or Canvas MCP. The only session exception is a short-lived anonymous cookie issued by the public course search and used only by that approved workflow. See [public-source policy](docs/public-source-policy.md).

## Directory map and ownership

| Area | Owner | Responsibility |
|---|---|---|
| `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, three governance documents in `docs/`, `resources/README.md` | Agent 1 | Bootstrap instructions and contracts |
| `skills/students.md`, `resources/students/`, shared academic calendar, student evaluations | Agent 2 | Student academic/public-support domain |
| `skills/faculty.md`, `resources/faculty/`, shared office routing and sensitive referrals, faculty evaluations | Agent 3 | Faculty domain and cross-role referrals |
| `skills/outside.md`, `resources/outside/`, shared glossary, outside evaluations | Agent 4 | Admissions and public information |
| Source tools/schema, inventory, generated manifest, shared source policy, `.gitignore` | Agent 5 | Reviewed collection, provenance, freshness |
| Course tools/schema, `resources/courses/`, course evaluations | Agent 6 | Public course archive, queries, live checks |
| `ncfbot/`, `pyproject.toml`, evaluation schema, integration tests/report | Agent 7 | Deterministic CLI and final integration |

The exact file-level ownership and branch names are in [CONTRIBUTING.md](CONTRIBUTING.md). Do not create other teams' missing files.

## Agent-native use

1. Open this repository as the agent's working directory.
2. Have the agent read `AGENTS.md` before answering an NCF question.
3. Ask a question. Explicit identity determines the appropriate role when it matters; role-independent questions do not require classification.
4. The agent reads only the needed skill/resource sections and their `.source.json` provenance.
5. It uses available approved helpers, verifies applicability and freshness, and answers with supporting public links at the end.

At the bootstrap stage, the agent must honestly report missing evidence and tools. Reading the master instructions alone does not provide verified NCF facts. Do not claim the corpus, website survey, or course archive has already been collected.

## Reserved CLI quick start — Agent 7

Run these from the repository root **after integration**, following the Python version and installation instructions Agent 7 will supply with `pyproject.toml`. No package or installation command is available in this bootstrap PR; these are interface commitments, not passing test results.

```sh
python -m ncfbot doctor
python -m ncfbot route "How do I sponsor an ISP?"
python -m ncfbot search "withdrawal deadline" --audience students
python -m ncfbot sources --topic admissions
python -m ncfbot evaluate
```

- `doctor`: check required files, provenance, schemas, IDs, paths, freshness, generated outputs, and course coverage; fail clearly on invalid state.
- `route`: show `students`, `faculty`, `outside`, `role-independent`, or `ambiguous` and transparent matched signals.
- `search`: show evidence excerpts, resource ID, heading, score, effective period, review state, and public URLs. It is not an official decision or generated answer.
- `sources`: inspect public provenance by topic.
- `evaluate`: validate cases and run deterministic routing/retrieval checks; export cases for separate human/model answer review.

Default validation/tests must run offline without an API key. Optional network checks are separate and explicitly requested.

## Reserved source and course workflows — Agents 5 and 6

These commands are not implemented at bootstrap. Replace uppercase arguments with values discovered from approved sources; do not guess a term or CRN.

```sh
python tools/validate_sources.py --all
python tools/check_freshness.py --offline
python tools/query_courses.py --subject SUBJECT --format scan
python tools/query_courses.py --course CODE --format full
python tools/query_courses.py --input resources/courses/historical-sections.jsonl --course CODE --format history
python tools/fetch_course_details.py --term TERM --crn CRN --format json
python tools/poll_live_sections.py --term TERM --crn CRN
```

Validation, offline freshness checks, and course queries use local files; historical detail fetching and live polling may contact the public source. A snapshot is never proof of current availability. Agent 6 will document exact coverage, field names, and failure behavior in `docs/course-data.md`; Agent 5 will document source collection and manifest rebuilding in `docs/source-pipeline.md`.

## Review and development

- [Contribution workflow](CONTRIBUTING.md): ownership, clean-room attestation, tests, PR content, and merge order.
- [Architecture](docs/architecture.md): boundaries, runtime flow, and manual routing traces.
- [Integration contracts](docs/integration-contracts.md): filenames, field types, schemas, and helper interfaces.
- [Resource authoring guide](resources/README.md): original summaries, sidecars, source footers, cross-role references, and maintenance.

Agent 1 changes are documentation-only. Before merge, another student must review the integration contracts. Agent 7 will later publish the combined test results and exact installation workflow; bootstrap review must not be represented as an end-to-end bot test.
