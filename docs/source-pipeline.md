# Source Pipeline Architecture

**Owner:** Agent 5
**Version:** 1.1
**Last updated:** 2026-09-02

This document describes the NCFBot public-source discovery, fetching, conversion,
validation, and freshness pipeline. Every factual resource in the corpus passes
through this pipeline before it is trusted.

---

## Overview

The pipeline has five stages, each implemented as a standalone CLI tool:

```
Public Web
    │
    ▼
[survey_sources.py]   ← robots.txt + sitemaps → candidate JSONL (no bodies)
    │
    ▼  (human review creates a preliminary approved sidecar entry)
    │
[fetch_sources.py]    ← approved URLs only → raw bodies in .cache/sources/
    │
    ▼
[convert_sources.py]  ← cached bodies → .cache/converted/ (UNTRUSTED EVIDENCE)
    │
    ▼  (resource author writes original Markdown, citing public URLs)
    │
[validate_sources.py] ← .source.json sidecars + resource Markdown → pass/fail
    │
    ▼
[check_freshness.py]  ← sidecar metadata + optional network HEAD → overdue report
```

No stage automatically promotes content to an approved resource file. Human
authorship is required between the conversion and validation stages.

---

## Stage 1: survey_sources.py

**Purpose:** Discover candidate URLs from robots.txt and sitemaps without downloading
page bodies.

**Inputs:** robots.txt at `www.ncf.edu`; optionally `resources/inventory/survey-config.json`
**Outputs:** `resources/inventory/survey-candidates.jsonl`, `resources/inventory/survey-summary.md`

**What it does:**
- Reads robots.txt to find sitemap URLs (does not guess paths)
- Recursively parses sitemap indexes and urlsets within response, depth, sitemap,
  and candidate limits
- Enforces an HTTPS domain allowlist (`*.ncf.edu` only by default)
- Rejects cross-domain, authentication, private-network, and insecure redirects
- Uses no cookies, credentials, environment proxy credentials, or authenticated state
- Respects robots.txt Disallow rules
- Auto-rejects URLs with authentication signals in the path
- Classifies candidates by guessed topic and audience (heuristic, path-based only)
- Deduplicates by URL
- Rate-limits all requests (1 req/sec default)

**What it does NOT do:**
- Download page bodies
- Automatically approve any URL
- Bypass robots policy

**After running:** Treat `survey-candidates.jsonl` as a generated inventory, not an
approval ledger. Review a candidate in a private/incognito browser session. To approve
it, add a preliminary source entry to the intended `.source.json` sidecar with the
verified URL, actual verification time, `public_access_verified: true`, and
`sha256: null`. Record the review decision in `notes`. The sidecar will not pass final
validation until the source is fetched, hashed, and the resource is authored.

**Command:**
```bash
python tools/survey_sources.py
python tools/survey_sources.py --config resources/inventory/survey-config.json
python tools/survey_sources.py --dry-run   # no network, tests output structure
```

---

## Stage 2: fetch_sources.py

**Purpose:** Download page bodies for approved sources only.

**Inputs:** `.source.json` sidecars (reads `canonical_url` where `public_access_verified: true`)
and `resources/inventory/fetch-domain-allowlist.json`
**Outputs:** `.cache/sources/<sha256-prefix>/<hash>.body` + `<hash>.meta.json`

**What it does:**
- Validates every URL against the allowlist before fetching
- Rejects private/local network targets (localhost, RFC-1918 ranges)
- Rejects URLs with auth signals
- Detects authentication redirects and stops
- Enforces a narrow content-type allowlist (HTML, PDF, plain text, and approved
  cached-only Office documents)
- Enforces a 10 MB body size cap
- Rate-limits requests (1.5 sec default)
- Records SHA-256, retrieval timestamp, content-type, and redirect chain in `.meta.json`
- Caches by URL hash — skips re-download unless `--force` is passed
- Never sends cookies or credentials
- Exits nonzero if any approved URL is blocked or fails

**Cache location:** `.cache/sources/` (gitignored — never commit raw bodies)

**Command:**
```bash
python tools/fetch_sources.py --sidecar resources/students/academic-model.source.json
python tools/fetch_sources.py --all
python tools/fetch_sources.py --all --force   # re-fetch even if cached
python tools/fetch_sources.py --all --dry-run # show what would be fetched
```

---

## Stage 3: convert_sources.py

**Purpose:** Convert cached HTML or PDF bodies to readable text for resource authors.

**Inputs:** `.cache/sources/<hash>.body` + `.meta.json`
**Outputs:** `.cache/converted/<hash-prefix>.md` or `.txt` (gitignored)

**What it does:**
- Converts HTML: strips navigation, sidebars, scripts, and boilerplate; preserves
  headings, paragraphs, lists, tables, and links
- Converts PDF: extracts text with page markers (requires `pdfminer.six` or `pdftotext`)
- Prepends a prominent UNTRUSTED EVIDENCE header to every output file
- Reports optional dependencies clearly rather than silently failing

**What it does NOT do:**
- Promote converted text to resource Markdown
- Make authorship decisions

