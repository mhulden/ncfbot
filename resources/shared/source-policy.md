# NCFBot Public Source Policy

Verified through: 2026-09-02

This document governs how public sources are selected, fetched, converted, stored,
and cited in the NCFBot corpus. All resource authors must follow these rules before
adding or updating any factual content.

---

## 1. What Counts as an Eligible Source

A source is eligible if and only if:

1. It is publicly reachable over HTTPS without authentication, credentials, or a
   university account.
2. It is hosted on an official NCF domain (`ncf.edu` and approved subdomains) or is
   an officially NCF-linked third-party system whose domain suffix is explicitly approved
   in `resources/inventory/fetch-domain-allowlist.json`.
3. It has been independently fetched and verified by a human (not assumed accessible).
4. Its `public_access_verified` field in the `.source.json` sidecar is `true`.

**Not eligible:** MyNCF, Canvas, Banner Self-Service authenticated pages, intranet
pages, staff-only handbooks, email, student records, any page that redirects to a
login screen, or any document obtained through a university account.

---

## 2. Source Authority by Topic

When multiple sources address the same topic, prefer them in this order:

| Priority | Source type | Example |
|----------|-------------|---------|
| 1 | Applicable catalog or controlling public policy | Undergraduate Catalog 2024-25 |
| 2 | Responsible office's current policy page | Registrar registration page |
| 3 | Current official academic calendar | Academic Calendar PDF |
| 4 | Official program or department page | AOC/major landing page |
| 5 | Official directory or profile | Faculty/staff directory |
| 6 | Current official announcement or news | NCF News post |
| 7 | Labeled historical material | Archived catalog edition |

Marketing pages, news articles, and social media posts may help discover facts but
are never the authority for binding requirements, deadlines, or procedures.

---

## 3. Volatility Classifications

Every `.source.json` must declare a `volatility` value. Use the table below to set
both `volatility` and `review_after`:

| Volatility | Meaning | Maximum `review_after` interval |
|------------|---------|--------------------------------|
| `daily` | Open/closed seats, event schedules, live enrollment | Do not cache as current; retrieve live or flag as stale |
| `term` | Course offerings, registration deadlines, dining hours | Verify each term; set `review_after` ≤ 4 months out |
| `annual` | Tuition, aid programs, catalogs, application requirements | Verify each year; set `review_after` ≤ 13 months out |
| `stable` | Institutional history, campus location, durable terminology | Verify yearly or when source hash changes |

---

## 4. Conflict Handling

When two approved sources disagree:

- Do **not** silently merge them into a consensus.
- Record the conflict explicitly in resource Markdown prose.
- Record it in the `notes` field of the `.source.json`.
- Identify which source has authority for the specific question (catalog year,
  applicable population, controlling office) and explain why.
- Tell the user what requires confirmation and which office owns it.
- Add an evaluation case for the conflict.

---

## 5. How Resource Authors Use the Pipeline

### Step 1 — Discover candidates
```bash
python tools/survey_sources.py --config resources/inventory/survey-config.json
# Review resources/inventory/survey-candidates.jsonl
```
The inventory is generated and must not be edited as an approval ledger. Confirm a
candidate in a private/incognito session and reject any login or personalized page.

### Step 2 — Record approval in a preliminary sidecar
Create or update the neighboring `.source.json` first. Add the verified canonical URL,
publisher, authority, actual public-verification timestamp, applicability fields, and
`public_access_verified: true`. Use `sha256: null` until the first controlled fetch and
record the reviewer/date/reason in `notes`. This preliminary sidecar is the approval
input; it is expected to fail final validation until the source and resource are complete.

### Step 3 — Fetch approved sources
```bash
# Fetch all approved URLs referenced by a sidecar
python tools/fetch_sources.py --sidecar resources/students/academic-model.source.json
```
Raw bodies land in `.cache/sources/` (gitignored). Never commit them.

### Step 4 — Convert for reading
```bash
python tools/convert_sources.py --sidecar resources/students/academic-model.source.json
# Output goes to .cache/converted/ — UNTRUSTED EVIDENCE, never commit
```

### Step 5 — Write original Markdown
Open the converted output as a reading aid only. Write your resource file in
your own words, citing the source URLs. Do not paste converted text directly.

### Step 6 — Finish provenance metadata
Copy the fetched body's SHA-256, retrieval timestamp, and usable last-modified value
from the cache metadata into the preliminary sidecar. Ensure the final Markdown
`Sources` section exactly matches the sidecar URLs.

### Step 7 — Validate
```bash
python tools/validate_sources.py --sidecar resources/students/academic-model.source.json
```
Fix all errors before opening a pull request.

### Step 8 — Check freshness before PR
```bash
python tools/check_freshness.py --offline --sidecar resources/students/academic-model.source.json
```

---

## 6. Copyright-Aware Storage

- Raw downloaded bodies go to `.cache/sources/` (gitignored). Do not commit them.
- Converted text goes to `.cache/converted/` (gitignored). Do not commit it.
- Resource Markdown files contain **original summaries** — not reproductions of
  source text. Short quotations are acceptable when quotation is essential for
  precision; always attribute them with a citation.
- PDFs and large HTML snapshots must not be committed to the repository.
- If a source explicitly prohibits reproduction, note this in the sidecar `notes`
  field and summarize rather than quoting.

---

## 7. What Happens When a Source Changes

After an explicit `fetch_sources.py --force` refresh, `check_freshness.py --offline`
hashes the cached body itself and compares it with the sidecar. If they differ, it
reports a change — it does **not** automatically rewrite the resource Markdown.
`check_freshness.py --network` adds safe reachability and redirect checks; it does not
silently replace the cached body or authored resource.

Resource authors must:
1. Read the changed source.
2. Determine what factual content, if any, changed.
3. Update the resource Markdown with original prose reflecting the change.
4. Update `sha256` and `retrieved_at` in the sidecar.
5. Update `review_after` to the next appropriate date.
6. Open a pull request with public evidence cited.

---

## 8. Authenticated and Private Sources

If the only useful guidance for a topic is behind authentication or in a private
document, the correct response is:

1. State explicitly in the resource that the information is not available in
   approved public sources.
2. Identify the responsible office and its public entry point.
3. Do **not** reconstruct private content from memory or inference.
4. Do **not** copy content from private systems accessed through a university account.

---

## Sources

- NCFBot PLAN-distributed.md §2 (Clean-Room Rule), §6.1–6.2 (Contracts), §8 (Authority & Freshness Policy)
  — internal project document, not a public source

*(This file documents project governance rules, not external facts. It does not require
a `.source.json` sidecar.)*
