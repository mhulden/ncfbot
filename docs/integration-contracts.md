# Integration Contracts

This document implements the shared interfaces in [PLAN-distributed.md](../PLAN-distributed.md). Agent 1 owns the bootstrap contract; Agents 5, 6, and 7 own the implementing schemas/tools. It is project design, not institutional evidence.

Required fields and paths from the work order are preserved here. Types, null handling, and the reserved manifest shape below make the interfaces explicit. Another student must review these contracts before bootstrap merge. Subsequent incompatible changes require the affected owners' review; never silently rename a field or weaken validation.

## 1. Common conventions

- Text files use UTF-8, LF line endings, and a trailing newline.
- Paths in metadata are repository-root-relative POSIX paths without a leading slash, `..` traversal, or machine-specific directories.
- IDs are stable, globally unique within their collection, and lowercase kebab-case. Resource and evaluation IDs are separate collections. Prefix IDs by audience/topic when helpful.
- Dates use `YYYY-MM-DD`; retrieval/generation timestamps use ISO 8601 UTC `YYYY-MM-DDTHH:MM:SSZ` (fractional seconds may be accepted by the owning schema).
- JSONL contains one JSON object per nonblank line, no array wrapper. Validation errors must identify the file and record/line where possible.
- `null` means unknown/not available where allowed. It is never interchangeable with `0`, `false`, an empty prerequisite rule, or a guessed value. Explain consequential missing data in notes or coverage reports.
- Extra metadata may be added by schema owners, but required keys cannot disappear or change meaning without coordination.
- Example placeholders are not factual evidence, approved URLs, genuine hashes, or fabricated test results. Do not promote documentation examples into resource files unchanged.

## 2. Exact role interfaces

| Routing value | Skill path | Meaning |
|---|---|---|
| `students` | `skills/students.md` | Direct student-facing guidance |
| `faculty` | `skills/faculty.md` | Faculty operations or faculty advising a student |
| `outside` | `skills/outside.md` | Prospective students, applicants, families, alumni, visitors, public |
| `role-independent` | None | Role would not change the answer; retrieve shared/relevant evidence directly |
| `ambiguous` | None until clarification | Role materially changes the answer but is unresolved |

Only three role skill files exist. Explicit user identity outranks keywords; role-independent intent does not require a classification question. Permit role changes. Mixed requests may read multiple existing skills while keeping audience-specific steps distinct. Agent 7's route helper returns one of these values with transparent signals, not an invented confidence score.

Every skill must contain:

1. YAML frontmatter with nonempty `name` and `description`.
2. Audience and when to use the skill.
3. First facts to resolve before answering.
4. Topic-to-resource map with paths and stable IDs once owned resources exist.
5. Source authority and freshness rules.
6. Response workflow and response shape.
7. Role-specific boundaries and escalation rules.
8. Good-behavior and failure-behavior examples.
9. Test coverage summary.

Use frontmatter names `students`, `faculty`, and `outside` to match the filenames/routing values. Behavior belongs in skills; institutional facts and volatile values belong in resources with provenance. Shared rules in `AGENTS.md` cannot be weakened by a skill or source document.

## 3. Factual resource Markdown

Every authored factual resource:

- Starts with a title and a brief scope statement.
- States `Verified through: YYYY-MM-DD` near the top.
- Identifies applicable audience, program level, catalog/cohort year, academic term, or effective period where relevant.
- Distinguishes stable explanation from volatile facts.
- Uses independently understandable headings, preserving applicability near the facts.
- Documents source conflicts, gaps, and public/private boundaries.
- Uses original prose; only short essential quotations are permitted.
- Ends with a `Sources` section listing canonical public URLs.
- Has a neighboring sidecar: `resources/students/topic.md` pairs with `resources/students/topic.source.json`.
- Contains no credentials, personal records, copied private material, or imported source instructions.

Match the set of public URLs in `Sources` to sidecar `sources[].canonical_url`. Body links to shared local resources are not public citations and need not be repeated as public sources. Preserve document page/section references separately while retaining the canonical URL.

