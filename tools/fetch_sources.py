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

    # Dry run — show what would be fetched without downloading
    python tools/fetch_sources.py --all --dry-run

Outputs (in .cache/sources/<sha256-prefix>/<filename>):
    <hash>.body      — raw response body
    <hash>.meta.json — status, headers, canonical URL, retrieval timestamp, sha256
"""

import argparse
import email.utils
import hashlib
import json
import logging
import os
import time
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    raise SystemExit("Missing dependency: pip install requests")

from source_http import (
    DEFAULT_AUTH_SIGNALS,
    is_allowed_domain as shared_is_allowed_domain,
    looks_like_auth as shared_looks_like_auth,
    make_no_cookie_session,
    private_target_error,
    validate_public_url,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "0.2.0"

ALLOWLIST_PATH = Path("resources/inventory/fetch-domain-allowlist.json")
DEFAULT_ALLOWED_DOMAINS = [
    "ncf.edu",
    "docs.google.com",
    "cm.maxient.com",
    "getfortifyfl.com",
]


def load_allowed_domains(path: Path = ALLOWLIST_PATH) -> list[str]:
    if not path.exists():
        return list(DEFAULT_ALLOWED_DOMAINS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        domains = data["domains"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid source domain allowlist {path}: {exc}") from exc
    if not isinstance(domains, list) or not domains or not all(
        isinstance(domain, str) and domain and "/" not in domain for domain in domains
    ):
        raise RuntimeError(f"Invalid domains in source allowlist {path}")
    return list(dict.fromkeys(domain.lower().rstrip(".") for domain in domains))


ALLOWED_DOMAINS = load_allowed_domains()

AUTH_SIGNALS = list(DEFAULT_AUTH_SIGNALS)

ALLOWED_CONTENT_TYPES = [
    "text/html",
    "application/xhtml+xml",
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
]

MAX_BODY_BYTES = 10 * 1024 * 1024  # 10 MB hard cap
RATE_LIMIT_SECONDS = 1.5
REQUEST_TIMEOUT = 20
CACHE_DIR = Path(".cache/sources")
USER_AGENT = "ncfbot-fetch/0.2 (+https://github.com/mhulden/ncfbot)"

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
    return shared_is_allowed_domain(url, ALLOWED_DOMAINS)


def is_private_network(url: str) -> bool:
    return private_target_error(url) is not None


def looks_like_auth(url: str) -> bool:
    return shared_looks_like_auth(url, AUTH_SIGNALS)


def validate_url(url: str, *, resolve_dns: bool = False) -> Optional[str]:
    """Return an error string if the URL should not be fetched, else None."""
    return validate_public_url(
        url,
        ALLOWED_DOMAINS,
        AUTH_SIGNALS,
        resolve_dns=resolve_dns,
    )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def cache_path_for(url: str) -> Path:
    """Deterministic cache directory based on URL hash."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    return CACHE_DIR / url_hash[:2] / url_hash


def is_cached(url: str) -> Optional[dict]:
    """Return cached metadata dict if a valid cache entry exists, else None."""
    body_path = cache_path_for(url).with_suffix(".body")
    meta_path = cache_path_for(url).with_suffix(".meta.json")
    if body_path.exists() and meta_path.exists():
        try:
            with meta_path.open(encoding="utf-8") as f:
                metadata = json.load(f)
            actual_sha256 = hashlib.sha256(body_path.read_bytes()).hexdigest()
            if metadata.get("sha256") == actual_sha256:
                return metadata
        except Exception:
            return None
    return None


def write_cache(url: str, body: bytes, meta: dict) -> Path:
    """Write body and metadata to cache. Returns the cache directory."""
    cache_dir = cache_path_for(url)
    cache_dir.mkdir(parents=True, exist_ok=True)
    body_path = cache_dir.with_suffix(".body")
    meta_path = cache_dir.with_suffix(".meta.json")
    def atomic_write(path: Path, payload: bytes) -> None:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    atomic_write(body_path, body)
    atomic_write(meta_path, (json.dumps(meta, indent=2) + "\n").encode())
    return cache_dir


def normalize_http_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

