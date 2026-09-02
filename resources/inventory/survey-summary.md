# NCFBot Public Source Survey

**Surveyed:** 2026-09-02T15:19:26Z  
**Tool version:** survey_sources.py 0.2.0  
**Seed:** https://www.ncf.edu/robots.txt  
**Allowed domains:** ncf.edu  

## Summary

| Metric | Count |
|--------|-------|
| Candidates discovered | 2268 |
| Candidates retained | 2268 |
| Candidates truncated by configured cap | 0 |
| Auto-rejected (auth signals) | 0 |
| Remaining candidates | 2268 |

## By Guessed Topic

| Topic | Count |
|-------|-------|
| other | 1426 |
| directory | 464 |
| news | 194 |
| admissions | 56 |
| programs | 50 |
| alumni | 16 |
| wellness | 15 |
| about-ncf | 12 |
| visit | 12 |
| registrar | 5 |
| graduation | 4 |
| library | 4 |
| advising | 3 |
| housing-dining | 2 |
| policy | 2 |
| athletics | 1 |
| calendar | 1 |
| financial-aid | 1 |

## By Guessed Audience

| Audience | Count |
|----------|-------|
| unknown | 2111 |
| outside | 66 |
| faculty | 58 |
| students | 33 |

## Next Steps

1. Review `survey-candidates.jsonl` as generated, read-only discovery metadata.
2. Approve a URL by recording its verified public URL in the intended preliminary `.source.json` sidecar.
3. Run `fetch_sources.py` against that sidecar, then finish its hashes and authored resource.

## Notes

- This file is machine-generated. Do not edit by hand.
- URL classifications are heuristic guesses from path patterns only — no page bodies were downloaded.
- `likely_authenticated: true` URLs were auto-rejected and must not be fetched.
- Re-run this script to refresh the candidate list; compare diffs to detect new or removed pages.