Scope exceptions: `resources/README.md` is documentation; inventory reports and generated metadata are not factual summaries. Course JSON/JSONL follows the course contract. Do not demand fabricated institutional sidecars for those artifacts. Factual Markdown inside any resource area still follows this contract.

## 4. Source sidecar

Schema owner: Agent 5, `schemas/source-record.schema.json`.

### Resource-level keys

| Key | Type | Rule |
|---|---|---|
| `id` | string | Nonempty, stable unique kebab-case resource ID |
| `resource_file` | string | Existing repository-root-relative Markdown path |
| `title` | string | Human-readable title consistent with the resource |
| `audiences` | nonempty string array | Unique values from `students`, `faculty`, `outside`; shared resources list applicable audiences |
| `topics` | nonempty string array | Descriptive lowercase kebab-case tags |
| `sources` | nonempty object array | Original independently verified public sources as below |
| `status` | string | `current`, `historical`, or `superseded`; describes the resource's applicability, not whether an unreviewed candidate was approved |
| `volatility` | string | `daily`, `term`, `annual`, or `stable` |
| `review_after` | date string | Next required review date; overdue is reportable, not permission to silently update it |
| `notes` | string | Conflicts, unavailable information, replacement context, or empty string |

### Per-source keys

| Key | Type | Rule |
|---|---|---|
| `canonical_url` | string | Approved original public HTTPS URL, including required public query parameters |
| `publisher` | string | Responsible office, institution, or catalog publisher |
| `authority_type` | string | One of `catalog`, `calendar`, `policy`, `office`, `program`, `directory`, `news`, `other` |
| `retrieved_at` | UTC timestamp string | Actual successful retrieval time |
| `last_modified` | UTC timestamp string or null | Parsed upstream value if usable; otherwise null, not a guessed modification time |
| `effective_from` | date string or null | Published applicability start if known |
| `effective_through` | date string or null | Published applicability end if known |
| `academic_year` | string or null | Source's academic-year label when applicable; do not infer it from the retrieval date |
| `sha256` | string | 64 lowercase hexadecimal characters; hash of the retrieved source body bytes, not the authored summary |
| `public_access_verified` | boolean | Must be true for usable public evidence; a login response cannot count as verification |

### Optional structured constraints

Issue #37 adds two optional, backward-compatible resource-level arrays. Existing
sidecars do not need either field.

| Key | Shape | Rule |
|---|---|---|
| `required_resources` | objects with `resource_id`, `reason` | Each resource ID is kebab-case and unique within the array; the reason is nonempty. This metadata states a dependency but does not prove that an agent loaded it. |
| `conflicts` | objects with `conflict_id`, `status`, `sources`, `claims`, `applicability`, `responsible_office` | IDs are kebab-case and unique; status is `unresolved`, `resolved`, or `deferred`; every source is a canonical URL already present in top-level `sources`; source and claim arrays contain at least two positionally paired entries; applicability and responsible office are nonempty. |

Consumers use the schema and manifest record directly; they do not import the
source-pipeline validator. Enforcement also requires runtime resource-order
telemetry and final-answer checks, as demonstrated by Agent 7's bounded pilot.

Required nullable keys must remain present. Inverted effective dates, duplicate IDs, unsafe paths, false public verification, missing hashes, and source-footer mismatches are validation failures. Source reachability/factual currency require separate checks; syntactically valid metadata is not proof of correctness.

Illustrative shape only; placeholder strings must be replaced through real collection:

```json
{
  "id": "students-example-topic",
  "resource_file": "resources/students/example-topic.md",
  "title": "Example topic",
  "audiences": ["students"],
  "topics": ["example-topic"],
  "sources": [{
    "canonical_url": "https://example.org/replace-with-approved-original-source",
    "publisher": "Verified responsible publisher",
    "authority_type": "office",
    "retrieved_at": "YYYY-MM-DDTHH:MM:SSZ",
    "last_modified": null,
    "effective_from": null,
    "effective_through": null,
    "academic_year": null,
    "sha256": "REPLACE_WITH_ACTUAL_64_CHARACTER_SHA256",
    "public_access_verified": true
  }],
  "status": "current",
  "volatility": "term",
  "review_after": "YYYY-MM-DD",
  "notes": "Example only; not verified evidence."
}
```

