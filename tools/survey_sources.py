#!/usr/bin/env python3
"""
survey_sources.py — Agent 5: metadata-only source survey

Discovers candidate public NCF URLs from robots.txt and sitemaps WITHOUT
downloading page bodies. Produces a deterministic JSONL candidate list and
a human-readable Markdown summary under resources/inventory/.

Usage:
    python tools/survey_sources.py
    python tools/survey_sources.py --config resources/inventory/survey-config.json
    python tools/survey_sources.py --out resources/inventory
    python tools/survey_sources.py --dry-run

Rules enforced:
  - HTTPS only
  - Domain allowlist (ncf.edu subdomains only by default)
  - No page body downloads — HEAD requests or sitemap XML only
  - Respects robots.txt Disallow rules
  - Identifies sitemaps from robots.txt before guessing paths
  - Rate-limited (configurable, default 1 req/sec)
  - Identifies authentication redirects and stops
"""

import argparse
import json
import logging
import re
import time
import urllib.robotparser
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    raise SystemExit(
        "Missing dependency: pip install requests\n"
        "Install all dev dependencies with: pip install -e '.[dev]'"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "0.1.0"

DEFAULT_CONFIG = {
    "allowed_domains": [
        "ncf.edu",
        "www.ncf.edu",
        "catalog.ncf.edu",
        "banapps02.ncf.edu",
        "ncfnow.ncf.edu",
    ],
    "seed_robots_url": "https://www.ncf.edu/robots.txt",
    "extra_sitemaps": [],
    "rate_limit_seconds": 1.0,
    "request_timeout_seconds": 15,
    "max_candidates": 2000,
    "user_agent": "ncfbot-survey/0.1 (public-info-bot class project; contact biocosmosmythos@gmail.com)",
    # Strings that suggest a URL requires authentication — skip these
    "auth_signals": [
        "login", "signin", "auth", "sso", "myncf", "canvas",
        "banner", "self-service", "secure", "account", "portal",
    ],
}

# Sitemap XML namespaces
SITEMAP_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("survey_sources")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def make_session(user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


def is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    """Return True if the URL's hostname is in or a subdomain of any allowed domain."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(
        host == d or host.endswith("." + d)
        for d in allowed_domains
    )


def looks_like_auth(url: str, auth_signals: list[str]) -> bool:
    """Return True if any auth signal appears in the URL path."""
    lower = url.lower()
    return any(sig in lower for sig in auth_signals)


def safe_get(
    session: requests.Session,
    url: str,
    timeout: int,
    rate: float,
    dry_run: bool = False,
) -> Optional[requests.Response]:
    """GET with rate limiting, timeout, and auth-redirect detection."""
    if dry_run:
        log.debug("DRY-RUN skip GET %s", url)
        return None
    time.sleep(rate)
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        # Detect login-page redirects
        if any(looks_like_auth(r.url, DEFAULT_CONFIG["auth_signals"])
               for r in resp.history):
            log.warning("Auth redirect detected for %s — skipping", url)
            return None
        return resp
    except requests.RequestException as exc:
        log.warning("GET failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# robots.txt parsing
# ---------------------------------------------------------------------------

def fetch_sitemaps_from_robots(
    robots_url: str,
    session: requests.Session,
    timeout: int,
    rate: float,
    dry_run: bool,
) -> list[str]:
    """Return sitemap URLs listed in robots.txt."""
    log.info("Fetching robots.txt: %s", robots_url)
    resp = safe_get(session, robots_url, timeout, rate, dry_run)
    if not resp or resp.status_code != 200:
        log.warning("Could not fetch robots.txt (status %s)", resp.status_code if resp else "n/a")
        return []

    sitemaps = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            sm_url = line.split(":", 1)[1].strip()
            if sm_url.startswith("https://"):
                sitemaps.append(sm_url)
                log.info("  Found sitemap: %s", sm_url)
    return sitemaps


def build_robots_parser(
    robots_url: str,
    session: requests.Session,
    timeout: int,
    rate: float,
    dry_run: bool,
) -> urllib.robotparser.RobotFileParser:
    """Return a populated RobotFileParser for the given robots.txt URL."""
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    log.info("Parsing robots.txt disallow rules...")
    resp = safe_get(session, robots_url, timeout, rate, dry_run)
    if resp and resp.status_code == 200:
        rp.parse(resp.text.splitlines())
    return rp


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------

def parse_sitemap(
    sm_url: str,
    session: requests.Session,
    config: dict,
    dry_run: bool,
    visited: set[str],
) -> list[dict]:
    """
    Recursively parse a sitemap or sitemap index.
    Returns a list of candidate dicts (url, lastmod, sitemap_source).
    Does NOT download page bodies.
    """
    if sm_url in visited:
        return []
    visited.add(sm_url)

    if not is_allowed_domain(sm_url, config["allowed_domains"]):
        log.warning("Sitemap URL outside allowlist, skipping: %s", sm_url)
        return []

    log.info("Fetching sitemap: %s", sm_url)
    resp = safe_get(
        session, sm_url,
        config["request_timeout_seconds"],
        config["rate_limit_seconds"],
        dry_run,
    )
    if not resp or resp.status_code != 200:
        log.warning("Could not fetch sitemap %s", sm_url)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        log.warning("XML parse error in %s: %s", sm_url, exc)
        return []

    tag = root.tag.lower()
    candidates = []

    # Detect whether the document uses the standard sitemap namespace
    ns_uri = SITEMAP_NS["sm"]
    has_ns = root.tag.startswith("{" + ns_uri + "}")
    sm_pfx = "sm:" if has_ns else ""
    ns_arg = SITEMAP_NS if has_ns else {}

    # Sitemap index — recurse into child sitemaps
    if "sitemapindex" in tag:
        for sitemap_el in root.findall(f"{sm_pfx}sitemap", ns_arg):
            loc_el = sitemap_el.find(f"{sm_pfx}loc", ns_arg)
            if loc_el is not None and loc_el.text:
                child_url = loc_el.text.strip()
                candidates.extend(
                    parse_sitemap(child_url, session, config, dry_run, visited)
                )

    # Regular urlset
    elif "urlset" in tag:
        for url_el in root.findall(f"{sm_pfx}url", ns_arg):
            loc_el = url_el.find(f"{sm_pfx}loc", ns_arg)
            lastmod_el = url_el.find(f"{sm_pfx}lastmod", ns_arg)
            if loc_el is None or not loc_el.text:
                continue
            page_url = loc_el.text.strip()
            lastmod = lastmod_el.text.strip() if lastmod_el is not None and lastmod_el.text else None

            if not page_url.startswith("https://"):
                continue
            if not is_allowed_domain(page_url, config["allowed_domains"]):
                continue

            candidates.append({
                "url": page_url,
                "lastmod": lastmod,
                "sitemap_source": sm_url,
            })

    return candidates


# ---------------------------------------------------------------------------
# Candidate classification
# ---------------------------------------------------------------------------

TOPIC_PATTERNS: list[tuple[str, str]] = [
    (r"/catalog/", "catalog"),
    (r"/registrar/", "registrar"),
    (r"/advising/", "advising"),
    (r"/admissions/", "admissions"),
    (r"/financial.?aid/", "financial-aid"),
    (r"/tuition|/cost|/fees", "cost"),
    (r"/housing|/dining|/residence", "housing-dining"),
    (r"/academic.?calendar|/calendar", "calendar"),
    (r"/directory|/faculty|/staff", "directory"),
    (r"/about|/mission|/history|/accredit", "about-ncf"),
    (r"/programs?/|/majors?/|/aoc/", "programs"),
    (r"/isp|/independent.study", "isp"),
    (r"/library", "library"),
    (r"/athletics|/sports", "athletics"),
    (r"/wellness|/counseling|/health", "wellness"),
    (r"/campus.?life|/student.?life", "campus-life"),
    (r"/visit|/tour|/map|/parking", "visit"),
    (r"/alumni", "alumni"),
    (r"/news|/announcement", "news"),
    (r"/commencement|/graduation", "graduation"),
    (r"/accessibility|/disability", "accessibility"),
    (r"/title.?ix|/conduct|/clery", "policy"),
]

AUDIENCE_PATTERNS: list[tuple[str, str]] = [
    (r"/faculty|/staff|/provost|/hr/", "faculty"),
    (r"/admissions|/prospective|/apply|/visit", "outside"),
    (r"/student|/registrar|/advising|/catalog|/isp", "students"),
]


def classify_candidate(url: str) -> dict:
    """Guess topic and audience from the URL path. Does not fetch the page."""
    path = urllib.parse.urlparse(url).path.lower()

    topic = "other"
    for pattern, label in TOPIC_PATTERNS:
        if re.search(pattern, path):
            topic = label
            break

    audience = "unknown"
    for pattern, label in AUDIENCE_PATTERNS:
        if re.search(pattern, path):
            audience = label
            break

    auth_flag = looks_like_auth(url, DEFAULT_CONFIG["auth_signals"])

    return {
        "guessed_topic": topic,
        "guessed_audience": audience,
        "likely_authenticated": auth_flag,
        "review_state": "rejected" if auth_flag else "candidate",
        # Valid review_state values: candidate, approved, deferred, rejected, historical, superseded
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_jsonl(candidates: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    log.info("Wrote %d candidates → %s", len(candidates), out_path)


def write_markdown_summary(
    candidates: list[dict],
    config: dict,
    surveyed_at: str,
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(candidates)
    rejected = sum(1 for c in candidates if c["review_state"] == "rejected")
    by_topic: dict[str, int] = {}
    by_audience: dict[str, int] = {}
    for c in candidates:
        by_topic[c["guessed_topic"]] = by_topic.get(c["guessed_topic"], 0) + 1
        by_audience[c["guessed_audience"]] = by_audience.get(c["guessed_audience"], 0) + 1

    lines = [
        "# NCFBot Public Source Survey",
        "",
        f"**Surveyed:** {surveyed_at}  ",
        f"**Tool version:** survey_sources.py {VERSION}  ",
        f"**Seed:** {config['seed_robots_url']}  ",
        f"**Allowed domains:** {', '.join(config['allowed_domains'])}  ",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total candidates found | {total} |",
        f"| Auto-rejected (auth signals) | {rejected} |",
        f"| Remaining candidates | {total - rejected} |",
        "",
        "## By Guessed Topic",
        "",
        "| Topic | Count |",
        "|-------|-------|",
    ]
    for topic, count in sorted(by_topic.items(), key=lambda x: -x[1]):
        lines.append(f"| {topic} | {count} |")

    lines += [
        "",
        "## By Guessed Audience",
        "",
        "| Audience | Count |",
        "|----------|-------|",
    ]
    for aud, count in sorted(by_audience.items(), key=lambda x: -x[1]):
        lines.append(f"| {aud} | {count} |")

    lines += [
        "",
        "## Next Steps",
        "",
        "1. Review `survey-candidates.jsonl` and change `review_state` to `approved` or `deferred` for each URL.",
        "2. Run `fetch_sources.py` only against approved URLs.",
        "3. Resource authors write Markdown summaries from fetched content — do NOT promote raw content automatically.",
        "",
        "## Notes",
        "",
        "- This file is machine-generated. Do not edit by hand.",
        "- URL classifications are heuristic guesses from path patterns only — no page bodies were downloaded.",
        "- `likely_authenticated: true` URLs were auto-rejected and must not be fetched.",
        "- Re-run this script to refresh the candidate list; compare diffs to detect new or removed pages.",
    ]

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Wrote Markdown summary → %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_config(config_path: Optional[Path]) -> dict:
    config = dict(DEFAULT_CONFIG)
    if config_path and config_path.exists():
        with config_path.open(encoding="utf-8") as f:
            overrides = json.load(f)
        config.update(overrides)
        log.info("Loaded config from %s", config_path)
    else:
        log.info("Using default config")
    return config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Metadata-only NCF public source survey. No page bodies downloaded."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to JSON config file (default: built-in defaults)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("resources/inventory"),
        help="Output directory for JSONL and Markdown (default: resources/inventory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip all network requests; useful for testing the output structure",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = load_config(args.config)
    session = make_session(config["user_agent"])
    surveyed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Get sitemaps from robots.txt
    sitemap_urls: list[str] = fetch_sitemaps_from_robots(
        config["seed_robots_url"], session,
        config["request_timeout_seconds"],
        config["rate_limit_seconds"],
        args.dry_run,
    )

    # 2. Add any extra sitemaps from config
    sitemap_urls += [s for s in config.get("extra_sitemaps", []) if s not in sitemap_urls]

    if not sitemap_urls and not args.dry_run:
        log.warning(
            "No sitemaps found in robots.txt. "
            "Try adding sitemap URLs manually to survey-config.json extra_sitemaps."
        )

    # 3. Build robots disallow parser
    rp = build_robots_parser(
        config["seed_robots_url"], session,
        config["request_timeout_seconds"],
        config["rate_limit_seconds"],
        args.dry_run,
    )

    # 4. Parse all sitemaps
    raw_candidates: list[dict] = []
    visited_sitemaps: set[str] = set()
    for sm_url in sitemap_urls:
        raw_candidates.extend(
            parse_sitemap(sm_url, session, config, args.dry_run, visited_sitemaps)
        )

    log.info("Raw candidates from sitemaps: %d", len(raw_candidates))

    # 5. Deduplicate by URL
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for c in raw_candidates:
        if c["url"] not in seen_urls:
            seen_urls.add(c["url"])
            deduped.append(c)

    log.info("After deduplication: %d", len(deduped))

    # 6. Check robots disallow and classify
    final: list[dict] = []
    for c in deduped:
        disallowed = not rp.can_fetch(config["user_agent"], c["url"])
        classification = classify_candidate(c["url"])
        record = {
            "url": c["url"],
            "lastmod": c.get("lastmod"),
            "sitemap_source": c.get("sitemap_source"),
            "robots_disallowed": disallowed,
            "surveyed_at": surveyed_at,
            **classification,
        }
        if disallowed:
            record["review_state"] = "rejected"
            record["rejection_reason"] = "robots_disallowed"
        elif classification["likely_authenticated"]:
            record["rejection_reason"] = "auth_signal_in_url"
        final.append(record)

    # 7. Cap if needed
    max_c = config.get("max_candidates", 2000)
    if len(final) > max_c:
        log.warning("Capping candidates at %d (found %d)", max_c, len(final))
        final = final[:max_c]

    # 8. Write outputs
    out_dir = args.out
    write_jsonl(final, out_dir / "survey-candidates.jsonl")
    write_markdown_summary(final, config, surveyed_at, out_dir / "survey-summary.md")

    # 9. Write a config template if none existed
    config_out = out_dir / "survey-config.json"
    if not config_out.exists():
        config_out.parent.mkdir(parents=True, exist_ok=True)
        with config_out.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
            f.write("\n")
        log.info("Wrote default config template → %s", config_out)

    approved = sum(1 for c in final if c["review_state"] == "candidate")
    rejected = sum(1 for c in final if c["review_state"] == "rejected")
    print(f"\nSurvey complete: {len(final)} total | {approved} candidates | {rejected} rejected")
    print(f"Review: {out_dir}/survey-candidates.jsonl")
    print(f"Summary: {out_dir}/survey-summary.md")


if __name__ == "__main__":
    main()
