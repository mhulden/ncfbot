# Public Banner course data

Scope: Agent 6's independently collected, anonymous public course-listing subsystem. It supports section discovery and historical observations; it does not perform registration or decide eligibility.

Verified through: 2026-08-31

## Public source and access boundary

The NCF Office of the Registrar's public [Class Schedule & Registration](https://www.ncf.edu/departments/registrar/class-schedule-registration/) page links directly to the [Banner Select a Term page](https://banapps02.ncf.edu/StudentRegistrationSsb/ssb/term/termSelection?mode=search). Both were reachable without an account on August 31, 2026. Banner issued a transient `Secure`, `HttpOnly`, `SameSite=None` `JSESSIONID`; the tools keep that cookie only in an in-memory cookie jar for one retrieval session.

The Banner page displays Ellucian's privacy/analytics notice. No root `robots.txt` was published at `https://banapps02.ncf.edu/robots.txt` when checked (HTTP 404). The direct Registrar link establishes the intended public class-search entry point; it is not permission to access authenticated registration functions. These tools identify themselves, use bounded pages and configurable delays, never accept credentials, and never persist cookies.

Excluded systems include MyNCF, Canvas, authenticated Self-Service Banner, registration actions, saved sessions, and private records. Raw detail fragments are cached under `resources/courses/.cache/details/`, which is excluded by the Agent 6-owned `resources/courses/.gitignore`. A caller can use `--no-cache` or an explicit temporary `--cache-dir` instead.

## Anonymous request sequence

Each term-scoped retrieval uses a fresh `BannerSession`:

1. `GET /StudentRegistrationSsb/ssb/term/termSelection?mode=search` establishes the anonymous session.
2. `GET /StudentRegistrationSsb/ssb/classSearch/getTerms` uses `searchTerm`, `offset`, and `max`. Discovery starts at offset 1 and continues until a page is empty, short, or yields no new exact codes.
3. `POST /StudentRegistrationSsb/ssb/term/search?mode=search` sends the exact selected `term` plus empty public optional fields. A valid response names `/StudentRegistrationSsb/ssb/classSearch/classSearch` as `fwdURL`.
4. `GET /StudentRegistrationSsb/ssb/classSearch/classSearch` completes the term-scoped public search bootstrap.
5. `GET /StudentRegistrationSsb/ssb/searchResults/searchResults` sends `txt_term`, `pageOffset`, `pageMaxSize`, and stable sort fields. Collection continues until the number of unique `(term_code, crn)` records equals `totalCount`; a stalled or changing total is a failure.
6. A shortlisted section may use `getCourseDescription`, `getSectionPrerequisites`, `getCorequisites`, `getRestrictions`, `getCourseMutuallyExclusions`, `getSectionCatalogDetails`, `getLinkedSections`, and `getXlstSections` with its exact term and CRN.

AJAX requests send `X-Requested-With: XMLHttpRequest`, an appropriate JSON `Accept` header, and the public class-search `Referer`. Detail responses are HTML fragments, not structured rule trees.

## Artifacts

| Path | Meaning |
|---|---|
| `resources/courses/public-terms.json` | Terms actually exposed by the selector, discovery time, endpoint, view-only label state, and observed earliest/latest codes. |
| `resources/courses/historical-sections.jsonl` | Canonical offline archive; one JSON object per public section. |
| `resources/courses/historical-sections.meta.json` | Archive coverage, counts, per-term completeness/failure state, source, versions, and collection time. |
| `resources/courses/course-fetch-state.json` | Resume evidence. A past term is reused only when its stored record count and normalized SHA-256 still match the archive. |
| `resources/courses/course-fetch-failures.json` | Explicit failed-term report; an empty array means no observed collection failure. |
| `resources/courses/course-scan.md` | Compact title/subject/term discovery view derived from the archive. |
| `resources/courses/current-sections.jsonl` | Explicit-term snapshot produced by `--term`; it is overwritten atomically on a successful new explicit-term collection. |
| `resources/courses/current-sections.meta.json` | Current snapshot term, count, retrieval time, detail level, and failures. |
| `resources/courses/current-course-scan.md` | Human-readable scan of the explicit-term snapshot. |
| `resources/courses/course-history.json` | Conservative grouping by exact normalized subject and exact published course number. |

JSONL contains section records only. Metadata never appears as a fake section row. All durable outputs use a temporary file, `fsync`, and `os.replace` so an interrupted generation does not replace a valid artifact with a partial file.

## Section record fields

Identity is the exact pair `(term_code, crn)`. Distinct sections are never collapsed. `schemas/course-section.schema.json` is normative.