### Approval is separate from status

Agent 5's inventory/approval input records `approved`, `deferred`, `rejected`, `historical`, or `superseded` with a URL, decision reason, reviewer, and review date. Fetching requires explicit authorization for that URL; mere presence in a candidate inventory is insufficient. A sidecar for reviewed material can serve as the explicit approval input under Agent 5's documented workflow. Deferred/rejected candidates never become retrieval evidence by setting `status: current`.

Historical and superseded material can be retained with explicit applicability. Search must penalize it for current operations and preserve its status in results. A historical catalog can still be relevant to a named cohort; select based on published applicability, not age alone.

## 5. Generated provenance interface

Agent 5 owns generation under `resources/generated/`; no one hand-edits a central source registry. Reserve `resources/generated/manifest.json` as the combined metadata index, generated from validated distributed sidecars.

Minimum manifest shape:

- `schema_version`: string, initially `"1"`.
- `generated_at`: actual UTC generation timestamp.
- `resources`: array sorted by resource `id`; each entry contains `sidecar_file` (root-relative path) and `record` (the full validated sidecar object).

For the same valid inputs, entry ordering and records are deterministic; `generated_at` may differ. Reject duplicate IDs and invalid sidecars rather than silently excluding them and calling the manifest complete. Report failures without replacing a valid manifest with a partial one. Agent 7 can reconstruct heading-level lexical search from the Markdown referenced by this manifest; no separately hand-maintained search index or vector store is required.

Agent 5 documents rebuilding and any additive metadata in `docs/source-pipeline.md`. Agent 7 consumes the recorded version, hashes the manifest for evaluation provenance, and checks it against source sidecars. An incompatible shape requires coordinated Agent 1/5/7 review.

## 6. Evaluation JSONL

Schema owner: Agent 7, `schemas/evaluation-case.schema.json`.

| Key | Type | Rule |
|---|---|---|
| `id` | string | Unique across all evaluation JSONL files |
| `audience` | string | `students`, `faculty`, `outside`, `role-independent`, or `ambiguous` |
| `topic` | string | Short kebab-case topic |
| `question` | string | User prompt, including non-sensitive role/context needed for a standalone case |
| `expected_skill` | string or null | Exact one of the three role paths; null when no role skill should be selected yet/at all |
| `expected_resource_ids` | string array | All listed resource IDs are expected evidence; empty for behavior-only, clarification, or unsupported cases |
| `must_include` | string array | Required concepts/behaviors, not necessarily verbatim answer substrings |
| `must_not_include` | string array | Forbidden claims/behaviors |
| `clarification_expected` | boolean | Whether a targeted question is required |
| `citation_required` | boolean | Whether public supporting citations are expected |
| `freshness_sensitive` | boolean | Whether term/date/currentness validation matters |
| `notes` | string | Review context, conflict scenario, limits, or empty string |

`expected_skill: null` prevents inventing a role-independent/ambiguous skill filename. It is also appropriate for immediate safety handling that must precede role routing; explain that in `notes`. `audience: ambiguous` describes role ambiguity, not every case with an unknown term. A known student needing a catalog year still routes to `skills/students.md` and may have `clarification_expected: true`.

For multi-turn or mixed-audience behavior, include sufficient non-sensitive context in the question/notes and split focused cases where a single expected skill cannot express all assertions. Agent 7 may add explicit context/multi-skill fields through coordinated schema changes; do not put an array into the current string field.

Example behavior-only case (no institutional facts):

```json
{"id":"cross-ambiguous-contract","audience":"ambiguous","topic":"routing","question":"How do I change an academic contract?","expected_skill":null,"expected_resource_ids":[],"must_include":["One short question distinguishing student-facing changes from faculty advising or sponsorship"],"must_not_include":["Assume the user is faculty","Invent a procedure"],"clarification_expected":true,"citation_required":false,"freshness_sensitive":false,"notes":"No identity or previous context is supplied; clarification precedes procedural advice."}
```

