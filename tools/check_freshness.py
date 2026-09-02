#!/usr/bin/env python3
"""
check_freshness.py — Agent 5: freshness and staleness reporter

Reports overdue review dates, sources with changed hashes, redirect chains,
missing sidecars, and effective-period problems. Does NOT automatically
rewrite resource files when a source changes — it reports and stops.

Usage:
    # Offline check (metadata only, no network)
    python tools/check_freshness.py --offline

    # Network recheck (includes offline checks, then safely re-HEADs approved sources)
    python tools/check_freshness.py --network

    # Check a single sidecar
    python tools/check_freshness.py --sidecar resources/students/academic-model.source.json --offline

Exit codes:
    0 — no issues found
    1 — one or more issues found (check stdout for details)
"""

import argparse
import hashlib
import json
import logging
import time
import urllib.parse
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("check_freshness")

RESOURCES_DIR = Path("resources")
CACHE_DIR = Path(".cache/sources")
RATE_LIMIT_SECONDS = 1.5
REQUEST_TIMEOUT = 15
USER_AGENT = "ncfbot-freshness/0.2 (+https://github.com/mhulden/ncfbot)"

AUTH_SIGNALS = [
    "login", "signin", "auth", "sso", "myncf", "canvas",
    "self-service", "secure", "portal", "myaccount",
]


# ---------------------------------------------------------------------------
# Issue types
# ---------------------------------------------------------------------------

class Issue:
    def __init__(self, severity: str, sidecar: str, source_url: str, message: str):
        self.severity = severity  # "error" | "warning" | "info"
        self.sidecar = sidecar
        self.source_url = source_url
        self.message = message

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.sidecar} | {self.source_url or '—'}\n  {self.message}"


# ---------------------------------------------------------------------------
# Offline checks
# ---------------------------------------------------------------------------

def check_sidecar_offline(sidecar_path: Path) -> list[Issue]:
    issues = []
    sid = str(sidecar_path)

    try:
        with sidecar_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        issues.append(Issue("error", sid, "", f"Could not parse sidecar: {exc}"))
        return issues

    # Check resource_file exists
    resource_path = Path(data.get("resource_file", ""))
    if not resource_path.exists():
        issues.append(Issue("error", sid, "", f"resource_file missing: {resource_path}"))

    # Check review_after
    review_str = data.get("review_after", "")
    if not review_str:
        issues.append(Issue("warning", sid, "", "review_after is missing or empty"))
    else:
        try:
            review_date = date.fromisoformat(review_str)
            days_overdue = (date.today() - review_date).days
            if days_overdue > 0:
                issues.append(Issue(
                    "error", sid, "",
                    f"review_after {review_str} is overdue by {days_overdue} day(s)"
                ))
            elif days_overdue > -14:
                issues.append(Issue(
                    "warning", sid, "",
                    f"review_after {review_str} is coming up in {-days_overdue} day(s)"
                ))
        except ValueError:
            issues.append(Issue("error", sid, "", f"review_after is not a valid date: {review_str!r}"))

    # Check each source
    for i, src in enumerate(data.get("sources", [])):
        url = src.get("canonical_url", f"<source[{i}]>")

        # Hash check against cache
        cached_sha = _cached_sha256(url)
        recorded_sha = src.get("sha256")

        if recorded_sha is None:
            issues.append(Issue(
                "warning", sid, url,
                "sha256 is null — run fetch_sources.py to populate"
            ))
        elif cached_sha and cached_sha != recorded_sha:
            issues.append(Issue(
                "error", sid, url,
                f"sha256 CHANGED: recorded={recorded_sha[:12]}... cached={cached_sha[:12]}...\n"
                "  Source content has changed. Review and update the resource Markdown."
            ))
        elif cached_sha and cached_sha == recorded_sha:
            log.debug("Hash match for %s", url)

        # Effective period sanity
        eff_from = src.get("effective_from")
        eff_through = src.get("effective_through")
        if eff_from and eff_through:
            try:
                effective_from = date.fromisoformat(eff_from)
                effective_through = date.fromisoformat(eff_through)
            except ValueError:
                issues.append(Issue(
                    "error", sid, url,
                    "effective_from/effective_through must be ISO dates when populated"
                ))
            else:
                if effective_from > effective_through:
                    issues.append(Issue(
                        "error", sid, url,
                        f"effective_from ({eff_from}) is after effective_through ({eff_through})"
                    ))
                if data.get("status") == "current" and effective_through < date.today():
                    issues.append(Issue(
                        "warning", sid, url,
                        f"current resource source effective period ended on {eff_through}"
                    ))
        else:
            for label, value in (("effective_from", eff_from), ("effective_through", eff_through)):
                if value:
                    try:
                        date.fromisoformat(value)
                    except ValueError:
                        issues.append(Issue(
                            "error", sid, url, f"{label} is not a valid ISO date: {value!r}"
                        ))

        # public_access_verified
        if not src.get("public_access_verified"):
            issues.append(Issue(
                "error", sid, url,
                "public_access_verified is not true — must be manually confirmed before fetching"
            ))

    # Volatility vs review_after sanity
    volatility = data.get("volatility", "")
    if review_str and volatility:
        try:
            review_date = date.fromisoformat(review_str)
            today = date.today()
            interval_days = (review_date - today).days
            max_intervals = {"daily": 1, "term": 120, "annual": 400, "stable": 400}
            max_days = max_intervals.get(volatility, 400)
            if interval_days > max_days:
                issues.append(Issue(
                    "warning", sid, "",
                    f"review_after ({review_str}) is {interval_days} days away, "
                    f"but volatility={volatility!r} suggests at most {max_days} days"
                ))
        except ValueError:
            pass

    return issues