**Dependency note:** HTML conversion requires `beautifulsoup4 lxml`. PDF conversion
requires `pdfminer.six` or system `pdftotext` (poppler). These are optional —
the rest of the pipeline works without them. Approved Office documents may be
cached for hashing/provenance, but this tool intentionally does not convert them.

**Command:**
```bash
python tools/convert_sources.py --sidecar resources/students/academic-model.source.json
python tools/convert_sources.py --input .cache/sources/<hash> --format html
python tools/convert_sources.py --all --out .cache/converted
```

---

## Stage 4: validate_sources.py

**Purpose:** Validate all `.source.json` sidecars against the JSON schema and check
cross-references. Optionally build a combined corpus manifest.

**Inputs:** `schemas/source-record.schema.json`; all `*.source.json` files under `resources/`
**Outputs:** Pass/fail report; optionally `resources/generated/manifest.json`

**Checks performed:**
- JSON schema conformance (all required fields, correct types)
- `resource_file` is safe, exists, and is the Markdown file neighboring the sidecar
- Sidecar title matches the Markdown H1
- The final Markdown section is `Sources`, with URLs exactly matching the sidecar
- Markdown has a `Verified through:` line
- `sha256` is populated (warns if null)
- `public_access_verified` is true
- `review_after` is not already overdue
- Duplicate sidecar IDs across the corpus (corpus-level check)

**Manifest:** `--manifest` produces the atomic full-corpus index at
`resources/generated/manifest.json`, the machine-readable index of all corpus
sources. Agent 7's `doctor` and `search`
commands consume this. Never hand-edit the manifest — regenerate it by running
`validate_sources.py --all --manifest`. The tool refuses to build a manifest from
a single-sidecar validation.

**Command:**
```bash
python tools/validate_sources.py --all
python tools/validate_sources.py --all --manifest
python tools/validate_sources.py --sidecar resources/students/academic-model.source.json
```

Exit code 0 = all pass; 1 = failures found.

---

## Stage 5: check_freshness.py

**Purpose:** Report overdue review dates, hash changes, and (optionally) redirect
or HTTP errors for approved source URLs.

**Inputs:** All `*.source.json` files; cached body files (offline); live HEAD
requests (network mode)
**Outputs:** Issue report to stdout

**Offline checks:**
- `review_after` overdue or approaching (within 14 days)
- `sha256` in sidecar vs. SHA-256 of cached body — mismatch = source changed
- `effective_from` / `effective_through` sanity
- `volatility` vs. `review_after` interval reasonableness
- `public_access_verified` not set

**Network checks (opt-in):**
- Run all offline checks first
- HEAD each approved URL; detect 404, 401/403, other 4xx/5xx
- Reject unsafe, private, cross-allowlist, and authentication redirects before following
- Detect URL changes (canonical_url should be updated)

**What it does NOT do:**
- Rewrite resource Markdown when a source changes
- Auto-update sidecar metadata

**Command:**
```bash
python tools/check_freshness.py --offline
python tools/check_freshness.py --network
python tools/check_freshness.py --offline --sidecar resources/students/academic-model.source.json
```

Exit code 0 = no errors (warnings may be reported); 1 = one or more errors.

---

## Sidecar Quick Reference

Every resource Markdown file must have a neighboring `<name>.source.json`. Required fields:

| Field | Type | Notes |
|-------|------|-------|
| `id` | string (kebab-case) | Unique across corpus; stable once set |
| `resource_file` | string (path) | `resources/path/name.md` |
| `title` | string | Matches Markdown H1 |
| `audiences` | array | `students`, `faculty`, `outside` |
| `topics` | array | Short slugs e.g. `["registration", "add-drop"]` |
| `sources` | array | At least one entry |
| `sources[].canonical_url` | string (HTTPS URI) | Must appear in Markdown Sources section |
| `sources[].publisher` | string | Responsible office or catalog |
| `sources[].authority_type` | enum | `catalog`, `calendar`, `policy`, `office`, `program`, `directory`, `news`, `other` |
| `sources[].retrieved_at` | datetime | ISO 8601 UTC |
| `sources[].sha256` | string or null | 64-char hex; populate after fetch |
| `sources[].public_access_verified` | boolean | True only after human confirmation |
| `status` | enum | `current`, `historical`, `superseded` |
| `volatility` | enum | `daily`, `term`, `annual`, `stable` |
| `review_after` | date | ISO 8601 YYYY-MM-DD |
| `notes` | string | Known conflicts or gaps; empty string if none |

See `schemas/source-record.schema.json` for the full schema with all optional fields.

---

## Common Mistakes

| Mistake | Correct approach |
|---------|-----------------|
| Committing `.cache/` contents | Add to `.gitignore`; cache is local only |
| Setting `public_access_verified: true` without testing | Open the URL in a private/incognito window; confirm no login redirect |
| Pasting converted text into resource Markdown | Write original prose; cite the URL |
| Assuming `survey-candidates.jsonl` URLs are approved | They are candidates; manual review required |
| Updating `sha256` without re-reading the source | Always read the diff first; update Markdown if facts changed |
| Setting `volatility: stable` for tuition or deadlines | Use `annual` or `term` for anything that changes on a predictable cycle |
| Claiming a redirected URL works | Update `canonical_url` to the final URL; re-fetch |