Agent 7's deterministic checks validate schema, routing, and retrieval expectations. Semantic `must_include`/`must_not_include` rules also require human/model answer review; keyword matching alone must not be reported as proof that generated answers are safe or correct. Exports record repository revision, resource manifest hash, evaluation version, and timestamp.

Required case counts remain those of the plan: at least 30 each for students, faculty, outside, and courses; at least 40 cross-cutting. Owners create their own files; Agent 1 does not create evaluation placeholders.

## 7. Course records and artifacts

Schema owner: Agent 6, `schemas/course-section.schema.json`; field/collection documentation: `docs/course-data.md`.

One normalized JSONL object represents one section. Preserve exact public term codes/CRNs as strings, including leading zeros if any. The identity is `(term_code, crn)` or a clearly documented equivalent public reference. Never group sections destructively just because they share a course code/title.

### Minimum section fields

All keys below must be present; use null for unavailable nullable scalar data and arrays for repeated data. Failed detail retrieval must be distinguished from a genuinely empty published value using detail/coverage metadata.

| Key | Type / meaning |
|---|---|
| `term_code` | Nonempty string; exact publicly discovered term code |
| `term_label` | String; original public label |
| `subject` | String; published subject |
| `course_number` | String; preserve published numbering |
| `course_display` | String; readable source-supported course code |
| `section` | String or null; public section identifier |
| `crn` | Nonempty string; public section reference |
| `title` | String; published course title |
| `instructors` | Array of strings; preserve multiple names, never infer missing instructors |
| `meetings` | Array of public meeting objects; Agent 6 documents nested fields in its schema |
| `meeting_summary` | String or null; readable meeting information without requiring consumers to parse nested fields |
| `credits_or_units` | Number, string, or null; retain published range/unit wording rather than forcing a scalar |
| `attributes` | Array of strings; source attributes |
| `description` | String or null; cleaned public text |
| `prerequisites` | String or null; source text, not a parsed eligibility rule |
| `corequisites` | String or null; source text |
| `restrictions` | String or null; source text |
| `detail_level` | String; `listing` for listings; `enriched` for detail-fetched records, with missing/failed detail fields documented |
| `source_url` | String; original approved public source |
| `retrieved_at` | UTC timestamp; actual retrieval of the listing/record |

Agent 6 may add field-level retrieval metadata, public mutual exclusions, catalog details, linked/cross-listed section fields, and other source-supported values. A later detail fetch does not make old listing/enrollment values fresh. If a required identity is absent or malformed, report/reject the record rather than invent it.

Enrollment fields are optional. Agent 6 must document exact field names and an enrollment-specific retrieval timestamp in the schema before other tools consume them. Preserve null/unknown distinctly from zero seats, no waitlist, or closed status. Only a successful fresh public response to the current question permits a live claim. A failed poll must not return a cached number labeled current. Historical observed enrollment may be retained with its old timestamp, never promoted to live availability.

### Required artifacts

- `resources/courses/public-terms.json`: top-level metadata and a `terms` array; exact term code, description, discovery timestamp, source endpoint, and view-only label state. Enumerate/paginate the public selector; do not guess a coverage range or term codes.
- `resources/courses/historical-sections.jsonl`: canonical section-level listing archive covering all discovered public terms or explicitly reporting incomplete/failed terms.
- Agent 6 also publishes current snapshot, title/subject scans, grouped history, and per-term completeness metadata within `resources/courses/`. Exact additional filenames and nested shapes are owned and documented by Agent 6; consumers must use that documentation instead of guessing them.
- Top-level/companion metadata includes tool/schema version, collection times, discovered coverage window, record counts, and per-term success/failure counts. JSONL rows remain section records; do not inject a metadata-only line into the section stream.
- Grouped history preserves the canonical archive and all observed codes, titles, instructors, terms, and attributes. Similarity is not official equivalency.