Required keys are:

- `term_code`, `term_label`, `subject`, `course_number`, `course_display`, `section`, `crn`, and `title`;
- `instructors`, `meetings`, `meeting_summary`, `credits_or_units`, and `attributes`;
- `description`, `prerequisites`, `corequisites`, `restrictions`, `mutual_exclusions`, `catalog_details`, `linked_sections`, and `cross_listed_sections`;
- `detail_level`, `detail_status`, `source_url`, `retrieved_at`, and `enrollment`.

`meetings` preserves days, source `HHMM` begin/end times, dates, building/room, campus, meeting/schedule type, and any meeting-level instructors. `meeting_summary` is a convenience rendering, not another source.

`detail_level` is `listing` or `enriched`. `detail_status` distinguishes `not_requested`, `success`, `partial`, and `failed`. Prerequisite/corequisite/restriction values remain cleaned published text; they are not personalized eligibility decisions.

When listing enrollment fields are present, `enrollment` contains `status`, `maximum`, `enrolled`, `seats_available`, `wait_capacity`, `wait_count`, `wait_available`, `open_section`, `retrieved_at`, and `freshness`. Archive/current snapshot rows use `freshness: snapshot`. Only `poll_live_sections.py` changes a successful fresh response to `freshness: live`. `open_section` and available seats do not establish registration eligibility.

## Commands

Discover the exact public term catalog:

```sh
python tools/discover_public_terms.py --output resources/courses/public-terms.json
```

Build or resume the complete historical archive. With `--resume`, omit `--current-term` to refetch every term; supply a selector-discovered current code to force that code and lexically later codes to refresh while count/hash-verified older rows may be retained:

```sh
python tools/fetch_public_courses.py --all-public-terms --resume --current-term TERM --output resources/courses
```

Create an explicit current snapshot. Detail enrichment is opt-in because it performs eight additional bounded requests per section:

```sh
python tools/fetch_public_courses.py --term TERM --output resources/courses
python tools/fetch_public_courses.py --term TERM --enrich-details --output resources/courses
```

Recommended quick-start workflow:

```sh
python tools/query_courses.py --subject SUBJECT --format scan
python tools/query_courses.py --course CODE --format full
python tools/query_courses.py --input resources/courses/historical-sections.jsonl --course CODE --format history
python tools/fetch_course_details.py --term TERM --crn CRN --format json
python tools/poll_live_sections.py --term TERM --crn CRN
```

`query_courses.py` filters by term, subject, course, section, CRN, instructor, keyword, and attribute. Formats are `scan`, `table`, `history`, `full`, `json`, and `jsonl`. Human formats state match count, coverage, timestamp, and known incompleteness. `--input` makes the same tool work with a current snapshot or historical archive.

## Completeness, freshness, and common mistakes

The observed selector count and coverage are not constants. On August 31, 2026 it exposed 26 exact codes from Spring 2017 through Fall 2026, all labeled view-only. Rebuilds rediscover the selector; tools do not probe guessed term codes. A substring such as `2008` may be part of a term code or a course number and must not be interpreted as a year without exact selector evidence.

The committed August 31, 2026 collection contains 5,103 distinct section records. All 26 discovered terms completed with their unique record counts equal to Banner's reported `totalCount`; the companion metadata records zero incomplete terms. The committed explicit Fall 2026 listing snapshot contains 273 sections and remains a timestamped snapshot, not a promise of present enrollment status.

An archive is complete only when every discovered term reports success and its unique record count equals Banner's `totalCount`. Failures remain in metadata and cause the all-term command to exit 2 after preserving all successfully collected rows. No result proves only that no matching section appears inside the documented coverage; it does not prove a course never existed.

Historical enrollment is an observation at `retrieved_at`, never current availability. A failed live poll returns `current: false`, no section values, and a nonzero exit. It does not fall back to cached numbers.

Course history groups only exact subject/course-number pairs. A changed code does not prove a different course, and a matching title does not prove official equivalency or nonequivalency. Automated renumbering/equivalency inference is a stretch goal and is deliberately absent from Version 1.

## Verification

Default unit tests are offline and use small, newly authored synthetic public-like fixtures:

```sh
python tests/test_courses.py -v
```

Network smoke checks are separate and dated. They should use temporary output/cache paths before replacing committed artifacts.

## Sources

- [NCF Office of the Registrar — Class Schedule & Registration](https://www.ncf.edu/departments/registrar/class-schedule-registration/)
- [NCF public Banner — Select a Term](https://banapps02.ncf.edu/StudentRegistrationSsb/ssb/term/termSelection?mode=search)