def make_session() -> requests.Session:
    return make_no_cookie_session(
        USER_AGENT,
        "text/html,application/xhtml+xml,application/xml,application/pdf;q=0.9,*/*;q=0.8",
    )


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
    result = {
        "url": url,
        "status": "pending",
        "cached": False,
        "error": None,
        "sha256": None,
    }

    # Pre-flight validation
    err = validate_url(url)
    if err:
        result["error"] = f"blocked: {err}"
        result["status"] = "blocked"
        log.warning("SKIP %s — %s", url, err)
        return result

    # Check cache
    if not force:
        cached_meta = is_cached(url)
        if cached_meta:
            log.info("CACHED %s", url)
            result.update({
                "status": "cached",
                "cached": True,
                "sha256": cached_meta.get("sha256"),
                "content_type": cached_meta.get("content_type"),
                "retrieved_at": cached_meta.get("retrieved_at"),
                "cache_path": str(cache_path_for(url)),
            })
            return result

    if dry_run:
        log.info("DRY-RUN would fetch: %s", url)
        result["status"] = "planned"
        return result

    time.sleep(RATE_LIMIT_SECONDS)

    # Follow redirects manually, validating every hop and the final destination
    current_url = url
    hops: list[str] = []
    try:
        while True:
            hop_err = validate_url(
                current_url,
                resolve_dns=isinstance(session, requests.Session),
            )
            if hop_err:
                result["error"] = f"redirect to blocked URL ({hop_err}): {current_url}"
                result["status"] = "blocked"
                log.warning("REDIRECT BLOCKED %s → %s (%s)", url, current_url, hop_err)
                return result
            resp = session.get(
                current_url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
            is_redirect = resp.is_redirect is True or resp.status_code in {301, 302, 303, 307, 308}
            if is_redirect:
                if len(hops) >= 5:
                    resp.close()
                    result["error"] = "redirect limit exceeded"
                    result["status"] = "failed"
                    return result
                next_url = resp.headers.get("Location", "")
                if not next_url:
                    resp.close()
                    result["error"] = "redirect response omitted Location header"
                    result["status"] = "failed"
                    return result
                next_url = urllib.parse.urljoin(current_url, next_url)
                hops.append(next_url)
                resp.close()
                current_url = next_url
                continue
            break
    except requests.RequestException as exc:
        result["error"] = str(exc)
        result["status"] = "failed"
        log.warning("FETCH ERROR %s: %s", url, exc)
        return result

    # Auth check on the final landed URL
    final_url = resp.url if isinstance(getattr(resp, "url", None), str) else current_url
    final_error = validate_url(final_url)
    if final_error:
        resp.close()
        result["error"] = f"final URL blocked ({final_error}): {final_url}"
        result["status"] = "blocked"
        log.warning("FINAL URL BLOCKED %s", final_url)
        return result
    if looks_like_auth(final_url):
        resp.close()
        result["error"] = f"auth signal in final URL: {current_url}"
        result["status"] = "blocked"
        log.warning("AUTH URL %s", current_url)
        return result

    if not 200 <= resp.status_code < 300:
        resp.close()
        result["error"] = f"HTTP {resp.status_code}"
        result["status"] = "failed"
        log.warning("HTTP ERROR %s — %s", url, resp.status_code)
        return result

    # Content-type check
    ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if not any(ct.startswith(allowed) for allowed in ALLOWED_CONTENT_TYPES):
        resp.close()
        result["error"] = f"disallowed content-type: {ct}"
        result["status"] = "blocked"
        log.warning("SKIP %s — content-type: %s", url, ct)
        return result

    # Size-limited read
    content_length = resp.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                resp.close()
                result["error"] = f"body exceeds size limit ({MAX_BODY_BYTES} bytes)"
                result["status"] = "blocked"
                return result
        except ValueError:
            pass

    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            resp.close()
            result["error"] = f"body exceeds size limit ({MAX_BODY_BYTES} bytes)"
            result["status"] = "blocked"
            log.warning("SIZE LIMIT %s", url)
            return result
        chunks.append(chunk)

    body = b"".join(chunks)
    resp.close()
    sha256 = hashlib.sha256(body).hexdigest()
    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    meta = {
        "url": url,
        "canonical_url": final_url,
        "status_code": resp.status_code,
        "content_type": ct,
        "content_length": len(body),
        "sha256": sha256,
        "retrieved_at": retrieved_at,
        "last_modified": normalize_http_datetime(resp.headers.get("Last-Modified")),
        "etag": resp.headers.get("ETag"),
        "redirect_chain": hops,
        "tool_version": VERSION,
    }

    cache_path = write_cache(url, body, meta)
    log.info("FETCHED %s [%d bytes, sha256=%s...]", url, len(body), sha256[:12])

    result.update({
        "status": "fetched",
        "canonical_url": final_url,
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
    ok = [r for r in results if r.get("status") in {"fetched", "cached"}]
    planned = [r for r in results if r.get("status") == "planned"]
    errs = [r for r in results if r.get("status") in {"blocked", "failed"}]
    cached = [r for r in results if r.get("cached")]

    print(f"\nFetch complete: {len(results)} URLs")
    print(f"  Fetched fresh : {len(ok) - len(cached)}")
    print(f"  From cache    : {len(cached)}")
    print(f"  Dry-run plans : {len(planned)}")
    print(f"  Errors/skipped: {len(errs)}")
    if errs:
        print("\nErrors:")
        for r in errs:
            print(f"  {r['url']}: {r['error']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