Rebuilds rediscover public terms, fetch all result pages using counts/pagination, re-fetch current/future terms, support resume/failure reporting, and write atomically. Historical details are fetched lazily for shortlisted sections, not every detail endpoint for every historical record. Past-term skipping needs an explicit stored hash/count policy.

## 8. Reserved tool interfaces

These commands are contracts, not implemented bootstrap features. Run from the repository root after the owners merge. Check their documented help before using optional flags. The plan permits improved source/course flags; owners must document changes and coordinate affected callers rather than silently breaking examples.

### Agent 5 — source pipeline

```sh
python tools/survey_sources.py --config resources/inventory/survey-config.json
python tools/fetch_sources.py --sidecar resources/students/academic-model.source.json
python tools/convert_sources.py --input .cache/sources/HASH --format html
python tools/validate_sources.py --all
python tools/check_freshness.py --offline
python tools/check_freshness.py --network
```

Survey is metadata-only. Fetching is approved/public-only; conversion does not approve facts. Validation rebuilds the source manifest from valid sidecars. Offline freshness reports metadata; network rechecks are explicit and never automatically overwrite authored resources.

### Agent 6 — course collection and queries

```sh
python tools/discover_public_terms.py --output resources/courses/public-terms.json
python tools/fetch_public_courses.py --all-public-terms --resume --output resources/courses
python tools/fetch_public_courses.py --term TERM --output resources/courses
python tools/build_course_history.py --input resources/courses/historical-sections.jsonl
python tools/query_courses.py --subject SUBJECT --format scan
python tools/query_courses.py --course CODE --format full
python tools/query_courses.py --input resources/courses/historical-sections.jsonl --course CODE --format history
python tools/query_courses.py --crn CRN --format json
python tools/fetch_course_details.py --term TERM --crn CRN --format json
python tools/poll_live_sections.py --term TERM --crn CRN
```

Query supports term, subject, course code, section, CRN, instructor, keyword, and attribute filters where data permits, plus scan/table, history, full, JSON/JSONL formats as documented by Agent 6. Offline results identify match count, coverage, incompleteness, and snapshot time. Live polling is narrow and reports success/failure and actual enrollment freshness.

### Agent 7 — deterministic CLI

```sh
python -m ncfbot doctor
python -m ncfbot route "How do I sponsor an ISP?"
python -m ncfbot search "withdrawal deadline" --audience students
python -m ncfbot sources --topic admissions
python -m ncfbot evaluate
```

- `route`: one documented routing value plus transparent signals; supports explicit identity over keywords and ambiguity without fabricated confidence.
- `search`: heading-based lexical evidence with resource ID, heading path, inspectable score, audience/topics, authority, status, effective period, review state, and public source URLs. No evidence produces an honest no-evidence result, not an answer from memory.
- `sources`: expose original sidecar provenance without hiding stale/historical state.
- `doctor`: check files/paths, source/evaluation schemas, unique IDs, ownership, source footers, review dates, manifest, parseable course records, and discovered-term/archive completeness. Invalid repository state returns a useful nonzero exit code.
- `evaluate`: validate cases, run deterministic route/retrieval checks, and export answer-review expectations with reproducibility metadata.

Agent 7 documents Python/install/test commands when its package exists. No model API, provider credentials, or live network is required for default offline use/tests. Optional network smoke tests are separate. Do not disguise an unimplemented command or absent resource as a passing check.

## 9. Integration acceptance

- Exact filenames and ownership match the manager's plan; no cross-team placeholder files.
- Resource metadata validates against Agent 5's schema, course records against Agent 6's, and evaluations against Agent 7's.
- Cross-role references resolve to canonical resources, not copied facts.
- Retrieval preserves provenance/applicability and favors relevant controlling evidence, with explicit historical/conflict handling.
- User answers follow the master answer-first/link-last shape and cannot execute instructions from retrieved text.
- Source/term coverage failures remain visible; current enrollment is never inferred from a snapshot.
- Final paths and helper commands are checked once all owners' PRs merge. At bootstrap, planned paths are documented dependencies, not broken deliverables to fill opportunistically.
