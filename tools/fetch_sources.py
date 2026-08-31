#!/usr/bin/env python3
"""
fetch_sources.py — Agent 5: approved-source fetcher

Downloads page bodies ONLY for URLs that have been explicitly approved in
a .source.json sidecar (public_access_verified: true). Saves raw bodies to
a gitignored local cache. Never auto-promotes content to resource Markdown.

Usage:
    # Fetch all approved sources across the repo
    python tools/fetch_sources.py --all

    # Fetch sources referenced by one sidecar
    python tools/fetch_sources.py --sidecar resources/students/academic-model.source.json

    # Fetch a single URL (must still be HTTPS and in the allowlist)
    python tools/fetch_sources.py --url https://catalog.ncf.edu/undergraduate/

    # Dry run — show what would be fetched without downloading
    python tools/fetch_sources.py --all --dry-run

Outputs (in .cache/sources/<sha256-prefix>/<filename>):
    <hash>.body      — raw response body
    <hash>.meta.json — status, headers, canonical URL, retrieval timestamp, sha256
"""

import argparse
import hashlib
import json
import logging
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    raise SystemExit("Missing dependency: pip install requests")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "0.1.0"

ALLOWED_DOMAINS = [
    "ncf.edu",
    "www.ncf.edu",
    "catalog.ncf.edu",
    "banapps02.ncf.edu",
    "ncfnow.ncf.edu",
]

AUTH_SIGNALS = [
    "login", "signin", "auth", "sso", "myncf", "canvas",
    "self-service", "secure", "account", "portal", "myaccount",
]

ALLOWED_CONTENT_TYPES = [
    "text/html",
    "application/xhtml+xml",
    "application/pdf",
    "text/plain",
]

MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB hard cap
RATE_LIMIT_SECONDS = 1.5
REQUEST_TIMEOUT = 20
CACHE_DIR = Path(".cache/sources")
USER_AGENT = "ncfbot-fetch/0.1 (public-info-bot class project; contact biocosmosmythos@gmail.com)"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch_sources")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def is_allowed_domain(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS)


def is_private_network(url: str) -> bool:
    """Reject localhost, 127.x, 10.x, 192.168.x, etc."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return True
    private = ["localhost", "127.", "10.", "172.16.", "192.168.", "0.0.0.0", "::1"]
    return any(host == p or host.startswith(p) for p in private)


def looks_like_auth(url: str) -> bool:
    lower = url.lower()
    return any(sig in lower for sig in AUTH_SIGNALS)


def validate_url(url: str) -> Optional[str]:
    """Return an error string if the URL should not be fetched, else None."""
    if not url.startswith("https://"):
        return "not HTTPS"
    if is_private_network(url):
        return "private/local network target"
    if not is_allowed_domain(url):
        return f"domain not in allowlist: {urllib.parse.urlparse(url).netloc}"
    if looks_like_auth(url):
        return "auth signal detected in URL"
    return None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def cache_path_for(url: str) -> Path:
    """Deterministic cache directory based on URL hash."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    return CACHE_DIR / url_hash[:2] / url_hash


def is_cached(url: str) -> Optional[dict]:
    """Return cached metadata dict if a valid cache entry exists, else None."""
    meta_path = cache_path_for(url).with_suffix(".meta.json")
    if meta_path.exists():
        try:
            with meta_path.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def write_cache(url: str, body: bytes, meta: dict) -> Path:
    """Write body and metadata to cache. Returns the cache directory."""
    cache_dir = cache_path_for(url)
    cache_dir.mkdir(parents=True, exist_ok=True)
    body_path = cache_dir.with_suffix(".body")
    meta_path = cache_dir.with_suffix(".meta.json")
    body_path.write_bytes(body)
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    return cache_dir


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class _NoCookiePolicy:
    """Cookie policy that rejects every cookie — prevents storage and resending."""
    def set_ok(self, cookie, request):
        return False
    def return_ok(self, cookie, request):
        return False
    def domain_return_ok(self, domain, request):
        return False
    def path_return_ok(self, path, request):
        return False
    is_blocking = True
    is_liberal = False
    netscape = True
    rfc2965 = False
    hide_cookie2 = False


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8",
    })
    # Disable cookie storage entirely — never accumulate or resend cookies
    jar = requests.cookies.RequestsCookieJar()
    jar.set_policy(_NoCookiePolicy())
    s.cookies = jar
    s.max_redirects = 5
    return s