def _cached_sha256(url: str) -> Optional[str]:
    """Return the SHA-256 of the cached body for this URL, or None if not cached."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    body_path = CACHE_DIR / url_hash[:2] / (url_hash + ".body")
    if not body_path.exists():
        return None
    try:
        digest = hashlib.sha256()
        with body_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Network checks
# ---------------------------------------------------------------------------

def check_sidecar_network(sidecar_path: Path) -> list[Issue]:
    """Re-HEAD all approved source URLs to detect redirects, 404s, and auth walls."""
    try:
        import requests
    except ImportError:
        raise SystemExit("Network checks require requests: pip install requests")

    issues = []
    sid = str(sidecar_path)

    try:
        with sidecar_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        issues.append(Issue("error", sid, "", f"Could not parse sidecar: {exc}"))
        return issues

    from fetch_sources import ALLOWED_DOMAINS
    from source_http import make_no_cookie_session, validate_public_url

    session = make_no_cookie_session(USER_AGENT, "text/html,application/pdf,*/*;q=0.5")

    for src in data.get("sources", []):
        if not src.get("public_access_verified"):
            continue
        url = src.get("canonical_url", "")
        if not url:
            continue

        initial_error = validate_public_url(url, ALLOWED_DOMAINS, AUTH_SIGNALS)
        if initial_error:
            issues.append(Issue("error", sid, url, f"Blocked network check: {initial_error}"))
            continue

        time.sleep(RATE_LIMIT_SECONDS)
        try:
            current_url = url
            for redirect_count in range(6):
                target_error = validate_public_url(
                    current_url,
                    ALLOWED_DOMAINS,
                    AUTH_SIGNALS,
                    resolve_dns=True,
                )
                if target_error:
                    raise ValueError(f"redirect target blocked: {target_error}: {current_url}")
                resp = session.head(
                    current_url,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
                is_redirect = resp.is_redirect is True or resp.status_code in {301, 302, 303, 307, 308}
                if not is_redirect:
                    break
                location = resp.headers.get("Location", "")
                resp.close()
                if redirect_count >= 5 or not location:
                    raise ValueError("invalid or excessive redirect chain")
                current_url = urllib.parse.urljoin(current_url, location)
            else:
                raise ValueError("redirect limit exceeded")
        except (requests.RequestException, ValueError) as exc:
            issues.append(Issue("error", sid, url, f"Network error: {exc}"))
            continue

        final_url = resp.url if isinstance(getattr(resp, "url", None), str) else current_url
        final_error = validate_public_url(final_url, ALLOWED_DOMAINS, AUTH_SIGNALS)
        if final_error:
            resp.close()
            issues.append(Issue("error", sid, url, f"Final URL blocked: {final_error}: {final_url}"))
            continue

        # Final URL changed
        if final_url != url and final_url.rstrip("/") != url.rstrip("/"):
            issues.append(Issue(
                "warning", sid, url,
                f"URL redirected to: {final_url} — update canonical_url in sidecar"
            ))

        # 4xx/5xx
        if resp.status_code == 404:
            issues.append(Issue("error", sid, url, "404 Not Found — source may be moved or removed"))
        elif resp.status_code == 401 or resp.status_code == 403:
            issues.append(Issue("error", sid, url, f"HTTP {resp.status_code} — source now requires authentication"))
        elif resp.status_code >= 400:
            issues.append(Issue("warning", sid, url, f"HTTP {resp.status_code} — check source availability"))
        resp.close()

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check sidecar freshness, review dates, and optionally network status."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Offline check only — metadata, dates, hash comparison against local cache",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Also re-HEAD approved source URLs to detect redirects and HTTP errors",
    )
    parser.add_argument(
        "--sidecar",
        type=Path,
        default=None,
        help="Check a single .source.json file instead of the whole corpus",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not args.offline and not args.network:
        parser.error("Specify at least one of --offline or --network")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.sidecar:
        sidecar_paths = [args.sidecar]
    else:
        sidecar_paths = sorted(RESOURCES_DIR.rglob("*.source.json"))

    log.info("Checking %d sidecar(s)...", len(sidecar_paths))

    all_issues: list[Issue] = []

    for path in sidecar_paths:
        if args.offline or args.network:
            all_issues.extend(check_sidecar_offline(path))
        if args.network:
            all_issues.extend(check_sidecar_network(path))

    # Report
    errors = [i for i in all_issues if i.severity == "error"]
    warnings = [i for i in all_issues if i.severity == "warning"]

    print(f"\nFreshness check: {len(sidecar_paths)} sidecar(s)")
    print(f"  Errors   : {len(errors)}")
    print(f"  Warnings : {len(warnings)}")

    if all_issues:
        print()
        for issue in all_issues:
            print(str(issue))
            print()

    if not args.network:
        print("(Network rechecks skipped — run with --network to detect redirects/404s)")

    print("\nIMPORTANT: This tool reports changes. It does NOT rewrite resource files.")
    print("Resource authors must review source changes and update Markdown manually.")

    import sys
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