def fetch_url(
    url: str,
    session: requests.Session,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    Fetch one URL. Returns a result dict with keys:
      url, status, cached, sha256, content_type, retrieved_at, error, cache_path
    """
    result = {"url": url, "cached": False, "error": None, "sha256": None}

    # Pre-flight validation
    err = validate_url(url)
    if err:
        result["error"] = f"blocked: {err}"
        log.warning("SKIP %s — %s", url, err)
        return result

    # Check cache
    if not force:
        cached_meta = is_cached(url)
        if cached_meta:
            log.info("CACHED %s", url)
            result.update({
                "cached": True,
                "sha256": cached_meta.get("sha256"),
                "content_type": cached_meta.get("content_type"),
                "retrieved_at": cached_meta.get("retrieved_at"),
                "cache_path": str(cache_path_for(url)),
            })
            return result

    if dry_run:
        log.info("DRY-RUN would fetch: %s", url)
        result["error"] = "dry-run"
        return result

    time.sleep(RATE_LIMIT_SECONDS)

    # Follow redirects manually, validating every hop and the final destination
    current_url = url
    hops: list[str] = []
    try:
        while True:
            hop_err = validate_url(current_url)
            if hop_err:
                result["error"] = f"redirect to blocked URL ({hop_err}): {current_url}"
                log.warning("REDIRECT BLOCKED %s → %s (%s)", url, current_url, hop_err)
                return result
            is_final = len(hops) >= 5
            resp = session.get(
                current_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                stream=is_final,
            )
            if resp.is_redirect and not is_final:
                next_url = resp.headers.get("Location", "")
                next_url = urllib.parse.urljoin(current_url, next_url)
                hops.append(current_url)
                current_url = next_url
            else:
                break
    except requests.RequestException as exc:
        result["error"] = str(exc)
        log.warning("FETCH ERROR %s: %s", url, exc)
        return result

    # Auth check on the final landed URL
    if looks_like_auth(resp.url if hasattr(resp, "url") else current_url):
        result["error"] = f"auth signal in final URL: {current_url}"
        log.warning("AUTH URL %s", current_url)
        return result

    # Content-type check
    ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if not any(ct.startswith(allowed) for allowed in ALLOWED_CONTENT_TYPES):
        result["error"] = f"disallowed content-type: {ct}"
        log.warning("SKIP %s — content-type: %s", url, ct)
        return result

    # Size-limited read
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            result["error"] = f"body exceeds size limit ({MAX_BODY_BYTES} bytes)"
            log.warning("SIZE LIMIT %s", url)
            return result
        chunks.append(chunk)

    body = b"".join(chunks)
    sha256 = hashlib.sha256(body).hexdigest()
    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    meta = {
        "url": url,
        "canonical_url": resp.url,
        "status_code": resp.status_code,
        "content_type": ct,
        "content_length": len(body),
        "sha256": sha256,
        "retrieved_at": retrieved_at,
        "last_modified": resp.headers.get("Last-Modified"),
        "etag": resp.headers.get("ETag"),
        "redirect_chain": [r.url for r in resp.history],
        "tool_version": VERSION,
    }

    cache_path = write_cache(url, body, meta)
    log.info("FETCHED %s [%d bytes, sha256=%s...]", url, len(body), sha256[:12])

    result.update({
        "sha256": sha256,
        "content_type": ct,
        "retrieved_at": retrieved_at,
        "status_code": resp.status_code,
        "cache_path": str(cache_path),
    })
    return result


# ---------------------------------------------------------------------------
# Sidecar source collection
# ---------------------------------------------------------------------------

def urls_from_sidecar(sidecar_path: Path) -> list[str]:
    """Return all canonical_url values from a .source.json where public_access_verified is true."""
    try:
        with sidecar_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        log.warning("Could not read sidecar %s: %s", sidecar_path, exc)
        return []

    urls = []
    for src in data.get("sources", []):
        if src.get("public_access_verified") is True:
            url = src.get("canonical_url", "").strip()
            if url:
                urls.append(url)
    return urls


def find_all_sidecars(root: Path = Path("resources")) -> list[Path]:
    return sorted(root.rglob("*.source.json"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch approved public NCF sources into the local cache."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Fetch all approved URLs across every .source.json in resources/",
    )
    group.add_argument(
        "--sidecar",
        type=Path,
        help="Fetch approved URLs from a single .source.json sidecar",
    )
    # --url removed: bypassed the sidecar approval gate. All fetches must flow
    # through a .source.json with public_access_verified: true. To fetch a new
    # URL, add it to a sidecar first, then run --sidecar.
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even if a cache entry already exists",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fetched without downloading",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    session = make_session()
    results = []

    if args.sidecar:
        urls = urls_from_sidecar(args.sidecar)
        if not urls:
            log.warning("No approved URLs found in %s", args.sidecar)
    else:  # --all
        sidecars = find_all_sidecars()
        log.info("Found %d sidecar files", len(sidecars))
        urls = []
        for sc in sidecars:
            urls.extend(urls_from_sidecar(sc))
        # Deduplicate
        seen = set()
        urls = [u for u in urls if not (u in seen or seen.add(u))]

    log.info("URLs to fetch: %d", len(urls))

    for url in urls:
        result = fetch_url(url, session, dry_run=args.dry_run, force=args.force)
        results.append(result)

    # Summary
    ok = [r for r in results if not r.get("error") or r.get("cached")]
    errs = [r for r in results if r.get("error") and not r.get("cached")]
    cached = [r for r in results if r.get("cached")]

    print(f"\nFetch complete: {len(results)} URLs")
    print(f"  Fetched fresh : {len(ok) - len(cached)}")
    print(f"  From cache    : {len(cached)}")
    print(f"  Errors/skipped: {len(errs)}")
    if errs:
        print("\nErrors:")
        for r in errs:
            print(f"  {r['url']}: {r['error']}")


if __name__ == "__main__":
    main()
